from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import ScheduledTaskLog, SystemAlert


@dataclass(frozen=True)
class OperationalRetentionResult:
    task_logs_deleted: int
    resolved_alerts_deleted: int


async def prune_operational_rows(
    session: AsyncSession, now: datetime
) -> OperationalRetentionResult:
    cutoff = now - timedelta(days=7)
    task_logs = await session.execute(
        delete(ScheduledTaskLog).where(ScheduledTaskLog.created_at < cutoff)
    )
    resolved_alerts = await session.execute(
        delete(SystemAlert).where(
            SystemAlert.is_resolved.is_(True),
            SystemAlert.resolved_at.is_not(None),
            SystemAlert.resolved_at < cutoff,
        )
    )
    return OperationalRetentionResult(
        task_logs_deleted=task_logs.rowcount or 0,
        resolved_alerts_deleted=resolved_alerts.rowcount or 0,
    )
