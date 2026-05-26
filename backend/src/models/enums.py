"""信号/推送等枚举值。

R3.1: signal_type 严禁 buy / sell / long / short / hold 词汇。
DB 层用 VARCHAR 存,Python 层用 StrEnum 校验,跨 SQLite / PostgreSQL 行为一致。
"""

from enum import StrEnum


class SignalType(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    WARNING = "warning"
    NEUTRAL = "neutral"
    NOT_APPLICABLE = "not_applicable"  # 基金未映射到 A 股板块(QDII / 指数 / 债基)


class TargetType(StrEnum):
    FUND = "fund"
    SECTOR = "sector"
    MARKET = "market"


class SectorType(StrEnum):
    INDUSTRY = "industry"
    CONCEPT = "concept"
    REGION = "region"


class PushType(StrEnum):
    MORNING = "morning"
    MIDDAY = "midday"
    EVENING = "evening"
    WEEKLY = "weekly"


class PushChannel(StrEnum):
    SERVERCHAN = "serverchan"


class PushStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
