"""删除 intraday_sector_flow 中指定 snapshot_time 的所有记录(PR18)。

跑法(backend 目录下):
    uv run python scripts/clear_intraday_snapshot.py \\
        --snapshot-time "2026-06-01 14:30:00"

Docker 上:
    docker compose exec backend uv run --no-dev python -m \\
        scripts.clear_intraday_snapshot --snapshot-time "2026-06-01 14:30:00"

安全设计:
- --snapshot-time 必填,没有默认值(不能误删整张表)
- snapshot_time 解析后 .replace(second=0, microsecond=0) — 跟 intraday_fetcher
  入库逻辑对齐,避免精度问题(实际存的就是分钟精度)
- 接受 ISO 格式("YYYY-MM-DD HH:MM:SS" / "YYYY-MM-DD HH:MM" / 带 T 分隔符)
- 没有匹配 → 打印 0,正常退出 0,不报错
- 只删 intraday_sector_flow,不动 sector_flow_daily / market_index_daily 等

典型用途:
- 手动测试时写入了假 snapshot(例:`fetch_and_store_intraday` 传
  datetime(2026, 6, 1, 14, 30) 验证管道),用完清掉避免污染前端展示
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from src.db import SessionLocal
from src.models import IntradaySectorFlow

logger = logging.getLogger(__name__)


def _parse_snapshot_time(s: str) -> datetime:
    """ISO 'YYYY-MM-DD HH:MM[:SS]' / 'YYYY-MM-DDTHH:MM[:SS]'。"""
    try:
        return datetime.fromisoformat(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"invalid snapshot_time {s!r}: expected ISO 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS'"
        ) from e


def run(session: Session, snapshot_time: datetime) -> dict[str, Any]:
    """删除该 snapshot_time 下所有行。返回 stats(便于单测)。

    snapshot_time 入参不强制 minute-aligned;函数内 .replace(second=0,
    microsecond=0) 跟入库逻辑对齐 — 即使用户传 "14:30:47" 也按 14:30 删。
    """
    canonical = snapshot_time.replace(second=0, microsecond=0)
    deleted_count = (
        session.query(IntradaySectorFlow)
        .filter_by(snapshot_time=canonical)
        .delete(synchronize_session=False)
    )
    session.commit()
    return {
        "snapshot_time": canonical.isoformat(),
        "deleted_count": deleted_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete all intraday_sector_flow rows at the given snapshot_time. "
            "Required: --snapshot-time. Idempotent: missing snapshot → 0 deleted."
        ),
    )
    parser.add_argument(
        "--snapshot-time",
        required=True,
        type=_parse_snapshot_time,
        metavar="ISO_DATETIME",
        help=(
            "snapshot_time to delete (Asia/Shanghai naive); "
            "examples: '2026-06-01 14:30:00' / '2026-06-01 14:30' / "
            "'2026-06-01T14:30:00'. Auto-truncated to minute precision."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    with SessionLocal() as session:
        result = run(session, args.snapshot_time)

    print("=" * 60)
    print("🧹 clear_intraday_snapshot 完成:")
    print(f"  snapshot_time : {result['snapshot_time']}")
    print(f"  deleted_count : {result['deleted_count']}")
    print("=" * 60)
    if result["deleted_count"] == 0:
        print("(没匹配的 snapshot,什么也没删)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
