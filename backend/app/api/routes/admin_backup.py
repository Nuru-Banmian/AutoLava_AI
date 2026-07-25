import asyncio
import shutil
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import require_final_admin
from app.core.config import get_settings
from app.services.sqlite_backup import create_verified_snapshot

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_final_admin)],
)


class _SnapshotFileResponse(FileResponse):
    def __init__(self, path: Path, *, cleanup_directory: Path, **kwargs: Any):
        super().__init__(path, **kwargs)
        self.cleanup_directory = cleanup_directory

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            shutil.rmtree(self.cleanup_directory, ignore_errors=True)


@router.get("/database-backup")
async def download_database_backup() -> FileResponse:
    settings = get_settings()
    filename = f"autolava-backup-{datetime.now(UTC):%Y%m%d-%H%M%S}.sqlite3"
    temporary_directory = Path(tempfile.mkdtemp(prefix="autolava-backup-"))
    snapshot = temporary_directory / filename
    snapshot_task = asyncio.create_task(
        asyncio.to_thread(
            create_verified_snapshot,
            settings.database_path,
            snapshot,
        )
    )
    try:
        await asyncio.shield(snapshot_task)
        return _SnapshotFileResponse(
            snapshot,
            cleanup_directory=temporary_directory,
            media_type="application/vnd.sqlite3",
            filename=filename,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except asyncio.CancelledError:
        with suppress(Exception):
            await snapshot_task
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise HTTPException(500, "Database backup could not be prepared") from error
