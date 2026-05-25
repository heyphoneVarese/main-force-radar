"""基金 ↔ 板块映射 service。

给定 fund_code,通过 funds.related_sectors 的中文标签 join sector_aliases
反查出所有有效的 eastmoney 板块代码(BKxxxx)。
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, SectorAlias

logger = logging.getLogger(__name__)


def get_sectors_for_fund(session: Session, fund_code: str) -> list[str]:
    """返回该基金关联的 eastmoney sector_code 列表。

    流程:fund_code → funds.related_sectors(中文标签数组) → sector_aliases
    → 仅保留 sector_code 不为 NULL 的项 → 返回去重后的 BK 代码列表。

    无关联 / 无 fund / 标签全部无映射 → 返回空列表。
    """
    fund = session.get(Fund, fund_code)
    if fund is None:
        logger.debug("get_sectors_for_fund: fund %s not found", fund_code)
        return []
    labels = fund.related_sectors or []
    if not labels:
        return []

    aliases = session.scalars(
        select(SectorAlias).where(SectorAlias.chinese_label.in_(labels))
    ).all()

    # 仅返回有 sector_code 的(NULL 表示明确无 BK 对应,如指数/海外)
    codes = [a.sector_code for a in aliases if a.sector_code]
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def get_unmapped_labels(session: Session) -> list[str]:
    """诊断函数:返回所有出现在某只 fund.related_sectors 中、
    但在 sector_aliases 表里完全没记录的中文标签(用于补 alias)。
    注意:有记录但 sector_code=NULL 的不算「未映射」(已显式标记无对应)。
    """
    funds = session.scalars(select(Fund)).all()
    used_labels: set[str] = set()
    for f in funds:
        for lbl in f.related_sectors or []:
            used_labels.add(lbl)

    known = set(session.scalars(select(SectorAlias.chinese_label)).all())
    return sorted(used_labels - known)


def coverage_report(session: Session) -> dict:
    """返回 52 只基金的板块映射覆盖率报告。"""
    funds = session.scalars(select(Fund)).all()
    total = len(funds)
    mapped = 0
    unmapped_funds: list[tuple[str, str, list[str]]] = []
    for f in funds:
        codes = get_sectors_for_fund(session, f.fund_code)
        if codes:
            mapped += 1
        else:
            unmapped_funds.append(
                (f.fund_code, f.fund_name, list(f.related_sectors or []))
            )
    return {
        "total": total,
        "mapped": mapped,
        "unmapped_count": total - mapped,
        "coverage_pct": round(100 * mapped / total, 1) if total else 0.0,
        "unmapped_funds": unmapped_funds,
        "unmapped_labels": get_unmapped_labels(session),
    }
