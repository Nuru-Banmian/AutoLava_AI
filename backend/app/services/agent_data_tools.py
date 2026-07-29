from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import StoreDailyRecord
from app.services.access import require_fresh_store_access
from app.services.owner import is_administrator


class DataToolValidationError(ValueError):
    pass


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class DataToolContext:
    user_id: int
    store_id: int


def _whole_euro_average(total: int, count: int) -> str | None:
    if count == 0:
        return None
    return format(
        (Decimal(total) / Decimal(count)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        ),
        "f",
    )


class AgentDataToolRegistry:
    names = frozenset({"business_performance_summary"})

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: DataToolContext,
        result_id: str,
    ) -> dict[str, Any]:
        if name not in self.names:
            raise DataToolValidationError("未知的数据工具")
        if set(arguments) != {"start", "end"}:
            raise DataToolValidationError("经营表现汇总参数无效")
        try:
            start = date.fromisoformat(str(arguments["start"]))
            end = date.fromisoformat(str(arguments["end"]))
        except ValueError as exc:
            raise DataToolValidationError("日期格式无效") from exc
        if start > end:
            raise DataToolValidationError("开始日期不能晚于结束日期")
        if (end - start).days > 366:
            raise DataToolValidationError("日期范围不能超过 367 天")

        async with self._session_factory() as session:
            user, store = await require_fresh_store_access(
                session,
                user_id=context.user_id,
                store_id=context.store_id,
                capability="analytics.view",
            )
            if not is_administrator(user):
                raise DataToolValidationError("数据分析 Agent 仅限管理员")
            local_today = date.today()
            try:
                from datetime import datetime

                local_today = datetime.now(ZoneInfo(store.timezone)).date()
            except (KeyError, ValueError):
                pass
            if end > local_today:
                raise DataToolValidationError("结束日期不能晚于门店本地日期")
            records = list(
                await session.scalars(
                    select(StoreDailyRecord)
                    .where(
                        StoreDailyRecord.store_id == context.store_id,
                        StoreDailyRecord.date.between(start, end),
                    )
                    .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
                )
            )

        operating = [
            record
            for record in records
            if record.is_open in {"营业", "提前休息"}
        ]
        ledger_revenue = sum(record.daily_revenue for record in records)
        operating_revenue = sum(record.daily_revenue for record in operating)
        wash_records = (
            [
                record
                for record in operating
                if record.wash_count is not None
            ]
            if store.wash_count_enabled
            else []
        )
        wash_count = (
            sum(record.wash_count or 0 for record in wash_records)
            if wash_records
            else None
        )
        wash_revenue = sum(record.daily_revenue for record in wash_records)
        average_per_wash = (
            _whole_euro_average(wash_revenue, wash_count)
            if wash_count is not None and wash_count > 0
            else None
        )
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "ledger_revenue": str(ledger_revenue),
                "operating_days": len(operating),
                "operating_day_average_ledger_revenue": (
                    _whole_euro_average(operating_revenue, len(operating))
                ),
                "wash_count": (
                    str(wash_count) if wash_count is not None else None
                ),
                "average_revenue_per_wash": average_per_wash,
            },
            "coverage": {
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "matching_records": len(records),
                "operating_days": len(operating),
                "missing_wash_count_days": (
                    len(operating) - len(wash_records)
                ),
                "truncated": False,
            },
        }
