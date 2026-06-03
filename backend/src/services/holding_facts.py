"""持仓-事实摘要(PR26)— 把"我的持仓分析"从情绪系统(bullish / bearish
/ warning / neutral)替换为纯事实系统。

R3 红线:
- **不出现** bullish / bearish / warning / neutral / 任何情绪词
- **不新增** score / health / rating(purity_score 是 PR17 已有的"主题
  贴合度",在 PR23 spec 的"保留" 列表里;不是情绪)
- 全部字段是客观计数 / 现值,不预测、不推荐

数据来源:
- holdings + funds.related_sectors → 找匹配的 sector_name
- sector_flow_daily(最新交易日)→ mapped_sector 信息 + 连续天数事实
  (复用 sector_persistence._load_context + _compute_facts)
- intraday_sector_flow(最新 snapshot industry,可选)→ 盘中实时

设计:
1. 对每个持仓:
   - 在 fund.related_sectors 各标签里找匹配的 sector(最新日 sector_flow_daily
     中存在的 sector_name 精确匹配)
   - 多个匹配 → 选 continuous_top20_days 最大的(再 tie-break 最新日 inflow)
   - 找不到 → 标记为"未映射"(mapped_sector=null)
2. 顶部 buckets 按 continuous_top20_days 分四档:
   ≥20天 / 5~19天 / <5天 / 未映射(=没有 mapped_sector)

排序:跟旧 dashboard_holdings 保持一致 — Holding.fund_code ASC。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, IntradaySectorFlow, SectorFlowDaily
from src.services.radar import _compute_purity_score
from src.services.sector_mapping import (
    FundSectorMapping,
    mapping_status_for_fund,
    resolve_fund_sector_mappings,
)
from src.services.sector_persistence import _compute_facts, _load_context


def _build_latest_sector_lookup(
    ctx: dict[str, Any] | None,
) -> tuple[dict[str, SectorFlowDaily], dict[str, int]]:
    """{sector_code: latest_row} + {sector_code: rank_within_own_sector_type}。

    多个 sector_type 同名时优先 industry。rank 按 (sector_type, latest_date)
    内 inflow DESC 计算 — 给 _compute_facts 用。
    """
    if ctx is None:
        return {}, {}
    latest_rows = [
        r for r in ctx["all_rows"] if r.trade_date == ctx["latest_date"]
    ]
    # 按 sector_type 分组排 rank,因为 _compute_facts 的 top20 是 sector_type 内的
    rank_by_code: dict[str, int] = {}
    by_type: dict[str, list[SectorFlowDaily]] = {}
    for r in latest_rows:
        by_type.setdefault(r.sector_type, []).append(r)
    for _, group in by_type.items():
        group.sort(key=lambda r: -r.main_inflow_wan_x10000)
        for i, r in enumerate(group, start=1):
            rank_by_code[r.sector_code] = i

    code_to_row = {r.sector_code: r for r in latest_rows}

    return code_to_row, rank_by_code


def _load_intraday_industry_by_name(
    session: Session,
) -> tuple[Any, dict[str, IntradaySectorFlow]]:
    """最新 snapshot industry 行,按 sector_code 索引。"""
    latest = session.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )
    if latest is None:
        return None, {}
    by_code: dict[str, IntradaySectorFlow] = {}
    for r in session.scalars(
        select(IntradaySectorFlow)
        .where(IntradaySectorFlow.snapshot_time == latest)
        .where(IntradaySectorFlow.sector_type == "industry")
    ):
        if r.sector_code and r.sector_code not in by_code:
            by_code[r.sector_code] = r
    return latest, by_code


def _empty_item(
    *,
    fund_code: str,
    fund_name: str,
    related: list[str],
    mapping_status: str,
    mapping: FundSectorMapping | None = None,
) -> dict[str, Any]:
    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "related_sectors": related,
        "mapped_sector": None,
        "sector_code": mapping.sector_code if mapping else None,
        "sector_name": mapping.sector_name if mapping else None,
        "mapping_status": mapping_status,
        "mapping_confidence": mapping.confidence if mapping else None,
        "mapping_source": mapping.source if mapping else None,
        "purity_score": None,
        "continuous_top20_days": None,
        "last_20_top20_days": None,
        "last_20_inflow_days": None,
        "latest_main_inflow_wan_x10000": None,
        "change_pct_x10000": None,
        "intraday_main_inflow_wan_x10000": None,
        "intraday_change_pct_x10000": None,
    }


def build_holding_facts(session: Session) -> dict[str, Any]:
    """持仓-事实摘要(service 出 dict,API 层算 Decimal)。

    Returns:
      {
        "trade_date": date | None,           # daily 最新交易日
        "snapshot_time": datetime | None,    # intraday 最新 snapshot;空 → null
        "buckets": {
          "persistence_ge_20": int,
          "persistence_5_to_19": int,
          "persistence_lt_5": int,           # 含 continuous_top20_days = 0
          "unmapped": int,                   # 找不到 mapped_sector
          "total": int,
        },
        "holdings": [
          {
            "fund_code": str,
            "fund_name": str,
            "related_sectors": list[str],
            # === mapped_sector 字段;未映射时全 None ===
            "mapped_sector": str | None,
            "sector_code": str | None,
            "sector_name": str | None,
            "purity_score": int | None,
            # === sector 事实(_compute_facts);未映射时全 None ===
            "continuous_top20_days": int | None,
            "last_20_top20_days": int | None,
            "last_20_inflow_days": int | None,
            # === 最新日 daily 数值 ===
            "latest_main_inflow_wan_x10000": int | None,
            "change_pct_x10000": int | None,
            # === intraday(可选) ===
            "intraday_main_inflow_wan_x10000": int | None,
            "intraday_change_pct_x10000": int | None,
          },
          ...
        ]
      }
    """
    holdings = list(
        session.scalars(select(Holding).order_by(Holding.fund_code))
    )
    if not holdings:
        return {
            "trade_date": None,
            "snapshot_time": None,
            "buckets": {
                "persistence_ge_20": 0,
                "persistence_5_to_19": 0,
                "persistence_lt_5": 0,
                "unmapped": 0,
                "total": 0,
            },
            "holdings": [],
        }

    ctx = _load_context(session)
    code_to_row, rank_by_code = _build_latest_sector_lookup(ctx)
    latest_snap, intraday_by_code = _load_intraday_industry_by_name(session)

    items: list[dict[str, Any]] = []
    for h in holdings:
        fund = session.get(Fund, h.fund_code)
        fund_name = (fund.fund_name if fund else None) or h.fund_code
        related = (
            list(fund.related_sectors)
            if fund and fund.related_sectors else []
        )

        mappings = resolve_fund_sector_mappings(session, h.fund_code)
        fund_mapping_status = mapping_status_for_fund(mappings)

        # 找匹配 sector:只允许高置信 verified mapping 进入事实计算。
        best: tuple[FundSectorMapping, SectorFlowDaily, dict[str, Any]] | None = None
        if ctx is not None:
            candidates: list[tuple[FundSectorMapping, SectorFlowDaily, dict[str, Any]]] = []
            seen_codes: set[str] = set()
            for mapping in mappings:
                if not mapping.eligible_for_sorting or mapping.sector_code is None:
                    continue
                daily_row = code_to_row.get(mapping.sector_code)
                if daily_row is None or daily_row.sector_code in seen_codes:
                    continue
                seen_codes.add(daily_row.sector_code)
                facts = _compute_facts(
                    ctx, daily_row, rank_by_code[daily_row.sector_code]
                )
                candidates.append((mapping, daily_row, facts))
            if candidates:
                # 选 continuous_top20 DESC → 最新 inflow DESC → sector_code ASC
                candidates.sort(key=lambda c: (
                    -c[2]["continuous_top20_days"],
                    -c[2]["main_inflow_wan_x10000"],
                    c[1].sector_code,
                ))
                best = candidates[0]

        if best is None:
            display_mapping = next(
                (m for m in mappings if m.status == fund_mapping_status),
                None,
            )
            items.append(_empty_item(
                fund_code=h.fund_code,
                fund_name=fund_name,
                related=related,
                mapping_status=fund_mapping_status,
                mapping=display_mapping,
            ))
            continue

        mapping, daily_row, facts = best
        intraday = intraday_by_code.get(daily_row.sector_code)
        matched_name = mapping.label
        purity = _compute_purity_score(related, matched_name, fund_name)
        items.append({
            "fund_code": h.fund_code,
            "fund_name": fund_name,
            "related_sectors": related,
            "mapped_sector": matched_name,
            "sector_code": daily_row.sector_code,
            "sector_name": daily_row.sector_name,
            "mapping_status": mapping.status,
            "mapping_confidence": mapping.confidence,
            "mapping_source": mapping.source,
            "purity_score": purity,
            "continuous_top20_days": facts["continuous_top20_days"],
            "last_20_top20_days": facts["last_20_top20_days"],
            "last_20_inflow_days": facts["last_20_inflow_days"],
            "latest_main_inflow_wan_x10000": daily_row.main_inflow_wan_x10000,
            "change_pct_x10000": daily_row.change_pct_x10000,
            "intraday_main_inflow_wan_x10000": (
                intraday.main_inflow_wan_x10000 if intraday else None
            ),
            "intraday_change_pct_x10000": (
                intraday.change_pct_x10000 if intraday else None
            ),
        })

    # buckets 分档:>=20 / 5..19 / <5(含 0)/ unmapped
    persistence_ge_20 = 0
    persistence_5_to_19 = 0
    persistence_lt_5 = 0
    unmapped = 0
    for it in items:
        c = it["continuous_top20_days"]
        if c is None:
            unmapped += 1
        elif c >= 20:
            persistence_ge_20 += 1
        elif c >= 5:
            persistence_5_to_19 += 1
        else:
            persistence_lt_5 += 1

    return {
        "trade_date": ctx["latest_date"] if ctx is not None else None,
        "snapshot_time": latest_snap,
        "buckets": {
            "persistence_ge_20": persistence_ge_20,
            "persistence_5_to_19": persistence_5_to_19,
            "persistence_lt_5": persistence_lt_5,
            "unmapped": unmapped,
            "total": len(items),
        },
        "holdings": items,
    }
