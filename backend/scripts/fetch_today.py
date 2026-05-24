"""手动触发今日数据采集 + 入库。

用法(在 backend/ 目录下):
    uv run python -m scripts.fetch_today

当前阶段(Phase 1 第 3 步)跑 2 类:
- 行业资金流 → sector_flow_daily(目前在 dev 环境因 eastmoney 接口报错暂跑不通,
  等大陆 VPS 部署后即可生效;代码 + 单元测试已就位)
- 大盘指数   → market_index_daily(sina 数据源)

其他 fetcher(概念流 / 基金净值 / 基金重仓)在 data_fetcher.py 已实现,
本脚本不触发,等 Phase 2 持仓功能上线后再加入。

北向资金已从需求中移除(港交所政策变化,实时数据停发)。

幂等:同 (trade_date, sector_code) / (index_code, trade_date) 已存在时跳过。
"""

import logging

from src.db import SessionLocal
from src.models import MarketIndexDaily, SectorFlowDaily
from src.services.data_fetcher import (
    fetch_market_index,
    fetch_sector_flow_industry,
)

logger = logging.getLogger(__name__)

DEFAULT_INDICES: list[tuple[str, str]] = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000300", "沪深300"),
]


def insert_sector_flow_rows(session, rows: list[dict]) -> int:
    inserted = 0
    for row in rows:
        exists = (
            session.query(SectorFlowDaily)
            .filter_by(trade_date=row["trade_date"], sector_code=row["sector_code"])
            .first()
        )
        if exists:
            continue
        session.add(SectorFlowDaily(**row))
        inserted += 1
    session.commit()
    return inserted


def insert_market_index_rows(
    session, rows: list[dict], index_name: str | None = None
) -> int:
    inserted = 0
    for row in rows:
        if index_name:
            row["index_name"] = index_name
        exists = (
            session.query(MarketIndexDaily)
            .filter_by(index_code=row["index_code"], trade_date=row["trade_date"])
            .first()
        )
        if exists:
            continue
        session.add(MarketIndexDaily(**row))
        inserted += 1
    session.commit()
    return inserted


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    with SessionLocal() as session:
        rows = fetch_sector_flow_industry()
        n = insert_sector_flow_rows(session, rows)
        logger.info("sector_flow_daily (industry): fetched=%d inserted=%d", len(rows), n)

        for code, name in DEFAULT_INDICES:
            rows = fetch_market_index(code)
            n = insert_market_index_rows(session, rows, index_name=name)
            logger.info(
                "market_index_daily [%s/%s]: fetched=%d inserted=%d",
                code,
                name,
                len(rows),
                n,
            )

    logger.info("fetch_today done")


if __name__ == "__main__":
    main()
