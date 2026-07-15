from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.income_config import IncomeConfigVersion


@dataclass(frozen=True)
class RetentionResult:
    ledger_snapshots_pruned: int
    config_versions_pruned: int


class RetentionService:
    LEDGER_MAX_SNAPSHOTS = 10
    LEDGER_MAX_AGE = timedelta(days=365)
    CONFIG_MAX_VERSIONS = 20
    CONFIG_MAX_AGE = timedelta(days=180)

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    async def prune(self, *, now: datetime) -> RetentionResult:
        pruning_time = self._naive_utc(now)
        ledger_cutoff = pruning_time - self.LEDGER_MAX_AGE
        config_cutoff = pruning_time - self.CONFIG_MAX_AGE

        ledger_rows = list(
            await self.session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.operation_domain == "ledger",
                    AuditLog.snapshot_expires_at.is_(None),
                    or_(
                        AuditLog.rollbackable.is_(True),
                        AuditLog.before_json.is_not(None),
                        AuditLog.after_json.is_not(None),
                    ),
                )
                .order_by(
                    AuditLog.record_id,
                    AuditLog.created_at.desc(),
                    AuditLog.id.desc(),
                )
            )
        )
        positions: dict[int | None, int] = {}
        ledger_pruned = 0
        for row in ledger_rows:
            position = positions.get(row.record_id, 0)
            positions[row.record_id] = position + 1
            if position < self.LEDGER_MAX_SNAPSHOTS and row.created_at >= ledger_cutoff:
                continue
            row.before_json = None
            row.after_json = None
            row.rollbackable = False
            row.snapshot_expires_at = pruning_time
            ledger_pruned += 1

        versions = list(
            await self.session.scalars(
                select(IncomeConfigVersion).order_by(
                    IncomeConfigVersion.store_id,
                    IncomeConfigVersion.version.desc(),
                    IncomeConfigVersion.id.desc(),
                )
            )
        )
        version_positions: dict[int, int] = {}
        config_pruned = 0
        for version in versions:
            position = version_positions.get(version.store_id, 0)
            version_positions[version.store_id] = position + 1
            is_latest = position == 0
            is_excess = position >= self.CONFIG_MAX_VERSIONS
            is_expired = version.created_at < config_cutoff
            if is_latest or not (is_excess or is_expired):
                continue
            await self.session.delete(version)
            config_pruned += 1

        await self.session.flush()
        return RetentionResult(
            ledger_snapshots_pruned=ledger_pruned,
            config_versions_pruned=config_pruned,
        )
