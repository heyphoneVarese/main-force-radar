"""push_logs 表入库 helper (Phase 3.11)。

每次 scheduler 触发推送 → 写一行。便于 VPS 上排查"昨天几点推送了什么",
也是 Phase 4 前端「推送历史」页面的数据源。
"""

import logging

from sqlalchemy.orm import Session

from src.models import PushLog
from src.models.enums import PushChannel, PushStatus
from src.utils.date_helper import cn_now

logger = logging.getLogger(__name__)


def write_push_log(
    session: Session,
    push_type: str,
    title: str,
    content: str,
    success: bool,
    error: str | None = None,
    channel: str = PushChannel.SERVERCHAN.value,
) -> PushLog:
    """写一条推送日志,commit 并返回。失败时 error 字段写原因。"""
    log = PushLog(
        push_type=push_type,
        channel=channel,
        title=title,
        content=content,
        status=PushStatus.SUCCESS.value if success else PushStatus.FAILED.value,
        error=error if not success else None,
        pushed_at=cn_now(),
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    logger.info(
        "push_log written: push_type=%s status=%s id=%s",
        push_type, log.status, log.id,
    )
    return log
