import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from acceptance.server import PASSWORD, USERNAME


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter and any(reporter.stats.get(kind) for kind in ("skipped", "xfailed", "xpassed")):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    directory = tmp_path_factory.mktemp("acceptance")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}/api"
    with (directory / "server.log").open("w", encoding="utf-8") as log:
        database = directory / "database"
        database.mkdir()
        process = subprocess.Popen(
            [sys.executable, "-m", "acceptance.server", "--port", str(port),
             "--data-dir", str(database)],
            cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("Acceptance server exited: " +
                                (directory / "server.log").read_text(encoding="utf-8"))
                try:
                    if httpx.get(url + "/auth/me", timeout=1, trust_env=False).status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Acceptance server did not start within 30 seconds")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            server_log = (directory / "server.log").read_text(encoding="utf-8")
            assert not any(marker in server_log for marker in (
                "ERROR [", "Traceback (most recent call last)",
            )), server_log


@pytest.fixture
def owner(base_url):
    with httpx.Client(base_url=base_url + "/", timeout=15, trust_env=False) as client:
        response = client.post("auth/login", json={"username": USERNAME, "password": PASSWORD})
        assert response.status_code == 200, response.text
        yield client
