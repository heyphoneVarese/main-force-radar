"""主力雷达 — 把盘中实时板块资金流映射到 holdings + candidates(PR16)。

R3 兼容:本服务**只输出客观排序**(rank/inflow → score);不暴露任何
buy/sell/long/short/hold/加仓/减仓/继续持有/建议 类词汇。score 的含义
是"该基金所映射板块的实时强势程度",不是操作信号。

R6 简化:
- 第一版只用 industry(intraday_sector_flow.sector_type='industry')
- 精确匹配(strip 后 equals),不模糊
- score 公式:rank_score + inflow_score,封顶 9
- 不用 cache;每次 API 调用现算(数据量小:~500 板块 × 100 funds = 50k 比较)

数据流:
    intraday_sector_flow (latest snapshot, industry only)
        │
        ├─► 按 main_inflow_wan_x10000 DESC 排 → 给每个 sector 标 rank (1-based)
        │
        ▼
    Fund.related_sectors (中文标签数组)
        │
        ├─► 任一标签精确命中 sector_name → 该 fund 入候选
        │   多个命中,取 rank 最小的(最强势板块)
        │
        ▼
    fund_code ∈ holdings? → holdings 区  / 否则 → candidates 区
        │
        ▼
    score = rank_score(rank) + inflow_score(yi),封顶 9
        │
        ▼
    各区按 (score DESC, sector_rank ASC) 排,取前 n 条
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, IntradaySectorFlow


def _rank_score(rank: int) -> int:
    """板块排名 → 强势加分(0..5)。rank 1-based。"""
    if rank == 1:
        return 5
    if rank == 2:
        return 4
    if rank == 3:
        return 3
    if 4 <= rank <= 10:
        return 2
    if 11 <= rank <= 20:
        return 1
    return 0


def _inflow_score(inflow_yi: float) -> int:
    """主力净流入亿元 → 加分(0..4)。负值/小于10亿 → 0。"""
    if inflow_yi >= 100:
        return 4
    if inflow_yi >= 50:
        return 3
    if inflow_yi >= 20:
        return 2
    if inflow_yi >= 10:
        return 1
    return 0


def _compute_score(rank: int, inflow_wan_x10000: int) -> int:
    """合并打分,封顶 9。"""
    # _x10000 → 万 → 亿 = _x10000 / 10000 / 10000 = _x10000 / 1e8
    inflow_yi = inflow_wan_x10000 / 100_000_000
    return min(9, _rank_score(rank) + _inflow_score(inflow_yi))


# ============================================================
# 基金纯度评分(PR17)
# ============================================================
# R3 兼容:purity_score 只表达"基金与该强势板块的主题贴合度",
# 不是收益预测、不是买卖建议。文档化在 schema description 里。
#
# 第一版 R6 简化:不读基金真实持仓成分(不接 fund_portfolio_hold_em),
# 只看 related_sectors 数量 + fund_name 命中关键词。
#
# 主题字典:matched_sector ∈ keywords[i] 时,fund_name 命中同主题
# 任一 keyword → +1 bonus(rule 6)。matched_sector 本身在 fund_name 里
# → 另 +1 bonus(rule 5)。两个 bonus 可同时触发,最后封顶 9。

THEME_GROUPS: list[dict] = [
    {
        "name": "semiconductor",
        "sector_keywords": ["半导体", "芯片", "集成电路"],
        "name_keywords": ["半导体", "芯片", "集成电路"],
    },
    {
        "name": "ai",
        "sector_keywords": ["人工智能", "AI", "算力", "光模块", "CPO"],
        "name_keywords": ["人工智能", "AI", "算力", "光模块", "CPO"],
    },
    {
        "name": "power",
        "sector_keywords": ["电力", "电网", "储能"],
        "name_keywords": ["电力", "电网", "储能"],
    },
    {
        "name": "defense",
        "sector_keywords": ["军工", "卫星", "商业航天"],
        "name_keywords": ["军工", "卫星", "商业航天"],
    },
    {
        "name": "gold",
        "sector_keywords": ["黄金", "有色"],
        "name_keywords": ["黄金", "有色"],
    },
    {
        "name": "consumer",
        "sector_keywords": ["白酒", "消费"],
        "name_keywords": ["白酒", "消费"],
    },
]


def _theme_name_bonus(matched_sector: str, fund_name: str) -> int:
    """Rule 6:matched_sector 命中某个主题 group,且 fund_name 含该 group
    任一 name_keyword → +1。"""
    for theme in THEME_GROUPS:
        in_theme = any(kw in matched_sector for kw in theme["sector_keywords"])
        if not in_theme:
            continue
        if any(kw in fund_name for kw in theme["name_keywords"]):
            return 1
    return 0


def _compute_purity_score(
    related_sectors: list[str], matched_sector: str, fund_name: str
) -> int:
    """规则(spec):
        1. related_sectors 长度 1     → base 9
        2. 长度 2                     → base 8
        3. 长度 3                     → base 7
        4. 长度 ≥ 4                   → base 6
        5. matched_sector 出现在 fund_name 中(子串) → +1
        6. matched_sector 属于某主题 + fund_name 含该主题同义词 → +1
        最终封顶 9。

    matched_sector 必然已在 related_sectors 中(由调用方保证)。
    """
    n = len(related_sectors)
    if n <= 1:
        base = 9
    elif n == 2:
        base = 8
    elif n == 3:
        base = 7
    else:
        base = 6

    bonus = 0
    # rule 5
    if matched_sector and matched_sector in (fund_name or ""):
        bonus += 1
    # rule 6
    bonus += _theme_name_bonus(matched_sector, fund_name or "")

    return min(9, base + bonus)


def build_intraday_radar(session: Session, *, n: int = 20) -> dict[str, Any]:
    """构建主力雷达 — 服务层产出 dict,API 层负责 Decimal 转换。

    返回 _x10000 整数原样;sector_main_inflow 字段后续在 API 层算成
    万元/亿元/百分数 Decimal。

    Returns:
        {
          "mode": "intraday",
          "trade_date": date | None,
          "snapshot_time": datetime | None,
          "holdings": [
            {
              "fund_code": str,
              "fund_name": str,
              "matched_sector": str,                       # 命中的中文标签
              "sector_code": str,                          # BK code
              "sector_rank": int,                          # 在 industry 内的 rank
              "sector_main_inflow_wan_x10000": int,        # 原始 _x10000
              "sector_change_pct_x10000": int | None,
              "score": int,                                # 0..9
              "badge": "已持有",
            },
            ...
          ],
          "candidates": [...],  # 同结构,badge="候选"
        }

    n=0 时上层应已被 Query(ge=1) 拒掉,本函数不防御。
    """
    # 1. 最新 snapshot
    latest_snapshot = session.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        return {
            "mode": "intraday",
            "trade_date": None,
            "snapshot_time": None,
            "holdings": [],
            "candidates": [],
        }

    # 2. 该 snapshot 下 industry 板块,按 main_inflow_wan_x10000 DESC
    #    第一版只用 industry(concept 抓取不稳定,避免噪声)
    sector_rows = list(session.scalars(
        select(IntradaySectorFlow)
        .where(IntradaySectorFlow.snapshot_time == latest_snapshot)
        .where(IntradaySectorFlow.sector_type == "industry")
        .order_by(IntradaySectorFlow.main_inflow_wan_x10000.desc())
    ))

    # 3. sector_name(strip)→ (rank, IntradaySectorFlow 行)
    sector_by_name: dict[str, tuple[int, IntradaySectorFlow]] = {}
    for rank, s in enumerate(sector_rows, start=1):
        key = (s.sector_name or "").strip()
        if not key:
            continue
        # 同名不同 code 罕见;保留首个(rank 最小)
        if key not in sector_by_name:
            sector_by_name[key] = (rank, s)

    # 4. 持仓 fund_code 集合,O(1) 判 badge
    holding_codes: set[str] = set(
        session.scalars(select(Holding.fund_code)).all()
    )

    # 5. 遍历 funds,精确匹配 related_sectors → sector_name
    holdings_items: list[dict[str, Any]] = []
    candidates_items: list[dict[str, Any]] = []

    for fund in session.scalars(select(Fund)):
        related = fund.related_sectors or []
        if not related:
            continue

        # 多个命中,取 rank 最小(最强板块)
        best: tuple[int, IntradaySectorFlow, str] | None = None
        for label in related:
            label_clean = (label or "").strip()
            if not label_clean:
                continue
            hit = sector_by_name.get(label_clean)
            if hit is None:
                continue
            rank, sector_row = hit
            if best is None or rank < best[0]:
                best = (rank, sector_row, label_clean)

        if best is None:
            continue

        rank, sector_row, matched_label = best
        score = _compute_score(rank, sector_row.main_inflow_wan_x10000)
        purity = _compute_purity_score(
            related, matched_label, fund.fund_name or ""
        )
        is_held = fund.fund_code in holding_codes

        item: dict[str, Any] = {
            "fund_code": fund.fund_code,
            "fund_name": fund.fund_name,
            "matched_sector": matched_label,
            "sector_code": sector_row.sector_code,
            "sector_rank": rank,
            "sector_main_inflow_wan_x10000": sector_row.main_inflow_wan_x10000,
            "sector_change_pct_x10000": sector_row.change_pct_x10000,
            "score": score,
            "purity_score": purity,
            "badge": "已持有" if is_held else "候选",
        }

        if is_held:
            holdings_items.append(item)
        else:
            candidates_items.append(item)

    # 6. 各自按 (score DESC, purity_score DESC, sector_rank ASC, fund_code ASC) 排,取前 n
    # PR17 改:加入 purity_score 作为同一板块强度内的区分键 — 让"纯半导体基金"
    # 排在"半导体只是 related 标签之一的混合基金"前面。fund_code ASC 是稳定排序兜底。
    def _sort_key(it: dict[str, Any]) -> tuple[int, int, int, str]:
        return (-it["score"], -it["purity_score"], it["sector_rank"], it["fund_code"])

    holdings_items.sort(key=_sort_key)
    candidates_items.sort(key=_sort_key)

    return {
        "mode": "intraday",
        "trade_date": latest_snapshot.date(),
        "snapshot_time": latest_snapshot,
        "holdings": holdings_items[:n],
        "candidates": candidates_items[:n],
    }
