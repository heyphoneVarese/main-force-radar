"""push_log.write_push_log 测试。"""

from src.models import PushLog
from src.models.enums import PushChannel, PushStatus
from src.services.push_log import write_push_log


def test_write_success_log_sets_status_and_clears_error(db_session):
    log = write_push_log(
        db_session, push_type="morning", title="t", content="c", success=True
    )
    assert log.id is not None
    assert log.status == PushStatus.SUCCESS.value
    assert log.error is None
    assert log.channel == PushChannel.SERVERCHAN.value
    assert log.pushed_at is not None


def test_write_failure_log_persists_error_message(db_session):
    log = write_push_log(
        db_session,
        push_type="weekly",
        title="t",
        content="c",
        success=False,
        error="HTTP 500: Server酱 挂了",
    )
    assert log.status == PushStatus.FAILED.value
    assert log.error == "HTTP 500: Server酱 挂了"


def test_write_failure_log_drops_error_when_success_true(db_session):
    """success=True 时,即便传了 error 也不保存(语义一致性)。"""
    log = write_push_log(
        db_session, push_type="midday", title="t", content="c",
        success=True, error="不应保留",
    )
    assert log.error is None


def test_write_log_persists_to_db(db_session):
    write_push_log(
        db_session, push_type="evening", title="title", content="body", success=True,
    )
    # 直接查表
    rows = db_session.query(PushLog).filter_by(push_type="evening").all()
    assert len(rows) == 1
    assert rows[0].title == "title"
