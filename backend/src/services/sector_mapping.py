"""基金 ↔ 板块映射 service。

给定 fund_code,通过 funds.related_sectors 的中文标签 join sector_aliases
反查出所有有效的 eastmoney 板块代码(BKxxxx)。
"""

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, SectorAlias

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 0.7
MappingStatus = Literal["verified", "low_confidence", "unmapped", "not_applicable"]


@dataclass(frozen=True)
class FundSectorMapping:
    """One fund label resolved through sector_aliases.

    status:
      verified       : has sector_code and confidence >= threshold
      low_confidence : has sector_code but confidence < threshold
      not_applicable : alias exists with sector_code NULL
      unmapped       : label has no alias row, or fund/labels are missing
    """

    label: str
    sector_code: str | None
    sector_name: str | None
    confidence: float | None
    status: MappingStatus
    source: str

    @property
    def eligible_for_sorting(self) -> bool:
        return self.status == "verified" and self.sector_code is not None


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


def resolve_fund_sector_mappings(
    session: Session,
    fund_code: str,
    *,
    min_confidence: float = HIGH_CONFIDENCE_THRESHOLD,
) -> list[FundSectorMapping]:
    """Resolve fund.related_sectors through sector_aliases.

    This is the unified mapping entry for dashboard fund/holding/radar views.
    Only mappings with status="verified" are allowed to drive ranking.
    Low-confidence mappings are returned for display/diagnostics, but must not
    influence "strongest/candidate" sorting.
    """
    fund = session.get(Fund, fund_code)
    if fund is None:
        logger.debug("resolve_fund_sector_mappings: fund %s not found", fund_code)
        return [
            FundSectorMapping(
                label="",
                sector_code=None,
                sector_name=None,
                confidence=None,
                status="unmapped",
                source="fund_missing",
            )
        ]

    labels = [str(lbl).strip() for lbl in (fund.related_sectors or []) if str(lbl).strip()]
    if not labels:
        return [
            FundSectorMapping(
                label="",
                sector_code=None,
                sector_name=None,
                confidence=None,
                status="not_applicable",
                source="fund.related_sectors",
            )
        ]

    aliases = {
        a.chinese_label: a
        for a in session.scalars(
            select(SectorAlias).where(SectorAlias.chinese_label.in_(labels))
        )
    }

    mappings: list[FundSectorMapping] = []
    for label in labels:
        alias = aliases.get(label)
        if alias is None:
            mappings.append(
                FundSectorMapping(
                    label=label,
                    sector_code=None,
                    sector_name=None,
                    confidence=None,
                    status="unmapped",
                    source="sector_aliases",
                )
            )
            continue

        if alias.sector_code is None:
            status: MappingStatus = "not_applicable"
        elif alias.confidence >= min_confidence:
            status = "verified"
        else:
            status = "low_confidence"

        mappings.append(
            FundSectorMapping(
                label=label,
                sector_code=alias.sector_code,
                sector_name=alias.sector_name,
                confidence=alias.confidence,
                status=status,
                source="sector_aliases",
            )
        )

    return mappings


def mapping_status_for_fund(mappings: list[FundSectorMapping]) -> MappingStatus:
    """Collapse per-label mappings to a single fund-level status."""
    statuses = {m.status for m in mappings}
    if "verified" in statuses:
        return "verified"
    if "low_confidence" in statuses:
        return "low_confidence"
    if statuses and statuses <= {"not_applicable"}:
        return "not_applicable"
    return "unmapped"


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
