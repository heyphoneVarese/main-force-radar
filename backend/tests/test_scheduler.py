"""SignalScheduler 测试 — cron 配置、注册、异常吞掉、生命周期。

不调真实 anthropic / ServerChan,全部 mock。
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.models.enums import PushType
from src.services.fetch_health import get_fetch_health
from src.services.scheduler import CN_TZ, JOBS_CONFIG, SignalScheduler

# ============================================================
# JOBS_CONFIG 静态约束(cron 时间 + push_type 一一对应)
# ============================================================


def test_jobs_config_has_5_push_jobs():
    assert len(JOBS_CONFIG) == 5


def test_jobs_config_covers_all_push_types():
    push_types = {c["push_type"] for c in JOBS_CONFIG}
    assert push_types == {
        PushType.MORNING.value,
        PushType.MIDDAY.value,
        PushType.EVENING.value,
        PushType.WEEKLY.value,
    }


@pytest.mark.parametrize(
    "job_id, hour, minute, day_of_week",
    [
        ("pre_market", 8, 30, "mon-fri"),
        ("midday", 12, 55, "mon-fri"),
        ("tail", 14, 30, "mon-fri"),
        ("close", 15, 30, "mon-fri"),
        ("weekly", 20, 0, "sun"),
    ],
)
def test_jobs_config_cron_times_match_spec(job_id, hour, minute, day_of_week):
    config = next(c for c in JOBS_CONFIG if c["job_id"] == job_id)
    assert config["cron"]["hour"] == hour
    assert config["cron"]["minute"] == minute
    assert config["cron"]["day_of_week"] == day_of_week


def test_jobs_config_every_job_has_required_fields():
    required = {"job_id", "push_type", "cron", "title_label", "macro_context"}
    for config in JOBS_CONFIG:
        assert required.issubset(config.keys())
        assert config["title_label"]
        assert config["macro_context"]


# ============================================================
# register_jobs() — 时区 + 5 个 push job + 幂等
# ============================================================


def test_register_jobs_registers_7_jobs():
    """5 个推送 job + 1 个 daily_fetch + 1 个 intraday_fetch = 7 个。"""
    s = SignalScheduler()
    s.register_jobs()
    assert len(s.scheduler.get_jobs()) == 7
    job_ids = {job.id for job in s.scheduler.get_jobs()}
    assert job_ids == {
        "pre_market", "midday", "tail", "close", "weekly",
        "daily_fetch", "intraday_fetch",
    }


def test_default_timezone_is_asia_shanghai():
    s = SignalScheduler()
    assert s.timezone == CN_TZ
    assert str(s.scheduler.timezone) == "Asia/Shanghai"


def test_all_triggers_use_asia_shanghai():
    s = SignalScheduler()
    s.register_jobs()
    for job in s.scheduler.get_jobs():
        assert str(job.trigger.timezone) == "Asia/Shanghai"


def test_register_jobs_after_start_is_idempotent():
    """scheduler 启动后再次 register_jobs 应去重(replace_existing 在 started 状态下生效)。
    注意:start() 之前重复调用会进 pending list,不去重 — 见 register_jobs docstring。
    """
    s = SignalScheduler()
    s.register_jobs()
    s.start()
    try:
        s.register_jobs()  # 这次走真去重
        assert len(s.scheduler.get_jobs()) == 7
    finally:
        s.shutdown()


def test_weekly_next_fire_is_sunday():
    """周报 job 的下次触发时刻应该落在周日 20:00。"""
    s = SignalScheduler()
    s.register_jobs()
    weekly_job = s.scheduler.get_job("weekly")
    # 用周一上午作为参考时刻
    monday = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_fire = weekly_job.trigger.get_next_fire_time(None, monday)
    assert next_fire is not None
    assert next_fire.weekday() == 6  # 6 = Sunday
    assert next_fire.hour == 20
    assert next_fire.minute == 0


def test_pre_market_next_fire_skips_weekend():
    """盘前 job(mon-fri)从周六开始算应该落在周一。"""
    s = SignalScheduler()
    s.register_jobs()
    job = s.scheduler.get_job("pre_market")
    saturday = datetime(2026, 5, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_fire = job.trigger.get_next_fire_time(None, saturday)
    assert next_fire.weekday() == 0  # Monday


# ============================================================
# _run_push_job:异常吞掉 + 推全链路 + 写 push_log
# ============================================================


def _patch_scheduler_settings(scheduler_module, *, anthropic_key="", sckey=""):
    """便捷:patch scheduler 模块里的 settings。"""
    return patch.object(
        scheduler_module.settings,
        "anthropic_api_key",
        anthropic_key,
    ), patch.object(
        scheduler_module.settings,
        "server_chan_sckey",
        sckey,
    )


def test_job_callable_swallows_top_level_exception():
    """_make_job_callable 包了顶层 try-except — 子调用抛错也不向上传播。"""
    s = SignalScheduler()
    with patch.object(s, "_run_push_job", side_effect=ValueError("boom")):
        callable_ = s._make_job_callable(JOBS_CONFIG[0])
        # 不应抛任何异常
        callable_()


def _patch_chain(*, anthropic_key: str = "", sckey: str = "test_sckey",
                  send_ok: bool = True, ai_side_effect=None,
                  signal_side_effect=None, signals_return=None):
    """便捷:返回多 patch 上下文的 list,在 with 里 ExitStack 组合。
    只 patch `.send()` 让真实 build_summary_markdown 跑起来,验证渲染不挂。"""
    pass  # 占位 — 直接在测试里写 patch 链,简单清楚


def test_run_push_job_writes_push_log_on_success():
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True), \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.server_chan_sckey = "test_sckey"
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []

        s._run_push_job("morning", "盘前简报", "test macro")

    assert mock_write_log.called
    kw = mock_write_log.call_args.kwargs
    assert kw["push_type"] == "morning"
    assert kw["success"] is True
    assert kw["error"] is None
    # 标题应该带 title_label
    assert "盘前简报" in kw["title"]


def test_run_push_job_writes_push_log_on_send_failure():
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.scheduler.assess_daily_freshness",
               return_value={"is_fresh": True, "reason": "fresh"}), \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=False), \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.server_chan_sckey = "test_sckey"
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []

        s._run_push_job("evening", "收盘复盘", "test")

    kw = mock_write_log.call_args.kwargs
    assert kw["success"] is False
    assert kw["error"] is not None


def test_run_push_job_blocks_close_when_daily_stale():
    s = SignalScheduler()
    stale = {
        "is_fresh": False,
        "reason": "今日 2026-06-03 已过 15:30,但 daily 最新是 2026-06-02",
    }
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector") as mock_hbs, \
         patch("src.services.scheduler.assess_daily_freshness", return_value=stale), \
         patch("src.services.notifier.ServerChanNotifier.send") as mock_send, \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.server_chan_sckey = "test_sckey"

        s._run_push_job("evening", "收盘复盘", "test")

    assert not mock_engine_cls.called
    assert not mock_hbs.called
    assert not mock_send.called
    assert mock_write_log.called
    kw = mock_write_log.call_args.kwargs
    assert kw["push_type"] == "evening"
    assert kw["success"] is False
    assert "daily 最新" in kw["error"]
    assert "本次未生成收盘/周报强结论" in kw["content"]


def test_run_push_job_continues_when_signal_engine_fails():
    """信号生成失败,job 不应中断,继续推空内容并写 push_log。"""
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True), \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.server_chan_sckey = "test_sckey"
        mock_engine_cls.return_value.generate_signals_for_holdings.side_effect = (
            RuntimeError("DB down")
        )

        # 不应抛
        s._run_push_job("morning", "盘前简报", "test")

    assert mock_write_log.called  # 仍写了 push_log


def test_run_push_job_skips_send_when_no_sckey():
    """SCKEY 未配置:跳过 send,但仍写 push_log(标记 failed)。"""
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True) as mock_send, \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        mock_settings.server_chan_sckey = ""  # 没配
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []

        s._run_push_job("morning", "盘前简报", "test")

    # send 不应被调用
    assert not mock_send.called
    # push_log 仍写,标失败
    assert mock_write_log.called
    assert mock_write_log.call_args.kwargs["success"] is False
    assert "未配置" in mock_write_log.call_args.kwargs["error"]


def test_run_push_job_continues_when_ai_fails():
    """AI 失败不影响推送(向后兼容 Phase 3.8 数据-only 模式)。"""
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.scheduler.AIAnalyst") as mock_ai_cls, \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True) as mock_send, \
         patch("src.services.scheduler.write_push_log") as mock_write_log, \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-test"
        mock_settings.server_chan_sckey = "test"
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []
        mock_ai_cls.return_value.analyze_signals.side_effect = Exception("api down")

        s._run_push_job("morning", "盘前简报", "test")

    # 推送仍发出
    assert mock_send.called
    # push_log success=True(推送本身成功,AI 失败只是没 AI 段)
    assert mock_write_log.call_args.kwargs["success"] is True


def test_run_push_job_passes_push_type_to_ai_analyst():
    """Phase 3.9: scheduler 必须把 push_type 传给 AIAnalyst,
    让对应的 prompts 模块被派发(盘前/盘中/收盘/周报 各有自己的 system prompt)。"""
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.scheduler.AIAnalyst") as mock_ai_cls, \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True), \
         patch("src.services.scheduler.write_push_log"), \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-test"
        mock_settings.server_chan_sckey = "test"
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []
        mock_ai_cls.return_value.analyze_signals.return_value = ""

        s._run_push_job("morning", "盘前简报", "macro for morning")

    kwargs = mock_ai_cls.return_value.analyze_signals.call_args.kwargs
    assert kwargs["push_type"] == "morning"
    assert kwargs["macro_context"] == "macro for morning"


def test_run_push_job_skips_ai_when_no_api_key():
    s = SignalScheduler()
    with patch("src.services.scheduler.SignalEngine") as mock_engine_cls, \
         patch("src.services.scheduler.build_holdings_by_sector", return_value={}), \
         patch("src.services.scheduler.AIAnalyst") as mock_ai_cls, \
         patch("src.services.notifier.ServerChanNotifier.send", return_value=True), \
         patch("src.services.scheduler.write_push_log"), \
         patch("src.services.scheduler.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""  # 空
        mock_settings.server_chan_sckey = "test"
        mock_engine_cls.return_value.generate_signals_for_holdings.return_value = []

        s._run_push_job("morning", "盘前简报", "test")

    # AIAnalyst 类根本没被实例化
    assert not mock_ai_cls.called


# ============================================================
# 生命周期 start / shutdown
# ============================================================


def test_start_then_shutdown():
    s = SignalScheduler()
    s.register_jobs()
    s.start()
    try:
        assert s.scheduler.running
    finally:
        s.shutdown()
    assert not s.scheduler.running


def test_shutdown_when_not_started_is_noop():
    s = SignalScheduler()
    s.shutdown()  # 不应抛


# ============================================================
# daily_fetch job
# ============================================================


def test_daily_fetch_job_registered():
    s = SignalScheduler()
    s.register_jobs()
    job = s.scheduler.get_job("daily_fetch")
    assert job is not None
    assert job.name == "每日数据采集"


def test_daily_fetch_cron_is_15_20_mon_fri():
    """15:20 mon-fri,排在 close 推送 15:30 之前 10 分钟。"""
    s = SignalScheduler()
    s.register_jobs()
    job = s.scheduler.get_job("daily_fetch")
    monday = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_fire = job.trigger.get_next_fire_time(None, monday)
    assert next_fire is not None
    assert next_fire.hour == 15
    assert next_fire.minute == 20
    assert next_fire.weekday() in {0, 1, 2, 3, 4}  # mon-fri


def test_daily_fetch_skips_weekend():
    s = SignalScheduler()
    s.register_jobs()
    job = s.scheduler.get_job("daily_fetch")
    saturday = datetime(2026, 5, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_fire = job.trigger.get_next_fire_time(None, saturday)
    assert next_fire.weekday() == 0  # Monday


def test_daily_fetch_uses_asia_shanghai():
    s = SignalScheduler()
    s.register_jobs()
    job = s.scheduler.get_job("daily_fetch")
    assert str(job.trigger.timezone) == "Asia/Shanghai"


def test_run_fetch_job_calls_fetch_and_store_today():
    """_run_fetch_job 应该 call fetch_and_store_today 服务函数。"""
    s = SignalScheduler()
    with patch("src.services.scheduler.fetch_and_store_today") as mock_fetch:
        mock_fetch.return_value = {
            "sectors_fetched": 80, "sectors_inserted": 80,
            "indices_fetched": 4, "indices_inserted": 4, "errors": [],
        }
        s._run_fetch_job()
    assert mock_fetch.called
    health = get_fetch_health()
    assert health["status"] == "ok"
    assert health["ok"] is True
    assert health["stats"]["sectors_inserted"] == 80


def test_run_fetch_job_records_partial_failure_health():
    s = SignalScheduler()
    with patch("src.services.scheduler.fetch_and_store_today") as mock_fetch:
        mock_fetch.return_value = {
            "sectors_fetched": 0,
            "sectors_inserted": 0,
            "indices_fetched": 4,
            "indices_inserted": 4,
            "errors": ["sector_flow_industry: returned 0 rows"],
        }
        s._run_fetch_job()
    health = get_fetch_health()
    assert health["status"] == "partial_failure"
    assert health["ok"] is False
    assert health["errors"]


def test_run_fetch_job_swallows_exception():
    """采集失败不应让 scheduler 崩 — 跟 push job 同样契约。"""
    s = SignalScheduler()
    with patch(
        "src.services.scheduler.fetch_and_store_today",
        side_effect=RuntimeError("akshare 挂了"),
    ):
        # 直接调内层不应抛(内层吞)
        s._run_fetch_job()
    health = get_fetch_health()
    assert health["status"] == "failed"
    assert health["ok"] is False
    assert "RuntimeError" in health["errors"][0]


def test_make_fetch_callable_swallows_top_level_exception():
    """顶层 callable 兜底:即便 _run_fetch_job 抛(理论上不会)也吞掉。"""
    s = SignalScheduler()
    with patch.object(s, "_run_fetch_job", side_effect=ValueError("boom")):
        callable_ = s._make_fetch_callable()
        callable_()  # 不应抛
