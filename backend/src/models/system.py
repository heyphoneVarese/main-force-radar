from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.utils.date_helper import cn_now


class PushLog(Base):
    """推送日志。每次微信/Server酱 推送都落一行。"""

    __tablename__ = "push_logs"
    __table_args__ = (Index("idx_push_logs_type_time", "push_type", "pushed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    push_type: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pushed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=cn_now)


class UserConfig(Base):
    """KV 配置。预期 key:alert_thresholds / focus_sectors / push_schedule_overrides。"""

    __tablename__ = "user_config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=cn_now, onupdate=cn_now
    )
