from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.utils.date_helper import cn_now


class SectorFlowDaily(Base):
    """板块资金流(每日)。核心数据源,每天采集。"""

    __tablename__ = "sector_flow_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "sector_code", name="uq_sector_flow_date_code"),
        Index("idx_sector_flow_date", "trade_date"),
        Index("idx_sector_flow_date_type", "trade_date", "sector_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    sector_code: Mapped[str] = mapped_column(String(20), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(50), nullable=False)
    sector_type: Mapped[str] = mapped_column(String(20), nullable=False)  # industry/concept/region
    main_inflow_wan_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    main_inflow_pct_x10000: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_pct_x10000: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)


class MarketIndexDaily(Base):
    """市场指数日线(上证综指 / 深证成指 / 创业板指 / 沪深 300 等)。"""

    __tablename__ = "market_index_daily"
    __table_args__ = (
        UniqueConstraint("index_code", "trade_date", name="uq_market_index_code_date"),
        Index("idx_market_index_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(String(20), nullable=False)
    index_name: Mapped[str] = mapped_column(String(50), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_pct_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    turnover_wan_x10000: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)
