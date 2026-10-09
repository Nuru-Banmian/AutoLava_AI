"""Display precision shared by business analytics and projected Agent queries."""

from decimal import ROUND_HALF_UP, Decimal


def rounded_average(total: int, count: int) -> int:
    """Round an average to integer euros; callers decide zero-denominator availability."""
    if count == 0:
        return 0
    return int((Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rounded_percent(numerator: int | float, denominator: int | float) -> float | None:
    """Return a percentage rounded to two decimals, or None for a zero denominator."""
    if denominator == 0:
        return None
    return float(
        (Decimal(str(numerator)) * 100 / Decimal(str(denominator)))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
