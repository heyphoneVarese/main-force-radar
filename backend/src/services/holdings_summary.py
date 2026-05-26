"""持仓 → 板块映射辅助函数(从 scripts/test_push.py 提取出来共用)。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding
from src.services.sector_mapping import get_sectors_for_fund


def build_holdings_by_sector(session: Session) -> dict[str, list[tuple[str, str]]]:
    """sector_code → [(fund_code, fund_name), ...]

    一个持仓基金可以映射到多个 sector(funds.related_sectors 有多个标签时),
    所以一只基金可能在多个 sector_code 的列表里都出现。
    """
    out: dict[str, list[tuple[str, str]]] = {}
    holdings = session.scalars(select(Holding)).all()
    for h in holdings:
        fund = session.get(Fund, h.fund_code)
        if fund is None:
            continue
        for sector_code in get_sectors_for_fund(session, h.fund_code):
            out.setdefault(sector_code, []).append((h.fund_code, fund.fund_name))
    return out
