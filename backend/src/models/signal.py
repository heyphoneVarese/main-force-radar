from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.utils.date_helper import cn_now


class Signal(Base):
    """信号记录。R3.1: signal_type 取值仅 bullish/bearish/warning/neutral/not_applicable,
    严禁 buy/sell/long/short/hold。

    Phase 2.7 新增字段(nullable,兼容旧记录):
    - persistence_score (0-9, int) : 持续性总分,见 services/signal_engine.py
    - main_inflow_wan_x10000       : 触发日主力净流入,万元 × 10000(R1)
    - triggered_at                  : 信号触发时刻(与 created_at 区分:created_at 是入库时刻)
    """

    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_date_target", "trade_date", "target_type", "target_code"),
        Index("idx_signals_date_type", "trade_date", "signal_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signal_name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    score_x100: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)

    # Phase 2.7 新增
    persistence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_inflow_wan_x10000: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
