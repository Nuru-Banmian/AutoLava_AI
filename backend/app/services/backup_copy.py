"""Copy a completed SQLite snapshot to a separately operated SSH host."""

import hashlib
import logging
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.sqlite_backup import _valid_backup


_SAFE_ACCOUNT = re.compile(r"^[A-Za-z0-9._-]+$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SshBackupDestination:
    host: str
    user: str
    directory: str
    key_file: Path
    known_hosts_file: Path

    def __post_init__(self) -> None:
        if not _SAFE_ACCOUNT.fullmatch(self.host) or not _SAFE_ACCOUNT.fullmatch(self.user):
            raise ValueError("Invalid backup SSH host or user")
        if not self.directory.startswith("/") or "\n" in self.directory:
            raise ValueError("Backup SSH directory must be absolute")
        if not self.key_file.is_file() or not self.known_hosts_file.is_file():
            raise ValueError("Backup SSH credentials or host keys are missing")


def copy_verified_snapshot(snapshot: Path, destination: SshBackupDestination) -> str:
    """Promote only a remotely verified upload; never expose a partial final file."""
    if not _valid_backup(snapshot, require_schema=True):
        raise ValueError("Only completed, verified SQLite snapshots may be copied")
    with snapshot.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    remote = f"{destination.user}@{destination.host}"
    options = [
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=10",
        "-o", f"UserKnownHostsFile={destination.known_hosts_file}",
        "-i", str(destination.key_file),
    ]
    final = f"{destination.directory.rstrip('/')}/{snapshot.name}"
    temporary = f"{final}.upload-{uuid.uuid4().hex}"
    quoted_temp = shlex.quote(temporary)
    try:
        with snapshot.open("rb") as source:
            subprocess.run(
                ["ssh", *options, remote, f"cat > {quoted_temp}"],
                stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, timeout=300,
            )
        result = subprocess.run(
            ["ssh", *options, remote, f"sha256sum {quoted_temp}"],
            capture_output=True, check=True, timeout=30,
        )
        if result.stdout.decode("ascii").split()[0] != digest:
            raise ValueError("Copied snapshot checksum mismatch")
        subprocess.run(
            ["ssh", *options, remote, f"mv -f {quoted_temp} {shlex.quote(final)}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30,
        )
    except BaseException:
        try:
            subprocess.run(
                ["ssh", *options, remote, f"rm -f {quoted_temp}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30,
            )
        except Exception as cleanup_error:
            logger.error("task=sqlite_backup_copy_cleanup result=failed error_type=%s", type(cleanup_error).__name__)
        raise
    return digest
