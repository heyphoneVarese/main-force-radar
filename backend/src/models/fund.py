from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.utils.date_helper import cn_now


class Fund(Base):
    __tablename__ = "funds"

    fund_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    fund_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fund_type: Mapped[str] = mapped_column(String(20), nullable=False)
    company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manager: Mapped[str | None] = mapped_column(String(50), nullable=True)
    establish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tracking_target: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Phase 2.5a 新增:基金 → 关注板块映射(JSON 字符串数组,如 ["BK0428"])
    related_sectors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=cn_now, onupdate=cn_now
    )


class Holding(Base):
    """我的持仓。R1 整数:cost_nav_x10000, shares_x100。D2: 聚合,1 基金 1 行。"""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(
        String(10), ForeignKey("funds.fund_code"), unique=True, nullable=False
    )
    cost_nav_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shares_x100: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Phase 2.5a 新增:建仓日(NOT NULL)
    bought_at: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=cn_now, onupdate=cn_now
    )


class FundNavDaily(Base):
    """基金每日净值快照。R2 入库后永不依赖外部回查。"""

    __tablename__ = "fund_nav_daily"
    __table_args__ = (Index("idx_fund_nav_trade_date", "trade_date"),)

    fund_code: Mapped[str] = mapped_column(
        String(10), ForeignKey("funds.fund_code"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    unit_nav_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accum_nav_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_return_x10000: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)
