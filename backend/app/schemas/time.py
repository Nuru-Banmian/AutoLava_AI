from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Expose UTC-naive database timestamps as explicit UTC API values."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
