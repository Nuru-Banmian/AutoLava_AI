"""Bound actual concurrent password calculations, including cancelled callers."""

import asyncio
from collections.abc import Callable
from typing import TypeVar

from app.core.security import hash_password, verify_password

T = TypeVar("T")
PASSWORD_WORK_LIMIT = 4
_password_slots = asyncio.Semaphore(PASSWORD_WORK_LIMIT)


def _finish_password_work(task: asyncio.Task[T]) -> None:
    _password_slots.release()
    # A caller may have been cancelled while the worker was running.
    if not task.cancelled():
        task.exception()


async def _run_password_work(function: Callable[..., T], *args: str) -> T:
    await _password_slots.acquire()
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    # Cancellation of a caller does not end its thread. Keep its slot occupied.
    task.add_done_callback(_finish_password_work)
    return await asyncio.shield(task)


async def hash_password_async(password: str) -> str:
    return await _run_password_work(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await _run_password_work(verify_password, password, password_hash)
