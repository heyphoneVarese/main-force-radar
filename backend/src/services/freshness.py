"""数据新鲜度评估(P0 fix)。

背景:scheduler 正常、DB 表正常、intraday 有 14:30 snapshot,但 Dashboard
等内容仍像旧数据 — 因为 daily_fetch 静默失败(inserted=0)、intraday
fetch 也可能在接口失败时不写新行,所有端点继续读 MAX(snapshot_time /
trade_date) → 旧数据被当作新数据展示。

本模块提供两个评估函数:
- assess_intraday_freshness(session)
- assess_daily_freshness(session)

两者都返回:
    {
      "is_fresh": bool,
      "source": str,                  # "intraday" | "daily"
      "latest_time": datetime | None, # date 会转 datetime midnight
      "age_minutes": int | None,      # 仅 intraday 有意义
      "reason": str,                  # 人类可读
    }

判定规则(intraday):
  · DB 为空                          → stale, reason="intraday 表为空"
  · 在交易时间窗口内
      · latest 不是今日              → stale, "盘中但 snapshot 不是今日"
      · age > 15 分钟                → stale, "盘中但已 N 分钟未更新"
      · 其它                         → fresh
  · 非交易时间窗口
      · latest 是今日                → fresh, "非交易时间,今日已有快照"
      · latest 在 4 个日历日内       → fresh(覆盖周末/节假日)
      · 其它                         → stale

判定规则(daily):
  · DB 为空                          → stale
  · 工作日 15:20 后 + latest != 今日 → stale("收盘后但 daily_fetch 失败")
  · 距今 > 4 日历日                   → stale("最新 trade_date 距今 N 天")
  · 其它                             → fresh

R3 红线:freshness 只是事实标记;不预测、不评分、不影响业务输出。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import IntradaySectorFlow, MarketIndexDaily, SectorFlowDaily
from src.services.intraday_fetcher import is_in_trading_window
from src.utils.date_helper import cn_now

# 在交易时间内,最新 snapshot 距 now 的最大可接受分钟数。
# cron 是 */10,加 2-3 分钟处理/网络余量;15 分钟内算正常。
_INTRADAY_MAX_AGE_IN_WINDOW_MIN = 15

# daily 容忍的最大日历日数(覆盖周末 + 1 日缓冲)。
_DAILY_MAX_AGE_DAYS = 4

# daily_fetch 的 cron 时间:15:20。15:30 后视为"今日数据应该已就位"。
_DAILY_EXPECTED_HOUR = 15
_DAILY_EXPECTED_MINUTE = 30


def _to_dt(d: date | None) -> datetime | None:
    """date → datetime midnight;datetime 原样;None 透传。"""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    return datetime.combine(d, datetime.min.time())


def _source_type(source: str, is_fresh: bool) -> str:
    if not is_fresh:
        return "stale"
    if source == "intraday":
        return "intraday"
    if source in {"daily", "market"}:
        return "daily_close"
    if source == "cached":
        return "cached"
    return source


def _with_time_meta(
    payload: dict[str, Any],
    *,
    source: str,
    data_dt: datetime | None,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    data_date = data_dt.date() if data_dt is not None else None
    data_time = data_dt.strftime("%H:%M") if source == "intraday" and data_dt is not None else None
    payload["data_date"] = data_date
    payload["data_time"] = data_time
    payload["source_type"] = _source_type(source, bool(payload["is_fresh"]))
    payload["updated_at"] = updated_at or data_dt
    return payload


def assess_intraday_freshness(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """评估 intraday_sector_flow 新鲜度。"""
    now = now or cn_now()
    latest: datetime | None = session.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )
    if latest is None:
        return _with_time_meta({
            "source": "intraday",
            "is_fresh": False,
            "latest_time": None,
            "age_minutes": None,
            "reason": "intraday_sector_flow 表为空(intraday_fetch 从未成功)",
        }, source="intraday", data_dt=None)

    updated_at = session.scalar(
        select(func.max(IntradaySectorFlow.created_at)).where(
            IntradaySectorFlow.snapshot_time == latest
        )
    )

    age_seconds = (now - latest).total_seconds()
    age_min = int(age_seconds // 60)
    # in_window 在原始函数里只看 time(不查 weekday;cron 自己拦周末),
    # 但 freshness 评估必须考虑周末/工作日:周六 11:00 即使时间窗匹配,
    # 也不该期待新 snapshot。
    today = now.date()
    in_window = is_in_trading_window(now) and today.weekday() < 5

    if in_window:
        if latest.date() != today:
            return _with_time_meta({
                "source": "intraday",
                "is_fresh": False,
                "latest_time": latest,
                "age_minutes": age_min,
                "reason": (
                    f"当前在交易时间窗口,但最新 snapshot 是 {latest.date()},"
                    f"不是今日 {today} — 盘中采集失败"
                ),
            }, source="intraday", data_dt=latest, updated_at=updated_at)
        if age_min > _INTRADAY_MAX_AGE_IN_WINDOW_MIN:
            return _with_time_meta({
                "source": "intraday",
                "is_fresh": False,
                "latest_time": latest,
                "age_minutes": age_min,
                "reason": (
                    f"当前在交易时间窗口,但最新 snapshot 已 {age_min} 分钟"
                    f"未更新(期望 ≤ {_INTRADAY_MAX_AGE_IN_WINDOW_MIN} 分钟)"
                ),
            }, source="intraday", data_dt=latest, updated_at=updated_at)
        return _with_time_meta({
            "source": "intraday",
            "is_fresh": True,
            "latest_time": latest,
            "age_minutes": age_min,
            "reason": f"盘中 snapshot 新鲜({age_min} 分钟前)",
        }, source="intraday", data_dt=latest, updated_at=updated_at)

    # 非交易时间窗口
    if latest.date() == today:
        return _with_time_meta({
            "source": "intraday",
            "is_fresh": True,
            "latest_time": latest,
            "age_minutes": age_min,
            "reason": "非交易时间,最新 snapshot 是今日",
        }, source="intraday", data_dt=latest, updated_at=updated_at)
    gap_days = (today - latest.date()).days
    if gap_days <= _DAILY_MAX_AGE_DAYS:
        return _with_time_meta({
            "source": "intraday",
            "is_fresh": True,
            "latest_time": latest,
            "age_minutes": age_min,
            "reason": (
                f"非交易日,最新 snapshot 来自 {latest.date()}"
                f"(距今 {gap_days} 日)"
            ),
        }, source="intraday", data_dt=latest, updated_at=updated_at)
    return _with_time_meta({
        "source": "intraday",
        "is_fresh": False,
        "latest_time": latest,
        "age_minutes": age_min,
        "reason": (
            f"最新 snapshot {latest.date()} 距今 {gap_days} 天,"
            "数据可能过期"
        ),
    }, source="intraday", data_dt=latest, updated_at=updated_at)


def assess_daily_freshness(
    session: Session,
    *,
    now: datetime | None = None,
    model: Any = SectorFlowDaily,
    label: str = "daily",
) -> dict[str, Any]:
    """评估 sector_flow_daily(或同结构表)新鲜度。

    model: 默认 SectorFlowDaily;可传 MarketIndexDaily 复用同一套判定。
    label: 出参 source 字段值。
    """
    now = now or cn_now()
    today = now.date()
    latest: date | None = session.scalar(
        select(model.trade_date)
        .order_by(model.trade_date.desc())
        .limit(1)
    )
    if latest is None:
        return _with_time_meta({
            "source": label,
            "is_fresh": False,
            "latest_time": None,
            "age_minutes": None,
            "reason": f"{label} 表为空(daily_fetch 从未成功)",
        }, source=label, data_dt=None)

    latest_dt = _to_dt(latest)
    updated_at = session.scalar(
        select(func.max(model.created_at)).where(model.trade_date == latest)
    )

    age_days = (today - latest).days
    # 今日是工作日 + 已过 daily_fetch cron 时间(15:20 → 取 15:30 + 容差)
    today_is_weekday = today.weekday() < 5
    past_close = (now.hour, now.minute) >= (
        _DAILY_EXPECTED_HOUR, _DAILY_EXPECTED_MINUTE
    )

    if today_is_weekday and past_close and latest != today:
        return _with_time_meta({
            "source": label,
            "is_fresh": False,
            "latest_time": latest_dt,
            "age_minutes": None,
            "reason": (
                f"今日 {today} 已过 {_DAILY_EXPECTED_HOUR:02d}:"
                f"{_DAILY_EXPECTED_MINUTE:02d},但 {label} 最新是 "
                f"{latest} — daily_fetch 可能失败"
            ),
        }, source=label, data_dt=latest_dt, updated_at=updated_at)
    if age_days > _DAILY_MAX_AGE_DAYS:
        return _with_time_meta({
            "source": label,
            "is_fresh": False,
            "latest_time": latest_dt,
            "age_minutes": None,
            "reason": (
                f"最新 trade_date {latest} 距今 {age_days} 天 — "
                "数据可能过期"
            ),
        }, source=label, data_dt=latest_dt, updated_at=updated_at)
    return _with_time_meta({
        "source": label,
        "is_fresh": True,
        "latest_time": latest_dt,
        "age_minutes": None,
        "reason": f"最新 trade_date {latest},距今 {age_days} 天",
    }, source=label, data_dt=latest_dt, updated_at=updated_at)


def assess_market_freshness(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """便利封装:评估 market_index_daily。"""
    return assess_daily_freshness(
        session, now=now, model=MarketIndexDaily, label="market"
    )
