from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.utils.date_helper import cn_now


class SectorAlias(Base):
    """中文板块标签 → eastmoney 板块代码的映射。

    用途:
    - funds.related_sectors 存的是用户视角的中文语义标签(如 'CPO' / '半导体')
    - 本表把这些标签映射到 eastmoney 行业/概念板块代码(如 'BK1144')
    - Phase 2.7 信号引擎可以:fund → labels → BK 代码 → sector_flow_daily

    note:
    - sector_code 可以为 NULL,表示"该标签没有对应 eastmoney 行业板块"
      (如 '沪深300' 是市场指数,'纳指100' 是海外指数,'债券' 是另一资产类)
    - confidence ∈ [0.0, 1.0],值越高映射越可信。0.0 表示明确无对应
    - chinese_label 加 UNIQUE 约束,1 个标签对应 1 个 BK(Phase 2.6 简化)
    """

    __tablename__ = "sector_aliases"
    __table_args__ = (Index("idx_sector_aliases_label", "chinese_label"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chinese_label: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    sector_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sector_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=cn_now, onupdate=cn_now
    )
