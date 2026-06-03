"""APScheduler 定时任务 — Phase 3.11

5 个 push cron 任务(全部 Asia/Shanghai 时区):
  - 08:30 CN  mon-fri  盘前简报
  - 12:55 CN  mon-fri  午盘观察
  - 14:30 CN  mon-fri  尾盘观察
  - 15:30 CN  mon-fri  收盘复盘(当日资金流向已定)
  - 20:00 CN  sun      周报(总结本周主线)

每个 job 流程:
  1. SignalEngine.generate_signals_for_holdings()
  2. build_holdings_by_sector
  3. AIAnalyst.analyze_signals(失败 fallback "")
  4. ServerChanNotifier.send(title, content)
  5. push_logs 写一行(成功/失败都写)
  6. 任何一步异常都 try/except 吞掉,不能让 scheduler 崩

R6 不过度设计:不上 Celery/Redis 任务队列。APScheduler 单机 +
BackgroundScheduler 够用,符合"个人自用工具"定位。

Server酱 免费版日限 5 条:工作日 4,周日 1。
"""

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.db import SessionLocal
from src.models.enums import PushType
from src.services.ai_analyst import AIAnalyst
from src.services.data_fetcher import fetch_and_store_today
from src.services.fetch_health import record_fetch_exception, record_fetch_result
from src.services.freshness import assess_daily_freshness
from src.services.holdings_summary import build_holdings_by_sector
from src.services.notifier import ServerChanNotifier
from src.services.push_log import write_push_log
from src.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)

CN_TZ = "Asia/Shanghai"
_DAILY_FRESHNESS_GATED_PUSH_TYPES = {
    PushType.EVENING.value,
    PushType.WEEKLY.value,
}


# 5 个 push cron job 配置
JOBS_CONFIG: list[dict] = [
    {
        "job_id": "pre_market",
        "push_type": PushType.MORNING.value,
        "cron": {"hour": 8, "minute": 30, "day_of_week": "mon-fri"},
        "title_label": "盘前简报",
        "macro_context": "盘前简报 — 开盘前的历史资金事实与持仓关注点",
    },
    {
        "job_id": "midday",
        "push_type": PushType.MIDDAY.value,
        "cron": {"hour": 12, "minute": 55, "day_of_week": "mon-fri"},
        "title_label": "午盘观察",
        "macro_context": "午盘观察 — 上午盘后主力资金动向与持仓关联事实",
    },
    {
        "job_id": "tail",
        "push_type": PushType.MIDDAY.value,
        "cron": {"hour": 14, "minute": 30, "day_of_week": "mon-fri"},
        "title_label": "尾盘观察",
        "macro_context": "盘中观察 — 尾盘前 30 分钟,关注主力是否兑现日内动作",
    },
    {
        "job_id": "close",
        "push_type": PushType.EVENING.value,
        "cron": {"hour": 15, "minute": 30, "day_of_week": "mon-fri"},
        "title_label": "收盘复盘",
        "macro_context": "收盘复盘 — 当日资金流向已定,判断明日延续性",
    },
    {
        "job_id": "weekly",
        "push_type": PushType.WEEKLY.value,
        "cron": {"hour": 20, "minute": 0, "day_of_week": "sun"},
        "title_label": "周报",
        "macro_context": "周报 — 总结本周主线 / 退潮主线,判断下周延续概率",
    },
]


class SignalScheduler:
    def __init__(self, timezone: str = CN_TZ):
        self.timezone = timezone
        self.scheduler: BackgroundScheduler = BackgroundScheduler(timezone=timezone)

    def register_jobs(self) -> None:
        """注册 5 个 push job + 1 个 daily_fetch job + 1 个 intraday_fetch job。

        ⚠️ 注意:scheduler 未启动时,APScheduler 的 add_job 会把任务放进
        pending list 而非按 ID 索引,此时 replace_existing=True 不会去重。
        生产里 lifespan 只 call 一次,不会撞到这个 quirk;但**别在 start()
        之前重复调用本方法**。
        """
        # 5 个推送 job(JOBS_CONFIG)
        for config in JOBS_CONFIG:
            trigger = CronTrigger(timezone=self.timezone, **config["cron"])
            self.scheduler.add_job(
                func=self._make_job_callable(config),
                trigger=trigger,
                id=config["job_id"],
                name=config["title_label"],
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=300,  # 5 min — VPS 重启后近期错过的也补一次
            )
            logger.info(
                "Registered job: id=%s push_type=%s cron=%s",
                config["job_id"], config["push_type"], config["cron"],
            )

        # 1 个数据采集 job(15:20 mon-fri,排在 close 推送 15:30 之前 10 分钟)
        # 注意:cron 用 mon-fri 不能跳 A 股节假日(春节等)。
        #     节假日那天会触发,但 akshare 返回空 / 旧数据,
        #     insert_*_rows 幂等保证不重复入库。引入节假日 lib 违反 R6,不做。
        fetch_cron = {"hour": 15, "minute": 20, "day_of_week": "mon-fri"}
        self.scheduler.add_job(
            func=self._make_fetch_callable(),
            trigger=CronTrigger(timezone=self.timezone, **fetch_cron),
            id="daily_fetch",
            name="每日数据采集",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info(
            "Registered job: id=daily_fetch (data collection) cron=%s",
            fetch_cron,
        )

        # 1 个盘中实时数据采集 job(Phase 5.1 PR15)
        # cron 设宽点(9-11/13-14 每 10 min),回调内部 is_in_trading_window
        # 二次过滤:只有 9:35-11:30 / 13:00-14:55 区间内才真正采集。
        # 这样 cron 简单 + 时间窗精确。集合竞价 9:30-9:35 不采(数据不稳)。
        intraday_cron = {
            "day_of_week": "mon-fri",
            "hour": "9-11,13-14",
            "minute": "*/10",
        }
        self.scheduler.add_job(
            func=self._make_intraday_fetch_callable(),
            trigger=CronTrigger(timezone=self.timezone, **intraday_cron),
            id="intraday_fetch",
            name="盘中实时数据采集",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,  # 1 min — 盘中错过就错过,不补
        )
        logger.info(
            "Registered job: id=intraday_fetch cron=%s (10min 内,9:35-11:30/13:00-14:55 才入库)",
            intraday_cron,
        )

    def _make_fetch_callable(self) -> Callable[[], None]:
        """daily_fetch 顶级吞掉异常 — 跟 push job 同样的安全契约。"""
        def _run():
            try:
                self._run_fetch_job()
            except Exception as e:
                logger.error(
                    "Job daily_fetch 顶级异常吞掉: %s: %s",
                    type(e).__name__, e,
                )

        return _run

    def _run_fetch_job(self) -> None:
        """采集今日板块资金流 + 4 大指数,幂等入库。"""
        logger.info("Job [daily_fetch] 开始执行")
        try:
            with SessionLocal() as session:
                stats = fetch_and_store_today(session)
            record_fetch_result(stats)
            logger.info("Job [daily_fetch] 完成: %s", stats)
        except Exception as e:
            record_fetch_exception(e)
            logger.error(
                "Job [daily_fetch] 内部失败但已吞掉: %s: %s",
                type(e).__name__, e,
            )

    def _make_intraday_fetch_callable(self) -> Callable[[], None]:
        """盘中采集回调。runtime 二次过滤交易窗口(集合竞价不采)。
        顶级吞异常,跟其它 job 同样契约。"""
        def _run():
            try:
                # 延迟 import 避免 scheduler module 加载时拉重链路
                from src.services.intraday_fetcher import (
                    fetch_and_store_intraday,
                    is_in_trading_window,
                )

                if not is_in_trading_window():
                    logger.debug(
                        "Job [intraday_fetch] 跳过 — 当前不在交易窗口"
                    )
                    return
                with SessionLocal() as session:
                    stats = fetch_and_store_intraday(session)
                logger.info("Job [intraday_fetch] 完成: %s", stats)
            except Exception as e:
                logger.error(
                    "Job intraday_fetch 顶级异常吞掉: %s: %s",
                    type(e).__name__, e,
                )

        return _run

    def _make_job_callable(self, config: dict) -> Callable[[], None]:
        """生成 cron 调用的闭包(捕获 config)+ 顶级异常吞掉。"""
        def _run():
            try:
                self._run_push_job(
                    push_type=config["push_type"],
                    title_label=config["title_label"],
                    macro_context=config["macro_context"],
                )
            except Exception as e:
                logger.error(
                    "Job %s 顶级异常(已吞掉,scheduler 不崩): %s: %s",
                    config["job_id"], type(e).__name__, e,
                )

        return _run

    def _run_push_job(
        self,
        push_type: str,
        title_label: str,
        macro_context: str,
    ) -> None:
        """共用流程:信号 → AI(可选) → 推送 → 写 push_logs。
        每个 try-except 独立,某一步失败不会中断后续步骤。"""
        logger.info("Job [%s] 开始执行", push_type)

        # 收盘复盘 / 周报依赖 sector_flow_daily 的 EOD 语义。若 daily 数据
        # 过期,直接阻断推送,避免输出"今日/收盘"强结论。
        if push_type in _DAILY_FRESHNESS_GATED_PUSH_TYPES:
            stale_reason: str | None = None
            try:
                with SessionLocal() as session:
                    freshness = assess_daily_freshness(session)
                if not freshness["is_fresh"]:
                    stale_reason = freshness["reason"]
            except Exception as e:
                stale_reason = (
                    f"daily freshness check failed: {type(e).__name__}: {e}"
                )

            if stale_reason:
                title = f"📊 {title_label} · 数据过期"
                content = (
                    "### 数据过期\n\n"
                    f"{stale_reason}\n\n"
                    "本次未生成收盘/周报强结论。"
                )
                logger.warning(
                    "Job [%s] blocked by stale daily freshness: %s",
                    push_type, stale_reason,
                )
                try:
                    with SessionLocal() as session:
                        write_push_log(
                            session,
                            push_type=push_type,
                            title=title,
                            content=content,
                            success=False,
                            error=stale_reason,
                        )
                except Exception as e:
                    logger.error(
                        "Job [%s] stale push_log 写入失败: %s: %s",
                        push_type, type(e).__name__, e,
                    )
                return

        # 1. 信号 + 持仓
        signals: list = []
        holdings_by_sector: dict[str, list[tuple[str, str]]] = {}
        try:
            with SessionLocal() as session:
                engine = SignalEngine(session)
                signals = engine.generate_signals_for_holdings()
                engine.save_signals(signals)
                holdings_by_sector = build_holdings_by_sector(session)
            logger.info(
                "Job [%s] 信号 %d 条, 涉及 %d 板块",
                push_type, len(signals), len(holdings_by_sector),
            )
        except Exception as e:
            logger.error(
                "Job [%s] 信号生成失败,推空数据继续: %s: %s",
                push_type, type(e).__name__, e,
            )

        # 2. AI 分析(可选,失败 fallback)
        # Phase 3.9: 传 push_type,让 AIAnalyst 派发到对应模板
        ai_analysis = ""
        if settings.anthropic_api_key:
            try:
                analyst = AIAnalyst(api_key=settings.anthropic_api_key)
                ai_analysis = analyst.analyze_signals(
                    signals,
                    holdings_by_sector,
                    macro_context=macro_context,
                    push_type=push_type,
                )
                logger.info(
                    "Job [%s] AI 分析: %d 字符",
                    push_type, len(ai_analysis),
                )
            except Exception as e:
                logger.error(
                    "Job [%s] AI 分析失败,无 AI 段继续: %s",
                    push_type, e,
                )

        # 3. 渲染
        title, content = ServerChanNotifier.build_summary_markdown(
            signals,
            holdings_by_sector,
            ai_analysis=ai_analysis,
            title_label=title_label,
        )

        # 4. 推送
        ok = False
        err: str | None = None
        if not settings.server_chan_sckey:
            err = "SERVER_CHAN_SCKEY 未配置"
            logger.warning("Job [%s]: %s,跳过推送但仍写 push_log", push_type, err)
        else:
            try:
                notifier = ServerChanNotifier(settings.server_chan_sckey)
                ok = notifier.send(title, content)
                if not ok:
                    err = "notifier.send 返回 False(见上方日志)"
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                logger.error("Job [%s] 推送异常: %s", push_type, err)

        # 5. 写 push_logs
        try:
            with SessionLocal() as session:
                write_push_log(
                    session,
                    push_type=push_type,
                    title=title,
                    content=content,
                    success=ok,
                    error=err,
                )
        except Exception as e:
            logger.error(
                "Job [%s] push_log 写入失败: %s: %s",
                push_type, type(e).__name__, e,
            )

        logger.info("Job [%s] 完成,success=%s", push_type, ok)

    def start(self) -> None:
        self.scheduler.start()
        logger.info(
            "SignalScheduler started (timezone=%s, jobs=%d)",
            self.timezone, len(self.scheduler.get_jobs()),
        )

    def shutdown(self, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("SignalScheduler shutdown")
