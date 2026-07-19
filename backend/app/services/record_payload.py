from typing import Any

from app.models.ledger import StoreDailyRecord


def record_payload(record: StoreDailyRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "store_id": record.store_id,
        "date": record.date.isoformat(),
        "daily_revenue": record.daily_revenue,
        "income_mode": record.income_mode,
        "wash_count": record.wash_count,
        "is_open": record.is_open,
        "weather": record.weather,
        "weather_auto": record.weather_auto,
        "weather_code": record.weather_code,
        "temperature_max": record.temperature_max,
        "temperature_min": record.temperature_min,
        "precipitation": record.precipitation,
        "activity": record.activity,
        "weather_edited": record.weather_edited,
        "scanned": record.scanned,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "items": [
            {
                "id": item.id,
                "category_id": item.category_id,
                "category_name": item.category_name,
                "include_in_total": item.include_in_total,
                "sort_order": item.sort_order,
                "amount": item.amount,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in sorted(record.items, key=lambda value: (value.sort_order, value.id))
        ],
    }
