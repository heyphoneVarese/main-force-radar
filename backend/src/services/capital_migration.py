"""资金迁移雷达 V1 — 基于 sector_flow_daily 的 20 日历史事实。

R3 红线:
- 只描述最近 N 个实际交易日的资金状态变化,不预测、不建议
- 不表达"资金从 A 流向 B"的因果路径
- 不读 intraday,不写数据库
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, SectorFlowDaily
from src.services.sector_mapping import (
    FundSectorMapping,
    mapping_status_for_fund,
    resolve_fund_sector_mappings,
)

MigrationStatus = Literal[
    "inflowing",
    "outflowing",
    "weak_to_strong",
    "strong_to_weak",
    "strengthening",
    "weakening",
    "mixed",
    "insufficient_data",
]


@dataclass(frozen=True)
class _SectorMetric:
    sector_code: str
    sector_name: str
    sector_type: str
    sample_days: int
    is_partial_window: bool
    first_half_sum: int
    second_half_sum: int
    delta: int
    first_half_inflow_days: int
    second_half_inflow_days: int
    first_half_outflow_days: int
    second_half_outflow_days: int
    inflow_days_20: int
    outflow_days_20: int
    latest_main_inflow: int
    latest_trade_date_rank: int | None


def _load_recent_context(
    session: Session,
    *,
    window: int,
    sector_type: str,
) -> dict[str, Any] | None:
    latest_date = session.scalar(
        select(SectorFlowDaily.trade_date)
        .order_by(SectorFlowDaily.trade_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return None

    all_dates = list(
        session.scalars(
            select(SectorFlowDaily.trade_date)
            .distinct()
            .order_by(SectorFlowDaily.trade_date.desc())
            .limit(window)
        )
    )
    if not all_dates:
        return None

    stmt = select(SectorFlowDaily).where(SectorFlowDaily.trade_date.in_(all_dates))
    if sector_type != "all":
        stmt = stmt.where(SectorFlowDaily.sector_type == sector_type)
    else:
        stmt = stmt.where(SectorFlowDaily.sector_type.in_(("industry", "concept")))
    rows = list(session.scalars(stmt))

    by_code: dict[str, dict[Any, SectorFlowDaily]] = {}
    for row in rows:
        by_code.setdefault(row.sector_code, {})[row.trade_date] = row

    latest_rows = [r for r in rows if r.trade_date == latest_date]
    if sector_type != "all":
        latest_rows = [r for r in latest_rows if r.sector_type == sector_type]
    latest_rows.sort(key=lambda r: -r.main_inflow_wan_x10000)
    latest_rank = {r.sector_code: i + 1 for i, r in enumerate(latest_rows)}

    return {
        "latest_date": latest_date,
        "dates_desc": all_dates,
        "dates_asc": list(reversed(all_dates)),
        "by_code": by_code,
        "latest_rank": latest_rank,
    }


def _metric_for_history(
    *,
    dates_asc: list,
    history: dict[Any, SectorFlowDaily],
    window: int,
    latest_rank: int | None,
) -> _SectorMetric | None:
    values: list[tuple[Any, SectorFlowDaily]] = [
        (d, history[d]) for d in dates_asc if d in history
    ]
    if not values:
        return None

    sample_days = len(values)
    split = sample_days // 2
    if split == 0:
        first = []
        second = [r for _, r in values]
    else:
        first = [r for _, r in values[:split]]
        second = [r for _, r in values[split:]]
    latest = values[-1][1]

    first_sum = sum(r.main_inflow_wan_x10000 for r in first)
    second_sum = sum(r.main_inflow_wan_x10000 for r in second)
    all_rows = [r for _, r in values]

    return _SectorMetric(
        sector_code=latest.sector_code,
        sector_name=latest.sector_name,
        sector_type=latest.sector_type,
        sample_days=sample_days,
        is_partial_window=sample_days < window,
        first_half_sum=first_sum,
        second_half_sum=second_sum,
        delta=second_sum - first_sum,
        first_half_inflow_days=sum(1 for r in first if r.main_inflow_wan_x10000 > 0),
        second_half_inflow_days=sum(1 for r in second if r.main_inflow_wan_x10000 > 0),
        first_half_outflow_days=sum(1 for r in first if r.main_inflow_wan_x10000 < 0),
        second_half_outflow_days=sum(1 for r in second if r.main_inflow_wan_x10000 < 0),
        inflow_days_20=sum(1 for r in all_rows if r.main_inflow_wan_x10000 > 0),
        outflow_days_20=sum(1 for r in all_rows if r.main_inflow_wan_x10000 < 0),
        latest_main_inflow=latest.main_inflow_wan_x10000,
        latest_trade_date_rank=latest_rank,
    )


def _build_metrics(
    ctx: dict[str, Any],
    *,
    window: int,
) -> dict[str, _SectorMetric]:
    metrics: dict[str, _SectorMetric] = {}
    for code, history in ctx["by_code"].items():
        metric = _metric_for_history(
            dates_asc=ctx["dates_asc"],
            history=history,
            window=window,
            latest_rank=ctx["latest_rank"].get(code),
        )
        if metric is not None:
            metrics[code] = metric
    return metrics


def _item(metric: _SectorMetric, status: MigrationStatus) -> dict[str, Any]:
    return {
        "sector_code": metric.sector_code,
        "sector_name": metric.sector_name,
        "sector_type": metric.sector_type,
        "migration_status": status,
        "sample_days": metric.sample_days,
        "is_partial_window": metric.is_partial_window,
        "first_half_sum_wan_x10000": metric.first_half_sum,
        "second_half_sum_wan_x10000": metric.second_half_sum,
        "delta_wan_x10000": metric.delta,
        "first_half_inflow_days": metric.first_half_inflow_days,
        "second_half_inflow_days": metric.second_half_inflow_days,
        "first_half_outflow_days": metric.first_half_outflow_days,
        "second_half_outflow_days": metric.second_half_outflow_days,
        "inflow_days_20": metric.inflow_days_20,
        "outflow_days_20": metric.outflow_days_20,
        "latest_main_inflow_wan_x10000": metric.latest_main_inflow,
        "latest_trade_date_rank": metric.latest_trade_date_rank,
    }


def _min_days_for_half(sample_days: int) -> int:
    """V1 门槛:半窗口内多数交易日同向。20 日=6 天;不足窗口按比例降级。"""
    half = max(1, sample_days - sample_days // 2)
    return max(1, half // 2 + 1)


def build_capital_migration(
    session: Session,
    *,
    window: int = 20,
    sector_type: str = "industry",
    n: int = 10,
) -> dict[str, Any]:
    """全市场资金状态变化。

    分类基于最近 window 个实际交易日,按时间正序切成前半段 / 后半段。
    """
    ctx = _load_recent_context(session, window=window, sector_type=sector_type)
    if ctx is None:
        return {
            "trade_date": None,
            "sector_type": sector_type,
            "window": window,
            "sample_days": 0,
            "is_partial_window": False,
            "inflowing": [],
            "outflowing": [],
            "weak_to_strong": [],
            "strong_to_weak": [],
        }

    metrics = _build_metrics(ctx, window=window)

    inflowing: list[dict[str, Any]] = []
    outflowing: list[dict[str, Any]] = []
    weak_to_strong: list[dict[str, Any]] = []
    strong_to_weak: list[dict[str, Any]] = []

    for metric in metrics.values():
        min_days = _min_days_for_half(metric.sample_days)
        if metric.second_half_sum > 0 and metric.second_half_inflow_days >= min_days:
            inflowing.append(_item(metric, "inflowing"))
        if metric.second_half_sum < 0 and metric.second_half_outflow_days >= min_days:
            outflowing.append(_item(metric, "outflowing"))
        if metric.first_half_sum <= 0 and metric.second_half_sum > 0 and metric.delta > 0:
            weak_to_strong.append(_item(metric, "weak_to_strong"))
        if metric.first_half_sum > 0 and metric.second_half_sum <= 0 and metric.delta < 0:
            strong_to_weak.append(_item(metric, "strong_to_weak"))

    inflowing.sort(key=lambda it: (-it["second_half_sum_wan_x10000"], it["sector_code"]))
    outflowing.sort(key=lambda it: (it["second_half_sum_wan_x10000"], it["sector_code"]))
    weak_to_strong.sort(key=lambda it: (-it["delta_wan_x10000"], it["sector_code"]))
    strong_to_weak.sort(key=lambda it: (it["delta_wan_x10000"], it["sector_code"]))

    return {
        "trade_date": ctx["latest_date"],
        "sector_type": sector_type,
        "window": window,
        "sample_days": len(ctx["dates_desc"]),
        "is_partial_window": len(ctx["dates_desc"]) < window,
        "inflowing": inflowing[:n],
        "outflowing": outflowing[:n],
        "weak_to_strong": weak_to_strong[:n],
        "strong_to_weak": strong_to_weak[:n],
    }


def _holding_status(metric: _SectorMetric | None) -> MigrationStatus:
    if metric is None or metric.sample_days < 2:
        return "insufficient_data"
    if metric.first_half_sum <= 0 and metric.second_half_sum > 0 and metric.delta > 0:
        return "strengthening"
    if metric.first_half_sum > 0 and metric.second_half_sum <= 0 and metric.delta < 0:
        return "weakening"
    if metric.second_half_sum > 0:
        return "inflowing"
    if metric.second_half_sum < 0:
        return "outflowing"
    return "mixed"


def _empty_holding_item(
    *,
    holding: Holding,
    fund: Fund | None,
    mapping_status: str,
    mapping: FundSectorMapping | None,
) -> dict[str, Any]:
    return {
        "fund_code": holding.fund_code,
        "fund_name": fund.fund_name if fund else holding.fund_code,
        "related_sectors": list(fund.related_sectors or []) if fund else [],
        "sector_code": mapping.sector_code if mapping else None,
        "sector_name": mapping.sector_name if mapping else None,
        "mapped_sector": mapping.label if mapping else None,
        "mapping_status": mapping_status,
        "mapping_confidence": mapping.confidence if mapping else None,
        "mapping_source": mapping.source if mapping else None,
        "migration_status": "insufficient_data",
        "sample_days": 0,
        "is_partial_window": True,
        "first_half_sum_wan_x10000": None,
        "second_half_sum_wan_x10000": None,
        "delta_wan_x10000": None,
        "inflow_days_20": None,
        "outflow_days_20": None,
    }


def build_holdings_capital_migration(
    session: Session,
    *,
    window: int = 20,
) -> dict[str, Any]:
    """我的持仓对应主线的资金状态变化。

    只允许 resolve_fund_sector_mappings 返回的 eligible_for_sorting 映射参与
    事实判断;低置信 / 未映射 / 不适用只展示状态。
    """
    ctx = _load_recent_context(session, window=window, sector_type="all")
    metrics = _build_metrics(ctx, window=window) if ctx is not None else {}

    holdings = list(session.scalars(select(Holding).order_by(Holding.fund_code)))
    items: list[dict[str, Any]] = []

    for holding in holdings:
        fund = session.get(Fund, holding.fund_code)
        mappings = resolve_fund_sector_mappings(session, holding.fund_code)
        fund_status = mapping_status_for_fund(mappings)

        candidates: list[tuple[FundSectorMapping, _SectorMetric]] = []
        for mapping in mappings:
            if not mapping.eligible_for_sorting or mapping.sector_code is None:
                continue
            metric = metrics.get(mapping.sector_code)
            if metric is not None:
                candidates.append((mapping, metric))

        if not candidates:
            display_mapping = next((m for m in mappings if m.status == fund_status), None)
            items.append(_empty_holding_item(
                holding=holding,
                fund=fund,
                mapping_status=fund_status,
                mapping=display_mapping,
            ))
            continue

        # V1 不做复杂一对多权重;多 verified 时选择资金状态变化幅度最大的一条主线展示。
        candidates.sort(key=lambda pair: (-abs(pair[1].delta), pair[0].sector_code or ""))
        mapping, metric = candidates[0]
        items.append({
            "fund_code": holding.fund_code,
            "fund_name": fund.fund_name if fund else holding.fund_code,
            "related_sectors": list(fund.related_sectors or []) if fund else [],
            "sector_code": metric.sector_code,
            "sector_name": metric.sector_name,
            "mapped_sector": mapping.label,
            "mapping_status": mapping.status,
            "mapping_confidence": mapping.confidence,
            "mapping_source": mapping.source,
            "migration_status": _holding_status(metric),
            "sample_days": metric.sample_days,
            "is_partial_window": metric.is_partial_window,
            "first_half_sum_wan_x10000": metric.first_half_sum,
            "second_half_sum_wan_x10000": metric.second_half_sum,
            "delta_wan_x10000": metric.delta,
            "inflow_days_20": metric.inflow_days_20,
            "outflow_days_20": metric.outflow_days_20,
        })

    return {
        "trade_date": ctx["latest_date"] if ctx is not None else None,
        "window": window,
        "sample_days": len(ctx["dates_desc"]) if ctx is not None else 0,
        "is_partial_window": len(ctx["dates_desc"]) < window if ctx is not None else False,
        "holdings": items,
    }
