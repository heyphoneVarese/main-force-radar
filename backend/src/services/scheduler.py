"""APScheduler 定时任务 — Phase 3.11

4 个 cron 任务(全部 Asia/Shanghai 时区):
  - 12:55 CN  mon-fri  盘前简报(下午开盘前)
  - 14:30 CN  mon-fri  盘中观察(尾盘前 30 分钟)
  - 15:30 CN  mon-fri  收盘复盘(当日资金流向已定)
  - 16:00 CN  fri      周报(总结本周主线)

每个 job 流程:
  1. SignalEngine.generate_signals_for_holdings()
  2. build_holdings_by_sector
  3. AIAnalyst.analyze_signals(失败 fallback "")
  4. ServerChanNotifier.send(title, content)
  5. push_logs 写一行(成功/失败都写)
  6. 任何一步异常都 try/except 吞掉,不能让 scheduler 崩

R6 不过度设计:不上 Celery/Redis 任务队列。APScheduler 单机 +
BackgroundScheduler 够用,符合"个人自用工具"定位。

Server酱 免费版日限 5 条:工作日 3 + 周报 1 = 4 ≤ 5 ✅
"""

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.db import SessionLocal
from src.models.enums import PushType
from src.services.ai_analyst import AIAnalyst
from src.services.holdings_summary import build_holdings_by_sector
from src.services.notifier import ServerChanNotifier
from src.services.push_log import write_push_log
from src.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)

CN_TZ = "Asia/Shanghai"


# 4 个 cron job 配置
JOBS_CONFIG: list[dict] = [
    {
        "job_id": "pre_market",
        "push_type": PushType.MORNING.value,
        "cron": {"hour": 12, "minute": 55, "day_of_week": "mon-fri"},
        "title_label": "盘前简报",
        "macro_context": "盘前简报 — 下午开盘前的主力资金动向,关注开盘方向",
    },
    {
        "job_id": "intraday",
        "push_type": PushType.MIDDAY.value,
        "cron": {"hour": 14, "minute": 30, "day_of_week": "mon-fri"},
        "title_label": "盘中观察",
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
        "cron": {"hour": 16, "minute": 0, "day_of_week": "fri"},
        "title_label": "周报",
        "macro_context": "周报 — 总结本周主线 / 退潮主线,判断下周延续概率",
    },
]


class SignalScheduler:
    def __init__(self, timezone: str = CN_TZ):
        self.timezone = timezone
        self.scheduler: BackgroundScheduler = BackgroundScheduler(timezone=timezone)

    def register_jobs(self) -> None:
        """把 4 个 job 注册到内部 scheduler。

        ⚠️ 注意:scheduler 未启动时,APScheduler 的 add_job 会把任务放进
        pending list 而非按 ID 索引,此时 replace_existing=True 不会去重。
        生产里 lifespan 只 call 一次,不会撞到这个 quirk;但**别在 start()
        之前重复调用本方法**。
        """
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
        ai_analysis = ""
        if settings.anthropic_api_key:
            try:
                analyst = AIAnalyst(api_key=settings.anthropic_api_key)
                ai_analysis = analyst.analyze_signals(
                    signals, holdings_by_sector, macro_context=macro_context
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
