from datetime import UTC, datetime

from app.models.operations import UTC_TIMESTAMP_CONTRACT


def timestamp_status(contract: str) -> str:
    return "utc" if contract == UTC_TIMESTAMP_CONTRACT else "legacy_unknown"


def trusted_utc(value: datetime | None, contract: str) -> datetime | None:
    """Expose a value only when its persisted source contract proves UTC semantics."""
    if contract != UTC_TIMESTAMP_CONTRACT:
        return None
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
