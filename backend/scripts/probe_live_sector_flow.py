"""P0 实时探针 — 对比 4 条采集路径 + 3 条 DB 状态。

跑法:
    docker compose exec backend uv run --no-dev python -m scripts.probe_live_sector_flow

不写任何表。只读 + 只调上游 API。每条路径独立 try-except,
单点失败不影响其它路径输出。

输出顺序(原顺序):
  1. direct eastmoney  - industry
  2. direct eastmoney  - concept
  3. akshare fallback  - industry
  4. akshare fallback  - concept
  5. DB latest intraday snapshot
  6. DB latest sector_flow_daily trade_date
  7. DB latest market_index_daily trade_date

每条均打印:
  - source 名 / 状态(OK / FAILED / EMPTY)
  - 返回行数(or DB 时间戳)
  - top 5(板块名 + 主力净流入亿元)
  - 失败时打印异常类型 + 消息(最多 3 行 traceback)
"""

from __future__ import annotations

import logging
import sys
import traceback
from typing import Any

import pandas as pd
from sqlalchemy import select

from src.db import SessionLocal
from src.models import (
    IntradaySectorFlow,
    MarketIndexDaily,
    SectorFlowDaily,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("probe-live")


def _hr(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _print_top5_df(df: pd.DataFrame, label: str) -> None:
    """统一格式打印 top5。akshare 列名 = ['名称', '今日主力净流入-净额', ...]。"""
    if df is None or df.empty:
        print(f"  {label}: EMPTY (0 rows)")
        return
    try:
        sub = df[["名称", "今日主力净流入-净额"]].copy()
        sub["亿元"] = sub["今日主力净流入-净额"].astype(float) / 1e8
        sub = sub.sort_values("亿元", ascending=False).head(5)
        print(f"  {label}: rows={len(df)}, top5:")
        for _, r in sub.iterrows():
            print(f"    {r['名称']:<12} {r['亿元']:+.2f}亿")
    except Exception as e:
        print(f"  {label}: rows={len(df)} (top5 解析失败:{type(e).__name__}: {e})")


def _try_path(name: str, fn: Any, label: str) -> None:
    print(f"\n[{name}]")
    try:
        df = fn()
        if df is None or (hasattr(df, "empty") and df.empty):
            print(f"  STATUS: EMPTY")
            print(f"  rows = 0")
            return
        print(f"  STATUS: OK")
        _print_top5_df(df, label)
    except Exception as e:
        print(f"  STATUS: FAILED")
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        # 限 3 行 traceback
        tb = traceback.format_exc().splitlines()[-3:]
        for line in tb:
            print(f"  {line}")


# =====================================================================
# 1-2. direct eastmoney
# =====================================================================


def probe_direct() -> None:
    _hr("1. direct eastmoney (push2.eastmoney.com/api/qt/clist/get)")
    from src.services.data_fetcher import _fetch_sector_flow_direct
    _try_path(
        "direct industry", lambda: _fetch_sector_flow_direct("行业资金流"),
        "direct industry",
    )
    _try_path(
        "direct concept", lambda: _fetch_sector_flow_direct("概念资金流"),
        "direct concept",
    )


# =====================================================================
# 3-4. akshare fallback
# =====================================================================


def probe_akshare() -> None:
    _hr("2. akshare fallback (ak.stock_sector_fund_flow_rank)")
    try:
        import akshare as ak
    except Exception as e:
        print(f"  akshare 导入失败:{type(e).__name__}: {e}")
        return
    _try_path(
        "akshare industry",
        lambda: ak.stock_sector_fund_flow_rank(
            indicator="今日", sector_type="行业资金流"
        ),
        "akshare industry",
    )
    _try_path(
        "akshare concept",
        lambda: ak.stock_sector_fund_flow_rank(
            indicator="今日", sector_type="概念资金流"
        ),
        "akshare concept",
    )


# =====================================================================
# 5-7. DB 现状
# =====================================================================


def probe_db() -> None:
    _hr("3. DB 现状(只读)")
    try:
        with SessionLocal() as session:
            # intraday
            latest_snap = session.scalar(
                select(IntradaySectorFlow.snapshot_time)
                .order_by(IntradaySectorFlow.snapshot_time.desc())
                .limit(1)
            )
            n_intraday_at_latest = (
                session.query(IntradaySectorFlow)
                .filter(IntradaySectorFlow.snapshot_time == latest_snap)
                .count()
                if latest_snap else 0
            )
            print(f"\n[5] intraday_sector_flow latest snapshot_time:")
            print(f"  {latest_snap if latest_snap else 'NONE (table empty)'}")
            print(f"  rows at that snapshot: {n_intraday_at_latest}")

            # daily sector
            latest_daily = session.scalar(
                select(SectorFlowDaily.trade_date)
                .order_by(SectorFlowDaily.trade_date.desc())
                .limit(1)
            )
            n_daily = (
                session.query(SectorFlowDaily)
                .filter(SectorFlowDaily.trade_date == latest_daily)
                .count()
                if latest_daily else 0
            )
            print(f"\n[6] sector_flow_daily latest trade_date:")
            print(f"  {latest_daily if latest_daily else 'NONE (table empty)'}")
            print(f"  rows at that date: {n_daily}")

            # market
            latest_market = session.scalar(
                select(MarketIndexDaily.trade_date)
                .order_by(MarketIndexDaily.trade_date.desc())
                .limit(1)
            )
            n_market = (
                session.query(MarketIndexDaily)
                .filter(MarketIndexDaily.trade_date == latest_market)
                .count()
                if latest_market else 0
            )
            print(f"\n[7] market_index_daily latest trade_date:")
            print(f"  {latest_market if latest_market else 'NONE (table empty)'}")
            print(f"  rows at that date: {n_market}")
    except Exception as e:
        print(f"  DB 探针失败:{type(e).__name__}: {e}")
        traceback.print_exc()


def main() -> int:
    print()
    print("┌" + "─" * 70 + "┐")
    print("│  P0 实时探针:对比上游 4 条采集路径 + 3 条 DB 状态           │")
    print("│  (只读;不写库;不退出非零除非脚本本身 crash)                  │")
    print("└" + "─" * 70 + "┘")
    probe_direct()
    probe_akshare()
    probe_db()
    print()
    print("=" * 72)
    print("  完成。诊断思路:")
    print("    - direct OK 但 DB 没新数据      → scheduler / cron 问题")
    print("    - direct FAILED 但 akshare OK   → 暂时启用 akshare 路径")
    print("    - 两个都 FAILED                  → 上游问题(IP 风控 / 节假日)")
    print("    - 两个都 OK 但 DB 旧             → 入库逻辑或时区问题")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
