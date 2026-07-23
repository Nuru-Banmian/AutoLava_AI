import asyncio
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.deps import require_final_admin
from app.core.config import get_settings
from app.services.sqlite_backup import create_verified_snapshot

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_final_admin)],
)


@router.get("/database-backup")
async def download_database_backup() -> FileResponse:
    settings = get_settings()
    filename = f"autolava-backup-{datetime.now(UTC):%Y%m%d-%H%M%S}.sqlite3"
    temporary_directory = Path(tempfile.mkdtemp(prefix="autolava-backup-"))
    snapshot = temporary_directory / filename
    try:
        await asyncio.to_thread(
            create_verified_snapshot,
            settings.database_path,
            snapshot,
        )
        return FileResponse(
            snapshot,
            media_type="application/vnd.sqlite3",
            filename=filename,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            background=BackgroundTask(
                shutil.rmtree,
                temporary_directory,
                ignore_errors=True,
            ),
        )
    except Exception as error:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise HTTPException(500, "Database backup could not be prepared") from error
