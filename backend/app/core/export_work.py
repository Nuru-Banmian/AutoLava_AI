"""Bound workbook construction even when an HTTP caller disconnects."""

import asyncio

from app.services.export import build_ledger_workbook

EXPORT_WORK_LIMIT = 4
_export_slots = asyncio.Semaphore(EXPORT_WORK_LIMIT)


def _finish_export(task: asyncio.Task[bytes]) -> None:
    _export_slots.release()
    if not task.cancelled():
        task.exception()


async def build_ledger_workbook_async(
    records: list[dict], *, include_wash_count: bool
) -> bytes:
    await _export_slots.acquire()
    task = asyncio.create_task(
        asyncio.to_thread(
            build_ledger_workbook, records, include_wash_count=include_wash_count
        )
    )
    task.add_done_callback(_finish_export)
    return await asyncio.shield(task)
