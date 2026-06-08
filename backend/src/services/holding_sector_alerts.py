"""持仓-板块事实预警(PR23)— 把"板块连续性事实 + 盘中实时变动" 主动
连接到"我的持仓",生成中性事实陈述。

R3 红线(spec):
- 全部是**客观事实陈述**,不是评分 / 健康度 / 买卖建议
- alert_type 是内部分类,**不等于买卖信号**
- message 不允许出现 买入 / 卖出 / 加仓 / 减仓 / 推荐 / 建议 / 看多 /
  看空 / 危险 / 机会 / 应该

R6 简化:
- 复用 sector_persistence._load_context + _compute_facts(PR20/21)
- intraday 只用 industry(跟 radar 一致,避免 concept 噪声)
- 持仓基金统一走 sector_aliases 高置信映射,再用 sector_code 关联资金流
- 一次性把 funds / holdings 拉进内存做映射

数据来源:
1. holdings + funds → sector_aliases → 每个 sector_code 关联了多少只我持仓的基金
2. sector_flow_daily → 连续天数事实(via _compute_facts)
3. intraday_sector_flow → 最新 snapshot industry 数据(可选)

alert_type 触发条件(同一板块多条命中时,按 A→B→C→D 优先序取第一条):
  A. intraday_outflow_on_long_persistence
     holding_count >= 2 AND continuous_top20_days >= 10
     AND intraday_main_inflow_yi < 0
  B. intraday_inflow_on_long_persistence
     holding_count >= 2 AND continuous_top20_days >= 10
     AND intraday_main_inflow_yi > 0
  C. continuous_outflow_holding_sector
     holding_count >= 2 AND continuous_outflow_days >= 3
  D. concentrated_holding_sector
     holding_count >= 5 AND continuous_top20_days >= 5

排序:
  holding_count DESC
  continuous_top20_days DESC
  abs(intraday_main_inflow_yi) DESC(null 当作 0)
  sector_name ASC

空库边界:
- holdings 为空 → items=[]
- sector_flow_daily 为空(_load_context 返回 None)→ items=[]
- intraday 为空 → intraday 字段全部 null,A/B 不触发但 C/D 仍可触发
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, IntradaySectorFlow, SectorFlowDaily
from src.services.sector_mapping import resolve_fund_sector_mappings
from src.services.sector_persistence import _compute_facts, _load_context


def _collect_holding_sector_groups(
    session: Session,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    """{sector_code: [{"fund_code","fund_name"}, ...]}。

    只考虑 holdings 表里实际持有的基金,并且只接受
    resolve_fund_sector_mappings() 返回的 eligible_for_sorting 映射。
    low_confidence / unmapped / not_applicable 都不参与提醒判断。
    """
    held_codes: set[str] = set(
        session.scalars(select(Holding.fund_code)).all()
    )
    diagnostics = {
        "held_fund_count": len(held_codes),
        "verified_held_fund_mappings": 0,
        "below_threshold_mappings": 0,
    }
    if not held_codes:
        return {}, diagnostics

    groups: dict[str, list[dict[str, str]]] = {}
    for fund in session.scalars(
        select(Fund).where(Fund.fund_code.in_(held_codes))
    ):
        seen_codes: set[str] = set()
        for mapping in resolve_fund_sector_mappings(session, fund.fund_code):
            if mapping.status == "low_confidence":
                diagnostics["below_threshold_mappings"] += 1
            if not mapping.eligible_for_sorting or mapping.sector_code is None:
                continue
            if mapping.sector_code in seen_codes:
                continue
            seen_codes.add(mapping.sector_code)
            diagnostics["verified_held_fund_mappings"] += 1
            groups.setdefault(mapping.sector_code, []).append({
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name or "",
            })
    return groups, diagnostics


def _load_intraday_industry(
    session: Session,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """加载最新 snapshot 的 industry intraday 数据。

    Returns:
        (latest_snapshot_time, by_code)
        latest_snapshot_time: datetime | None
        by_code: {sector_code: {sector_name, main_inflow_wan_x10000,
                                change_pct_x10000, rank}}
        rank 按 main_inflow_wan_x10000 DESC,1-based。
    """
    latest = session.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )
    if latest is None:
        return None, {}
    rows = list(session.scalars(
        select(IntradaySectorFlow)
        .where(IntradaySectorFlow.snapshot_time == latest)
        .where(IntradaySectorFlow.sector_type == "industry")
        .order_by(IntradaySectorFlow.main_inflow_wan_x10000.desc())
    ))
    by_code: dict[str, dict[str, Any]] = {}
    for rank, r in enumerate(rows, start=1):
        key = (r.sector_code or "").strip()
        if not key or key in by_code:
            continue
        by_code[key] = {
            "sector_name": r.sector_name,
            "main_inflow_wan_x10000": r.main_inflow_wan_x10000,
            "change_pct_x10000": r.change_pct_x10000,
            "rank": rank,
        }
    return latest, by_code


def _pick_alert_type(
    holding_count: int,
    continuous_top20_days: int,
    continuous_outflow_days: int,
    intraday_inflow_wan_x10000: int | None,
) -> str | None:
    """按 A→B→C→D 优先序返回第一条命中的 alert_type;无命中 → None。"""
    # A / B 需要 intraday 数据
    if intraday_inflow_wan_x10000 is not None:
        if (
            holding_count >= 2
            and continuous_top20_days >= 10
            and intraday_inflow_wan_x10000 < 0
        ):
            return "intraday_outflow_on_long_persistence"
        if (
            holding_count >= 2
            and continuous_top20_days >= 10
            and intraday_inflow_wan_x10000 > 0
        ):
            return "intraday_inflow_on_long_persistence"
    # C: 持续净流出
    if holding_count >= 2 and continuous_outflow_days >= 3:
        return "continuous_outflow_holding_sector"
    # D: 持仓集中且长期在场
    if holding_count >= 5 and continuous_top20_days >= 5:
        return "concentrated_holding_sector"
    return None


def _format_yi(wan_x10000: int) -> str:
    """_x10000 → 亿元 1 位小数字符串,带 +/- 符号。"""
    yi = wan_x10000 / 100_000_000  # _x10000 / 1e8 = 亿元
    return f"{yi:+.1f}"


def _build_message(
    alert_type: str,
    sector_name: str,
    holding_count: int,
    facts: dict[str, Any],
    intraday_inflow_wan_x10000: int | None,
) -> str:
    """生成事实陈述。R3 红线:不出现 买入/卖出/加仓/减仓/推荐/建议/看多/
    看空/危险/机会/应该。"""
    c_top = facts["continuous_top20_days"]
    c_out = facts["continuous_outflow_days"]
    l20_top = facts["last_20_top20_days"]

    if alert_type == "intraday_outflow_on_long_persistence":
        assert intraday_inflow_wan_x10000 is not None
        return (
            f"你持有 {holding_count} 只关联{sector_name}的基金。该板块"
            f"连续Top20 {c_top}天,近20日Top20 {l20_top}次,今日盘中"
            f"主力净流出 {_format_yi(intraday_inflow_wan_x10000)}亿。"
        )
    if alert_type == "intraday_inflow_on_long_persistence":
        assert intraday_inflow_wan_x10000 is not None
        return (
            f"你持有 {holding_count} 只关联{sector_name}的基金。该板块"
            f"连续Top20 {c_top}天,近20日Top20 {l20_top}次,今日盘中"
            f"主力净流入 {_format_yi(intraday_inflow_wan_x10000)}亿。"
        )
    if alert_type == "continuous_outflow_holding_sector":
        return (
            f"你持有 {holding_count} 只关联{sector_name}的基金。该板块"
            f"连续净流出 {c_out} 天。"
        )
    if alert_type == "concentrated_holding_sector":
        return (
            f"你持有 {holding_count} 只关联{sector_name}的基金,持仓较为"
            f"集中。该板块连续Top20 {c_top} 天。"
        )
    return ""  # 不会到这里


def build_holding_sector_alerts(
    session: Session, *, n: int = 10
) -> dict[str, Any]:
    """构建持仓-板块事实预警(service 出 dict,API 层做 Decimal 转换)。

    Returns:
        {
          "trade_date": date | None,        # daily persistence 最新日
          "snapshot_time": datetime | None, # intraday 最新 snapshot;无则 null
          "items": [
            {
              "sector_name": str,
              "sector_code": str,                              # 优先 intraday;否则 daily
              "holding_count": int,
              "holding_fund_codes": list[str],                 # 全量(前端再截)
              "holding_fund_names": list[str],                 # 全量
              "intraday_main_inflow_wan_x10000": int | None,
              "intraday_rank": int | None,
              "intraday_change_pct_x10000": int | None,
              "continuous_top20_days": int,
              "continuous_inflow_days": int,
              "continuous_outflow_days": int,
              "last_20_top20_days": int,
              "last_20_inflow_days": int,
              "last_20_outflow_days": int,
              "alert_type": str,
              "message": str,
            },
            ...
          ]
        }
    """
    holding_groups, mapping_diagnostics = _collect_holding_sector_groups(session)
    diagnostics = {
        "verified_held_fund_mappings": mapping_diagnostics[
            "verified_held_fund_mappings"
        ],
        "below_threshold_mappings": mapping_diagnostics[
            "below_threshold_mappings"
        ],
        "missing_latest_daily_rows": 0,
        "latest_intraday_matches": 0,
        "final_candidate_count": 0,
    }

    ctx = _load_context(session)
    if ctx is None:
        # spec 7:daily 为空 → 空数组
        return {
            "trade_date": None,
            "snapshot_time": None,
            "items": [],
            "diagnostics": diagnostics,
            "empty_reason": "暂无收盘板块资金数据",
        }

    if not holding_groups:
        if mapping_diagnostics["held_fund_count"] == 0:
            empty_reason = "暂无持仓"
        elif diagnostics["below_threshold_mappings"] > 0:
            empty_reason = "持仓映射均低于置信门槛或暂无高置信映射"
        else:
            empty_reason = "暂无可参与提醒判断的高置信持仓映射"
        return {
            "trade_date": ctx["latest_date"],
            "snapshot_time": None,
            "items": [],
            "diagnostics": diagnostics,
            "empty_reason": empty_reason,
        }

    latest_snapshot, intraday_by_code = _load_intraday_industry(session)

    # 最新日 industry 行,按 sector_code 索引(_compute_facts 需要原 row)
    latest_industry_by_code: dict[str, SectorFlowDaily] = {}
    by_inflow: dict[str, int] = {}  # 排名给 _compute_facts;不参与 alert 输出
    latest_rows = [
        r for r in ctx["all_rows"]
        if r.trade_date == ctx["latest_date"] and r.sector_type == "industry"
    ]
    latest_rows.sort(key=lambda r: -r.main_inflow_wan_x10000)
    for i, r in enumerate(latest_rows, start=1):
        key = (r.sector_code or "").strip()
        if not key or key in latest_industry_by_code:
            continue
        latest_industry_by_code[key] = r
        by_inflow[key] = i

    diagnostics["missing_latest_daily_rows"] = sum(
        sector_code not in latest_industry_by_code
        for sector_code in holding_groups
    )
    diagnostics["latest_intraday_matches"] = sum(
        sector_code in intraday_by_code
        for sector_code in holding_groups
    )

    items: list[dict[str, Any]] = []
    for sector_code, fund_list in holding_groups.items():
        holding_count = len(fund_list)
        daily_row = latest_industry_by_code.get(sector_code)
        if daily_row is None:
            # 无 daily 数据 → 所有触发条件都需要 daily,跳过
            continue
        facts = _compute_facts(ctx, daily_row, by_inflow[sector_code])

        intraday_info = intraday_by_code.get(sector_code)
        intraday_wan_x10000 = (
            intraday_info["main_inflow_wan_x10000"]
            if intraday_info else None
        )

        alert_type = _pick_alert_type(
            holding_count=holding_count,
            continuous_top20_days=facts["continuous_top20_days"],
            continuous_outflow_days=facts["continuous_outflow_days"],
            intraday_inflow_wan_x10000=intraday_wan_x10000,
        )
        if alert_type is None:
            continue

        message = _build_message(
            alert_type=alert_type,
            sector_name=daily_row.sector_name,
            holding_count=holding_count,
            facts=facts,
            intraday_inflow_wan_x10000=intraday_wan_x10000,
        )

        items.append({
            "sector_name": daily_row.sector_name,
            "sector_code": daily_row.sector_code,
            "holding_count": holding_count,
            "holding_fund_codes": [f["fund_code"] for f in fund_list],
            "holding_fund_names": [f["fund_name"] for f in fund_list],
            "intraday_main_inflow_wan_x10000": intraday_wan_x10000,
            "intraday_rank": (
                intraday_info["rank"] if intraday_info else None
            ),
            "intraday_change_pct_x10000": (
                intraday_info["change_pct_x10000"] if intraday_info else None
            ),
            "continuous_top20_days": facts["continuous_top20_days"],
            "continuous_inflow_days": facts["continuous_inflow_days"],
            "continuous_outflow_days": facts["continuous_outflow_days"],
            "last_20_top20_days": facts["last_20_top20_days"],
            "last_20_inflow_days": facts["last_20_inflow_days"],
            "last_20_outflow_days": facts["last_20_outflow_days"],
            "alert_type": alert_type,
            "message": message,
        })

    # 排序:holding_count DESC, continuous_top20 DESC,
    #       abs(intraday inflow) DESC(null → 0), sector_name ASC
    def _sort_key(it: dict[str, Any]) -> tuple[int, int, int, str]:
        intraday_abs = abs(it["intraday_main_inflow_wan_x10000"] or 0)
        return (
            -it["holding_count"],
            -it["continuous_top20_days"],
            -intraday_abs,
            it["sector_name"],
        )

    items.sort(key=_sort_key)
    diagnostics["final_candidate_count"] = len(items)

    if items:
        empty_reason = None
    elif diagnostics["missing_latest_daily_rows"] == len(holding_groups):
        empty_reason = "高置信持仓映射在最新收盘行业数据中无匹配"
    else:
        empty_reason = "持仓关联板块尚未达到提醒触发门槛"

    return {
        "trade_date": ctx["latest_date"],
        "snapshot_time": latest_snapshot,
        "items": items[:n],
        "diagnostics": diagnostics,
        "empty_reason": empty_reason,
    }
