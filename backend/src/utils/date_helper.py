from datetime import date, datetime
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")


def cn_now() -> datetime:
    """Asia/Shanghai 时区下的 naive datetime。所有 created_at / updated_at 的默认值。"""
    return datetime.now(CN_TZ).replace(tzinfo=None)


def cn_today() -> date:
    return cn_now().date()
