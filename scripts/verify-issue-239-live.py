"""Run store description browser acceptance against disposable migrated SQLite and real HTTP."""

import json
import os
from pathlib import Path
import runpy
import secrets
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / ".autolava-test" / "issue-239"


def main():
    helpers = runpy.run_path(str(ROOT / "scripts" / "verify-issue-227-live.py"))
    python = helpers["PYTHON"]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx is None or not python.is_file():
        raise RuntimeError("Existing backend virtualenv and npx are required")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    processes, logs = [], []
    with tempfile.TemporaryDirectory(prefix="autolava-issue-239-") as temporary_name:
        temporary = Path(temporary_name).resolve()
        if (not temporary.is_relative_to(Path(tempfile.gettempdir()).resolve())
                or not temporary.name.startswith("autolava-issue-239-")):
            raise RuntimeError("Unsafe temporary cleanup target")
        api_port, web_port = helpers["free_port"](), helpers["free_port"]()
        api_base, web_base = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
        environment = os.environ | {
            "AUTOLAVA_ENVIRONMENT": "development",
            "AUTOLAVA_DATABASE_PATH": str(temporary / "test.sqlite3"),
            "AUTOLAVA_BACKUP_DIRECTORY": str(temporary / "backups"),
            "AUTOLAVA_BOOTSTRAP_USERNAME": "issue239" + secrets.token_hex(4),
            "AUTOLAVA_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(32),
            "AUTOLAVA_JWT_SECRET": secrets.token_urlsafe(48), "AUTOLAVA_COOKIE_SECURE": "false",
            "AUTOLAVA_DESCRIPTION_LIVE": "1", "AUTOLAVA_DESCRIPTION_ARTIFACTS": str(ARTIFACTS),
            "PYTHONPATH": os.pathsep.join([str(temporary), str(BACKEND)]),
        }
        environment["AUTOLAVA_LIVE_USERNAME"] = environment["AUTOLAVA_BOOTSTRAP_USERNAME"]
        environment["AUTOLAVA_LIVE_PASSWORD"] = environment["AUTOLAVA_BOOTSTRAP_PASSWORD"]

        def run(args, cwd):
            subprocess.run(args, cwd=cwd, env=environment, check=True)

        def launch(args, cwd, name):
            stdout = (ARTIFACTS / f"{name}.out.log").open("wb")
            stderr = (ARTIFACTS / f"{name}.err.log").open("wb")
            logs.extend([stdout, stderr])
            process = subprocess.Popen(args, cwd=cwd, env=environment, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            processes.append(process)
            return process

        try:
            run([str(python), "-m", "alembic", "upgrade", "head"], BACKEND)
            run([str(python), "-m", "app.scripts.create_admin"], BACKEND)
            (temporary / "description_app.py").write_text(
                "from app.main import create_app\n"
                "class NoUpstreamWeather:\n"
                "    async def get_daily(self, store, target): return None\n"
                "    async def timezone(self, latitude, longitude): return 'Europe/Rome'\n"
                "app = create_app(weather_service=NoUpstreamWeather())\n"
                "app.state.open_meteo_provider = NoUpstreamWeather()\n", encoding="utf-8",
            )
            api = launch([str(python), "-m", "uvicorn", "description_app:app", "--host", "127.0.0.1",
                          "--port", str(api_port)], BACKEND, "api")
            helpers["wait_ready"](api, api_base + "/health")
            runtime = ARTIFACTS / "runtime"
            runtime.mkdir(exist_ok=True)
            vite_config = runtime / "vite.config.mts"
            vite_config.write_text(
                "import base from " + json.dumps((FRONTEND / "vite.config.ts").as_posix()) + ";\n"
                "import { mergeConfig } from " + json.dumps((FRONTEND / "node_modules/vite/dist/node/index.js").as_posix()) + ";\n"
                "export default mergeConfig(base, " + json.dumps({"root": str(FRONTEND), "server": {
                    "proxy": {"/api": {"target": api_base}, "/health": {"target": api_base}}}}) + ");\n",
                encoding="utf-8",
            )
            web = launch([npx, "vite", "--config", str(vite_config), "--host", "127.0.0.1",
                          "--port", str(web_port), "--strictPort"], FRONTEND, "vite")
            helpers["wait_ready"](web, web_base)
            config = runtime / "playwright.config.mts"
            config.write_text(
                "import { defineConfig } from " + json.dumps((FRONTEND / "node_modules/@playwright/test/index.mjs").as_posix()) + ";\n"
                "export default defineConfig(" + json.dumps({
                    "testDir": str(FRONTEND / "tests"), "testMatch": "store-description-live.spec.ts",
                    "workers": 1, "timeout": 60000,
                    "reporter": [["line"], ["json", {"outputFile": str(ARTIFACTS / "playwright-results.json")}]],
                    "outputDir": str(ARTIFACTS / "browser-results"),
                    "use": {"baseURL": web_base, "trace": "retain-on-failure"},
                }) + ");\n", encoding="utf-8",
            )
            run([npx, "playwright", "test", "--config", str(config)], FRONTEND)
            print(f"Store description live validation passed. Evidence: {ARTIFACTS}", flush=True)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        process.terminate()
                    process.wait(timeout=10)
            for log in logs:
                log.close()


if __name__ == "__main__":
    main()
