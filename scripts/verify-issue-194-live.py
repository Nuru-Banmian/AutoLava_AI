"""Run the settlement browser flow against a disposable migrated SQLite database."""

from pathlib import Path
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"


def run(args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main() -> None:
    if not PYTHON.is_file():
        raise RuntimeError("backend/.venv/Scripts/python.exe is required")
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx is required")

    temporary = tempfile.TemporaryDirectory(prefix="autolava-issue-194-")
    directory = Path(temporary.name).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not directory.is_relative_to(temp_root) or not directory.name.startswith("autolava-issue-194-"):
        raise RuntimeError("Unsafe temporary directory")

    process: subprocess.Popen[bytes] | None = None
    try:
        env = os.environ.copy()
        username = "issue194" + str(secrets.randbelow(900000) + 100000)
        password = secrets.token_urlsafe(32)
        env.update(
            AUTOLAVA_DATABASE_PATH=str(directory / "test.sqlite3"),
            AUTOLAVA_BACKUP_DIRECTORY=str(directory / "backups"),
            AUTOLAVA_BOOTSTRAP_USERNAME=username,
            AUTOLAVA_BOOTSTRAP_PASSWORD=password,
            AUTOLAVA_JWT_SECRET=secrets.token_urlsafe(48),
            AUTOLAVA_COOKIE_SECURE="false",
            AUTOLAVA_LIVE_BROWSER="1",
            AUTOLAVA_LIVE_USERNAME=username,
            AUTOLAVA_LIVE_PASSWORD=password,
        )
        run([str(PYTHON), "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env)
        run([str(PYTHON), "-m", "app.scripts.create_admin"], cwd=BACKEND, env=env)

        with (directory / "api.out").open("wb") as stdout, (directory / "api.err").open("wb") as stderr:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(
                [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=BACKEND,
                env=env,
                stdout=stdout,
                stderr=stderr,
                creationflags=flags,
            )
            for _ in range(80):
                if process.poll() is not None:
                    raise RuntimeError("Temporary API stopped during startup")
                try:
                    with urlopen("http://127.0.0.1:8000/health", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Temporary API did not become ready")

            run([npx, "playwright", "test", "tests/company-settlement-live.spec.ts", "--reporter=line"], cwd=FRONTEND, env=env)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        temporary.cleanup()


if __name__ == "__main__":
    main()
