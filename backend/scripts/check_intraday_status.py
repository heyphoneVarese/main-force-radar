"""盘中实时表状态报告(PR18)— 只读,验证自动采集是否正常。

跑法(backend 目录下):
    uv run python scripts/check_intraday_status.py

Docker 上:
    docker compose exec backend uv run --no-dev python -m \\
        scripts.check_intraday_status

输出包含:
1. intraday_sector_flow 总行数
2. 最新 snapshot_time 和 trade_date
3. 各 sector_type(industry / concept)在最新 snapshot 的条数
4. 最新 snapshot 的 Top 10 industry 板块(rank / name / 主力净流入 / 涨跌)
5. 最新 snapshot 的 Top 10 concept(没数据时显示 concept_count=0,不报错)
6. 空表 → 显示 "暂无盘中数据" 后正常退出 0

只读 — 不写库,不动业务。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db import SessionLocal
from src.models import IntradaySectorFlow

logger = logging.getLogger(__name__)


def _fmt_yi(wan_x10000: int) -> str:
    """主力净流入 _x10000 → '+95.0亿' / '-379.3亿'。"""
    yi = wan_x10000 / 100_000_000  # _x10000 → 万 → 亿
    sign = "+" if yi > 0 else ""    # 负号 :.1f 自带
    return f"{sign}{yi:.1f}亿"


def _fmt_pct(pct_x10000: int | None) -> str:
    """涨跌幅 _x10000 → '+2.10%';None → 'n/a'。"""
    if pct_x10000 is None:
        return "n/a"
    pct = pct_x10000 / 100  # x10000 fraction → percent
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}%"


def collect_status(session: Session) -> dict[str, Any]:
    """读 intraday_sector_flow 当前状态。空表时所有字段都是合理的 falsy 值。

    Returns:
        {
          "total_rows": int,
          "latest_snapshot_time": datetime | None,
          "latest_trade_date": date | None,
          "by_type": {sector_type: count, ...},     # latest snapshot
          "industry_top": list[IntradaySectorFlow], # latest snapshot, top 10 by inflow
          "concept_top": list[IntradaySectorFlow],  # 同上
        }
    """
    total = session.scalar(select(func.count(IntradaySectorFlow.id))) or 0

    if total == 0:
        return {
            "total_rows": 0,
            "latest_snapshot_time": None,
            "latest_trade_date": None,
            "by_type": {},
            "industry_top": [],
            "concept_top": [],
        }

    latest_snapshot = session.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )

    latest_rows = list(session.scalars(
        select(IntradaySectorFlow).where(
            IntradaySectorFlow.snapshot_time == latest_snapshot
        )
    ))

    by_type: dict[str, int] = {}
    for r in latest_rows:
        by_type[r.sector_type] = by_type.get(r.sector_type, 0) + 1

    industry_top = sorted(
        (r for r in latest_rows if r.sector_type == "industry"),
        key=lambda r: -r.main_inflow_wan_x10000,
    )[:10]

    concept_top = sorted(
        (r for r in latest_rows if r.sector_type == "concept"),
        key=lambda r: -r.main_inflow_wan_x10000,
    )[:10]

    return {
        "total_rows": total,
        "latest_snapshot_time": latest_snapshot,
        "latest_trade_date": latest_snapshot.date() if latest_snapshot else None,
        "by_type": by_type,
        "industry_top": industry_top,
        "concept_top": concept_top,
    }


def print_report(status: dict[str, Any]) -> None:
    if status["total_rows"] == 0:
        print("暂无盘中数据")
        return

    print("=" * 60)
    print("📊 intraday_sector_flow 状态")
    print("=" * 60)
    print(f"  总行数            : {status['total_rows']}")
    print(f"  最新 snapshot     : {status['latest_snapshot_time']}")
    print(f"  最新 trade_date   : {status['latest_trade_date']}")
    print()
    print("  最新 snapshot 各 sector_type:")
    for st in ("industry", "concept", "region"):
        cnt = status["by_type"].get(st, 0)
        print(f"    {st:<10} : {cnt}")
    print()

    print("  Top 10 industry:")
    if not status["industry_top"]:
        print("    (空)")
    for i, r in enumerate(status["industry_top"], 1):
        # 板块名截短到 16 字符,避免长名字撑爆终端
        name = r.sector_name[:16]
        print(
            f"    #{i:<2} {name:<16} "
            f"{_fmt_yi(r.main_inflow_wan_x10000):>10}  "
            f"{_fmt_pct(r.change_pct_x10000):>8}"
        )
    print()

    concept_count = status["by_type"].get("concept", 0)
    if concept_count == 0:
        print("  Top 10 concept: concept_count=0")
    else:
        print("  Top 10 concept:")
        for i, r in enumerate(status["concept_top"], 1):
            name = r.sector_name[:16]
            print(
                f"    #{i:<2} {name:<16} "
                f"{_fmt_yi(r.main_inflow_wan_x10000):>10}  "
                f"{_fmt_pct(r.change_pct_x10000):>8}"
            )
    print("=" * 60)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    with SessionLocal() as session:
        status = collect_status(session)
    print_report(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
