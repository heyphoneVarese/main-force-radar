"""板块连续天数事实(PR20)— 基于 sector_flow_daily 历史。

R3 红线:
- 全部是**事实统计**,不是 score、不是评分、不是买卖建议、不预测涨跌
- 字段名都用 "_days" / "_count" 这种客观计数表达
- 调用方不要把这些数字再合成 "health score" 之类的派生分

R6 简化:
- 不用 intraday 表(避免盘中噪音污染历史连续性判断)
- 一次性把 sector_flow_daily 整张表读进内存做 grouping,避免 N+1 查询
  (典型规模:~500 板块 × 历史 30+ 交易日 = 15-30k 行,内存几 MB)

算法:
1. 取最新 trade_date
2. 该日按 main_inflow 排,取 top n(可按 sector_type 过滤)
3. 对每个上榜板块,基于全表 grouping 计算:
   - continuous_inflow_days:从最新日开始连续 inflow > 0 的天数
                              (遇 <=0 或该 sector 在某日无记录 → stop)
   - continuous_outflow_days:同上但 < 0
   - continuous_top20_days:从最新日开始连续在"同 sector_type"的 Top20
                            里的天数(stop 同上)
   - last_20_top20_days:最近 20 个交易日内进入 Top20 的次数
   - last_20_inflow_days:最近 20 个交易日内 inflow > 0 的次数
   - last_20_outflow_days:最近 20 个交易日内 inflow < 0 的次数

"交易日"= sector_flow_daily 实际存在的 trade_date(节假日 / 数据缺失自然
跳过)。"最近 20 个交易日"指 all_dates 倒序前 20 个。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import SectorFlowDaily

# top20 计算窗口大小(spec 写死 20)
_TOP_K_FOR_STREAK = 20
# PR21:多个 last_N 统计窗口
_LAST_N_WINDOWS: tuple[int, ...] = (5, 10, 20)


def _build_topk_lookup(
    rows: list[SectorFlowDaily],
) -> dict[tuple[str, date], set[str]]:
    """{(sector_type, trade_date): set of top-K sector_codes by inflow}。"""
    grouped: dict[tuple[str, date], list[SectorFlowDaily]] = {}
    for r in rows:
        grouped.setdefault((r.sector_type, r.trade_date), []).append(r)
    out: dict[tuple[str, date], set[str]] = {}
    for key, group in grouped.items():
        group.sort(key=lambda r: -r.main_inflow_wan_x10000)
        out[key] = {r.sector_code for r in group[:_TOP_K_FOR_STREAK]}
    return out


def _continuous_count(
    code: str,
    sector_type: str,
    dates_desc: list[date],
    history: dict[date, SectorFlowDaily],
    *,
    condition: str,
    topk_lookup: dict[tuple[str, date], set[str]] | None = None,
) -> int:
    """从 dates_desc[0] 起,连续满足 condition 的天数。遇到不满足或缺记录则 stop。

    condition:
      "inflow"  → main_inflow_wan_x10000 > 0
      "outflow" → main_inflow_wan_x10000 < 0
      "top20"   → sector_code 在 topk_lookup[(sector_type, d)] 里
    """
    streak = 0
    for d in dates_desc:
        if condition == "top20":
            assert topk_lookup is not None
            if code in topk_lookup.get((sector_type, d), set()):
                streak += 1
            else:
                break
        else:
            row = history.get(d)
            if row is None:
                break
            v = row.main_inflow_wan_x10000
            if condition == "inflow" and v > 0:
                streak += 1
            elif condition == "outflow" and v < 0:
                streak += 1
            else:
                break
    return streak


def _load_context(session: Session) -> dict[str, Any] | None:
    """共享:一次性拉所有 sector_flow_daily 行并预聚合 lookups。

    PR22 提取出来给 build_sector_persistence + build_persistence_leaders 复用。

    Returns: dict 或 None(空库)。
      latest_date    : date
      all_rows       : list[SectorFlowDaily]
      all_dates      : list[date] desc
      topk_lookup    : dict[(sector_type, date)] → set[sector_code]
      history_by_code: dict[sector_code] → dict[date] → SectorFlowDaily
      windowed_dates : dict[int] → list[date](_LAST_N_WINDOWS 各切片)
    """
    latest_date = session.scalar(
        select(SectorFlowDaily.trade_date)
        .order_by(SectorFlowDaily.trade_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return None

    all_rows = list(session.scalars(select(SectorFlowDaily)))
    all_dates: list[date] = sorted(
        {r.trade_date for r in all_rows}, reverse=True
    )
    topk_lookup = _build_topk_lookup(all_rows)
    history_by_code: dict[str, dict[date, SectorFlowDaily]] = {}
    for r in all_rows:
        history_by_code.setdefault(r.sector_code, {})[r.trade_date] = r
    windowed_dates: dict[int, list[date]] = {
        k: all_dates[:k] for k in _LAST_N_WINDOWS
    }
    return {
        "latest_date": latest_date,
        "all_rows": all_rows,
        "all_dates": all_dates,
        "topk_lookup": topk_lookup,
        "history_by_code": history_by_code,
        "windowed_dates": windowed_dates,
    }


def _compute_facts(
    ctx: dict[str, Any], row: SectorFlowDaily, rank: int
) -> dict[str, Any]:
    """共享:对一个 sector(在 latest_date 那条 row)算全部 12 个事实字段。

    rank:该 sector 在最新日按 main_inflow DESC 的排名(1-based)。
    """
    code = row.sector_code
    own_type = row.sector_type
    sector_hist = ctx["history_by_code"].get(code, {})
    all_dates = ctx["all_dates"]
    topk_lookup = ctx["topk_lookup"]

    c_in = _continuous_count(
        code, own_type, all_dates, sector_hist, condition="inflow"
    )
    c_out = _continuous_count(
        code, own_type, all_dates, sector_hist, condition="outflow"
    )
    c_top = _continuous_count(
        code, own_type, all_dates, sector_hist,
        condition="top20", topk_lookup=topk_lookup,
    )

    window_counts: dict[str, int] = {}
    for k in _LAST_N_WINDOWS:
        k_dates = ctx["windowed_dates"][k]
        k_top = 0
        k_in = 0
        k_out = 0
        for d in k_dates:
            if code in topk_lookup.get((own_type, d), set()):
                k_top += 1
            r = sector_hist.get(d)
            if r is None:
                continue
            if r.main_inflow_wan_x10000 > 0:
                k_in += 1
            elif r.main_inflow_wan_x10000 < 0:
                k_out += 1
        window_counts[f"last_{k}_top20_days"] = k_top
        window_counts[f"last_{k}_inflow_days"] = k_in
        window_counts[f"last_{k}_outflow_days"] = k_out

    return {
        "sector_code": code,
        "sector_name": row.sector_name,
        "sector_type": own_type,
        "main_inflow_wan_x10000": row.main_inflow_wan_x10000,
        "rank": rank,
        "continuous_inflow_days": c_in,
        "continuous_outflow_days": c_out,
        "continuous_top20_days": c_top,
        **window_counts,
    }


def build_sector_persistence(
    session: Session,
    *,
    n: int = 20,
    sector_type: str = "industry",
) -> dict[str, Any]:
    """主入口(PR20/21 不变)。返回 dict(_x10000 整数原样,API 层转 Decimal)。

    sector_type:'industry' / 'concept' / 'all'
    - 'industry'/'concept':最新日 top-N 在该类型内排;continuous_top20 同
    - 'all':最新日 top-N 跨 industry+concept 合并排;continuous_top20 仍
      按板块"自己 sector_type 内的 top20"(industry 看 industry top20,
      concept 看 concept top20)
    """
    ctx = _load_context(session)
    if ctx is None:
        return {
            "trade_date": None,
            "sector_type": sector_type,
            "items": [],
        }

    # 最新日按 sector_type 过滤 + 按 inflow DESC 取 top n
    latest_rows = [
        r for r in ctx["all_rows"] if r.trade_date == ctx["latest_date"]
    ]
    if sector_type != "all":
        latest_rows = [r for r in latest_rows if r.sector_type == sector_type]
    latest_rows.sort(key=lambda r: -r.main_inflow_wan_x10000)
    top_rows = latest_rows[:n]

    items = [_compute_facts(ctx, r, i + 1) for i, r in enumerate(top_rows)]

    return {
        "trade_date": ctx["latest_date"],
        "sector_type": sector_type,
        "items": items,
    }


# =====================================================================
# PR22 — 连续 Top20 排行榜
# =====================================================================


def build_persistence_leaders(
    session: Session,
    *,
    n: int = 10,
    sector_type: str = "industry",
) -> dict[str, Any]:
    """排行榜:对最新日所有(过滤后的)板块算事实,然后按"持续出现"键排序。

    R3 红线:**不做评分 / 健康度 / 买卖建议**。这里只是用客观计数键做
    排序顺序的调整 — continuous_top20_days 排第一是因为它最能反映"持续
    出现"这个事实,不是"看多/看空"。

    排序键(全部 DESC,最后 sector_code ASC 兜底稳定):
      1. continuous_top20_days
      2. last_20_top20_days
      3. last_20_inflow_days
      4. main_inflow_wan_x10000(latest 当日)
      5. sector_code(ASC,兜底)

    latest_rank:在 sector_type 过滤后的最新日按 inflow DESC 的位置。
    """
    ctx = _load_context(session)
    if ctx is None:
        return {
            "trade_date": None,
            "sector_type": sector_type,
            "items": [],
        }

    # 最新日按 sector_type 过滤
    latest_rows = [
        r for r in ctx["all_rows"] if r.trade_date == ctx["latest_date"]
    ]
    if sector_type != "all":
        latest_rows = [r for r in latest_rows if r.sector_type == sector_type]

    # 先按 inflow 排,标 latest_rank(1-based)— 给客户端"今天主力净流入排第几"
    by_inflow_desc = sorted(
        latest_rows, key=lambda r: -r.main_inflow_wan_x10000
    )
    rank_by_code = {r.sector_code: i + 1 for i, r in enumerate(by_inflow_desc)}

    # 对每个板块算完整事实,带上 latest_rank
    all_items: list[dict[str, Any]] = []
    for r in latest_rows:
        facts = _compute_facts(ctx, r, rank_by_code[r.sector_code])
        # 复制 rank → latest_rank,api 层用这个名字
        facts["latest_rank"] = facts["rank"]
        all_items.append(facts)

    # 按 leader keys 排
    def _leader_key(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
        return (
            -item["continuous_top20_days"],
            -item["last_20_top20_days"],
            -item["last_20_inflow_days"],
            -item["main_inflow_wan_x10000"],
            item["sector_code"],
        )

    all_items.sort(key=_leader_key)

    return {
        "trade_date": ctx["latest_date"],
        "sector_type": sector_type,
        "items": all_items[:n],
    }
