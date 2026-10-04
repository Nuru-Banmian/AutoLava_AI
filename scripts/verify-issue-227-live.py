"""Verify grouped charts through real local HTTP, SQLite, and a Chromium browser.

All accounts and records are disposable synthetic fixtures. Recorded weather is
written through the public ledger API; one old value is installed directly in
the disposable database to represent data predating the WMO write contract.
The unrelated upstream weather provider returns no data in this harness.
"""

from collections import defaultdict
from contextlib import closing
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
ARTIFACTS = ROOT / ".autolava-test" / "issue-227"
WEATHER = [
    "晴", "少云", "多云", "阴", "雾", "冻雾", "小毛毛雨", "毛毛雨", "大毛毛雨",
    "小冻毛毛雨", "冻毛毛雨", "小雨", "中雨", "大雨", "小冻雨", "冻雨", "小雪",
    "中雪", "大雪", "雪粒", "小阵雨", "阵雨", "大阵雨", "小阵雪", "大阵雪", "雷雨",
    "雷雨伴小冰雹", "雷雨伴大冰雹",
]
LEGACY = "旧版可控天气"


class RetriedTemporaryDirectory(tempfile.TemporaryDirectory):
    def cleanup(self) -> None:
        target = Path(self.name).resolve()
        if not target.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not target.name.startswith("autolava-issue-227-"):
            raise RuntimeError("Unsafe temporary cleanup target")
        for attempt in range(50):
            try:
                super().cleanup()
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.2)


def free_port() -> int:
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        return int(bound.getsockname()[1])


def wait_ready(process: subprocess.Popen, url: str) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f"Local service stopped before readiness: {url}")
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Local service did not become ready: {url}")


def expected(rows: list[dict]) -> dict:
    by_day: dict[int, list[int]] = defaultdict(list)
    by_weather: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row["status"] == "休息":
            continue
        by_day[date.fromisoformat(row["date"]).weekday()].append(row["amount"])
        label = row["weather"]
        group = "历史未规范天气" if label == LEGACY else label or "未记录"
        by_weather[group].append(row["amount"])

    def metric(values: list[int]) -> dict:
        mean = int((Decimal(sum(values)) / len(values)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return {"average_revenue": mean, "operating_day_count": len(values)}

    order = [label for label in WEATHER if label in by_weather]
    order += [label for label in ["历史未规范天气", "未记录"] if label in by_weather]
    return {
        "weekday": [{"weekday": day, **metric(values)} for day, values in sorted(by_day.items())],
        "weather": [{"weather": label, **metric(by_weather[label])} for label in order],
    }


def main(*, prepare=None, test_match="grouped-performance-live.spec.ts", artifacts=ARTIFACTS) -> None:
    ARTIFACTS = artifacts
    if not PYTHON.is_file():
        raise RuntimeError("backend/.venv/Scripts/python.exe is required")
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx is required")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen] = []
    opened_logs = []
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    with RetriedTemporaryDirectory(prefix="autolava-issue-227-") as temporary_name:
        temporary = Path(temporary_name).resolve()
        if not temporary.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("Unsafe temporary directory")
        database = temporary / "test.sqlite3"
        api_port, web_port = free_port(), free_port()
        username, password = "issue227" + secrets.token_hex(4), secrets.token_urlsafe(32)
        env = os.environ.copy()
        env.update(
            AUTOLAVA_ENVIRONMENT="development", AUTOLAVA_DATABASE_PATH=str(database),
            AUTOLAVA_BACKUP_DIRECTORY=str(temporary / "backups"),
            AUTOLAVA_BOOTSTRAP_USERNAME=username, AUTOLAVA_BOOTSTRAP_PASSWORD=password,
            AUTOLAVA_JWT_SECRET=secrets.token_urlsafe(48), AUTOLAVA_COOKIE_SECURE="false",
            AUTOLAVA_LIVE_BROWSER="1", AUTOLAVA_LIVE_USERNAME=username,
            AUTOLAVA_LIVE_PASSWORD=password, AUTOLAVA_GROUPS_ARTIFACTS=str(ARTIFACTS),
            PYTHONPATH=os.pathsep.join([str(temporary), str(BACKEND)]),
        )

        def run(args: list[str], cwd: Path) -> None:
            subprocess.run(args, cwd=cwd, env=env, check=True)

        def launch(args: list[str], cwd: Path, name: str) -> subprocess.Popen:
            stdout = (ARTIFACTS / f"{name}.out.log").open("wb")
            stderr = (ARTIFACTS / f"{name}.err.log").open("wb")
            opened_logs.extend([stdout, stderr])
            process = subprocess.Popen(args, cwd=cwd, env=env, stdout=stdout, stderr=stderr, creationflags=flags)
            processes.append(process)
            return process

        try:
            run([str(PYTHON), "-m", "alembic", "upgrade", "head"], BACKEND)
            run([str(PYTHON), "-m", "app.scripts.create_admin"], BACKEND)
            (temporary / "issue227_app.py").write_text(
                "from app.main import create_app\n"
                "class NoUpstreamWeather:\n"
                "    async def get_daily(self, store, target):\n"
                "        return None\n"
                "app = create_app(weather_service=NoUpstreamWeather())\n", encoding="utf-8",
            )
            api_base = f"http://127.0.0.1:{api_port}"
            api_process = launch([str(PYTHON), "-m", "uvicorn", "issue227_app:app", "--host", "127.0.0.1", "--port", str(api_port)], BACKEND, "api")
            wait_ready(api_process, api_base + "/health")
            opener = build_opener(HTTPCookieProcessor(CookieJar()))

            def api(method: str, path: str, data: dict | None = None) -> dict:
                body = json.dumps(data).encode() if data is not None else None
                request = Request(api_base + "/api" + path, data=body, method=method, headers={"Content-Type": "application/json"})
                try:
                    with opener.open(request, timeout=20) as response:
                        return json.load(response)
                except HTTPError as error:
                    raise RuntimeError(f"Fixture request {method} {path} failed ({error.code}): {error.read().decode()}") from error

            api("POST", "/auth/login", {"username": username, "password": password})
            stores = [api("POST", "/admin/stores", {"name": name, "address": "Synthetic validation address", "latitude": "45", "longitude": "9", "timezone": "Europe/Rome"}) for name in ["Issue 227 dense synthetic store", "Issue 227 sparse synthetic store"]]
            dense = [{"date": f"2026-07-{index + 1:02}", "amount": 0 if index == 2 else 101 + index * 11, "status": "提前休息" if index == 1 else "营业", "weather": weather} for index, weather in enumerate(WEATHER)]
            dense += [
                {"date": "2026-07-29", "amount": 102, "status": "营业", "weather": "晴"},
                {"date": "2026-07-30", "amount": 701, "status": "营业", "weather": LEGACY},
                {"date": "2026-07-31", "amount": 0, "status": "提前休息", "weather": None},
            ]
            june = [
                {"date": "2026-06-01", "amount": 303, "status": "营业", "weather": "晴"},
                {"date": "2026-06-02", "amount": 100, "status": "营业", "weather": "中雨"},
                {"date": "2026-06-04", "amount": 88, "status": "提前休息", "weather": LEGACY},
                {"date": "2026-06-05", "amount": 55, "status": "营业", "weather": None},
                {"date": "2026-06-06", "amount": 0, "status": "休息", "weather": "晴"},
            ]
            sparse = [
                {"date": "2026-06-01", "amount": 100, "status": "营业", "weather": "晴"},
                {"date": "2026-06-08", "amount": 101, "status": "营业", "weather": "晴"},
                {"date": "2026-06-02", "amount": 0, "status": "营业", "weather": "中雨"},
                {"date": "2026-06-03", "amount": 0, "status": "休息", "weather": "少云"},
                {"date": "2026-06-04", "amount": 202, "status": "提前休息", "weather": None},
                {"date": "2026-06-11", "amount": 203, "status": "提前休息", "weather": None},
                {"date": "2026-06-05", "amount": 155, "status": "营业", "weather": LEGACY},
            ]
            scopes = [{"store_id": stores[0]["id"], "month": "2026-07", "rows": dense}, {"store_id": stores[0]["id"], "month": "2026-06", "rows": june}, {"store_id": stores[1]["id"], "month": "2026-06", "rows": sparse}]
            for scope in scopes:
                store_id = scope["store_id"]
                config = api("GET", f"/income-config/{store_id}/current")
                for row in scope["rows"]:
                    api("PUT", f"/ledger/{store_id}/{row['date']}", {"expected_config_revision": config["revision"], "expected_identity": None, "expected_revision": None, "is_open": row["status"], "daily_revenue": row["amount"], "weather": "晴" if row["weather"] == LEGACY else row["weather"], "weather_edited": True})
                    if row["weather"] == LEGACY:
                        with closing(sqlite3.connect(database)) as connection:
                            connection.execute("UPDATE store_daily_records SET weather = ? WHERE store_id = ? AND date = ?", (LEGACY, store_id, row["date"]))
                            connection.commit()
                scope["expected"] = expected(scope["rows"])
                end_day = "31" if scope["month"] == "2026-07" else "30"
                actual = api("GET", f"/charts/{store_id}?start={scope['month']}-01&end={scope['month']}-{end_day}&bucket=day")
                for field in ["weekday", "weather"]:
                    sort_key = "weekday" if field == "weekday" else "weather"
                    assert sorted(actual[field], key=lambda row: row[sort_key]) == sorted(scope["expected"][field], key=lambda row: row[sort_key]), f"Independent public HTTP calculation differs: {scope['month']} {field}"
            extra = prepare(api, database) if prepare else {}
            manifest = {"stores": stores, "scopes": scopes, "weather_provider": "no-data synthetic provider; no supplier calls", **extra}
            manifest_path = ARTIFACTS / "fixture-and-http-evidence.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            env["AUTOLAVA_GROUPS_MANIFEST"] = str(manifest_path)
            runtime = ARTIFACTS / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            vite_config = runtime / "vite.config.mts"
            vite_config.write_text("import base from " + json.dumps((FRONTEND / "vite.config.ts").as_posix()) + ";\nimport { mergeConfig } from " + json.dumps((FRONTEND / "node_modules/vite/dist/node/index.js").as_posix()) + ";\nexport default mergeConfig(base, " + json.dumps({"root": str(FRONTEND), "server": {"proxy": {"/api": {"target": api_base, "changeOrigin": False}, "/health": {"target": api_base, "changeOrigin": False}}}}) + ");\n", encoding="utf-8")
            web_process = launch([npx, "vite", "--config", str(vite_config), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], FRONTEND, "vite")
            wait_ready(web_process, f"http://127.0.0.1:{web_port}/")
            playwright_config = runtime / "playwright.config.mts"
            playwright_config.write_text("import { defineConfig } from " + json.dumps((FRONTEND / "node_modules/@playwright/test/index.mjs").as_posix()) + ";\nexport default defineConfig(" + json.dumps({"testDir": str(FRONTEND / "tests"), "testMatch": test_match, "workers": 1, "timeout": 90000, "reporter": [["line"], ["json", {"outputFile": str(ARTIFACTS / "playwright-results.json")}]], "outputDir": str(ARTIFACTS / "browser-results"), "use": {"baseURL": f"http://127.0.0.1:{web_port}", "trace": "retain-on-failure"}}) + ");\n", encoding="utf-8")
            print("Independent public HTTP calculations passed for three synthetic scopes; running five-width real browser checks.", flush=True)
            run([npx, "playwright", "test", "--config", str(playwright_config)], FRONTEND)
            print(f"Live grouped chart validation passed. Evidence: {ARTIFACTS}", flush=True)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for log in opened_logs:
                log.close()


if __name__ == "__main__":
    main()
