"""SignalScheduler 测试 — cron 配置、注册、异常吞掉、生命周期。

不调真实 anthropic / ServerChan,全部 mock。
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.models.enums import PushType
from src.services.scheduler import CN_TZ, JOBS_CONFIG, SignalScheduler


# ============================================================
# JOBS_CONFIG 静态约束(cron 时间 + push_type 一一对应)
# ============================================================


def test_jobs_config_has_4_jobs():
    assert len(JOBS_CONFIG) == 4


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
        ("pre_market", 12, 55, "mon-fri"),
        ("intraday", 14, 30, "mon-fri"),
        ("close", 15, 30, "mon-fri"),
        ("weekly", 16, 0, "fri"),
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
# register_jobs() — 时区 + 4 个 job + 幂等
# ============================================================


def test_register_jobs_registers_4_jobs():
    s = SignalScheduler()
    s.register_jobs()
    assert len(s.scheduler.get_jobs()) == 4


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
        assert len(s.scheduler.get_jobs()) == 4
    finally:
        s.shutdown()


def test_weekly_next_fire_is_friday():
    """周报 job 的下次触发时刻应该落在周五。"""
    s = SignalScheduler()
    s.register_jobs()
    weekly_job = s.scheduler.get_job("weekly")
    # 用周一上午作为参考时刻
    monday = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    next_fire = weekly_job.trigger.get_next_fire_time(None, monday)
    assert next_fire is not None
    assert next_fire.weekday() == 4  # 4 = Friday
    assert next_fire.hour == 16
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
