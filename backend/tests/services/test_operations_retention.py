from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.operations import ScheduledTaskLog, SystemAlert, UTC_TIMESTAMP_CONTRACT
from app.services.operations_retention import prune_operational_rows


def _task_log(created_at: datetime, *, label: str) -> ScheduledTaskLog:
    return ScheduledTaskLog(
        store_id=None,
        task_type=label,
        status="success",
        message=label,
        retry_count=0,
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        timestamp_contract=UTC_TIMESTAMP_CONTRACT,
    )


def _alert(
    created_at: datetime,
    *,
    label: str,
    resolved_at: datetime | None,
) -> SystemAlert:
    return SystemAlert(
        store_id=None,
        alert_type=label,
        level="warning",
        message=label,
        is_resolved=resolved_at is not None,
        created_at=created_at,
        resolved_at=resolved_at,
        timestamp_contract=UTC_TIMESTAMP_CONTRACT,
    )


async def test_prune_operational_rows_uses_strict_seven_day_cutoff(db_session) -> None:
    now = datetime(2026, 7, 19, 12)
    cutoff = now - timedelta(days=7)
    db_session.add_all(
        [
            _task_log(cutoff - timedelta(seconds=1), label="expired-task"),
            _task_log(cutoff, label="boundary-task"),
            _task_log(cutoff + timedelta(seconds=1), label="recent-task"),
            _alert(
                cutoff - timedelta(days=30),
                label="unresolved-old",
                resolved_at=None,
            ),
            _alert(
                cutoff - timedelta(seconds=1),
                label="resolved-expired",
                resolved_at=cutoff - timedelta(seconds=1),
            ),
            _alert(
                cutoff,
                label="resolved-boundary",
                resolved_at=cutoff,
            ),
        ]
    )
    await db_session.flush()

    result = await prune_operational_rows(db_session, now)
    await db_session.flush()

    task_types = set(await db_session.scalars(select(ScheduledTaskLog.task_type)))
    alert_types = set(await db_session.scalars(select(SystemAlert.alert_type)))
    assert result.task_logs_deleted == 1
    assert result.resolved_alerts_deleted == 1
    assert task_types == {"boundary-task", "recent-task"}
    assert alert_types == {"unresolved-old", "resolved-boundary"}
