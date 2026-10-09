"""Real HTTP server on a migrated disposable database, with external I/O substitutes."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

USERNAME = "ci-owner"
PASSWORD = "ci-acceptance-password"


class ScriptedModel:
    """Speak the model protocol; tool execution and persistence remain production code.

    Receipts are echoed, never synthesized, so tests can observe actual query/calculation
    results through the public chat API. No database or production service imports here.
    """

    model_name = "acceptance-script"

    @staticmethod
    def call(name, arguments):
        from app.agents.providers.bailian import ToolCall

        return ToolCall(uuid4().hex, name, json.dumps(arguments))

    async def stream_plan(self, messages, schemas):
        yield self.call("plan_response", {"kind": "query", "queries": []})

    async def stream_tools(self, messages, schemas):
        question = next(message["content"] for message in reversed(messages)
                        if message["role"] == "user")
        if "模拟模型失败" in question:
            from app.agents.providers.bailian import ModelFailure

            raise ModelFailure("model_unavailable")
        receipts = {}
        names = {}
        for message in messages:
            if message.get("tool_calls"):
                names = {call["id"]: call["function"]["name"]
                         for call in message["tool_calls"]}
            elif message["role"] == "tool":
                receipts[names[message["tool_call_id"]]] = json.loads(message["content"])
        if "store_data_catalog" not in receipts:
            yield self.call("store_data_catalog", {})
        elif "store_query" not in receipts:
            yield self.call("store_query", {
                "catalog_version": receipts["store_data_catalog"]["catalog_version"],
                "targets": [{"id": "daily", "domain": "daily_ledger",
                             "range": {"start": "2025-01-01", "end": "2025-01-04"},
                             "metrics": ["total_revenue"], "group_by": ["day"]}],
            })
        elif "calculate" not in receipts:
            yield self.call("calculate", {"expression": "0.1 + 0.2"})
        elif "store_chart" not in receipts:
            yield self.call("store_chart", {
                "operation": "create",
                "result_ref": receipts["store_query"]["targets"][0]["result_ref"],
                "dimension": "day", "series": ["total_revenue"],
                "type": "line", "title": "验收营业额",
            })
        else:
            if "等待重置" in question:
                yield "等待重置信号"
                await asyncio.sleep(30)  # Reset must cancel this external wait.
            yield "验收结果：" + json.dumps({
                "query": receipts["store_query"], "calculation": receipts["calculate"],
            }, ensure_ascii=False)


class OfflineWeather:
    async def get_daily(self, store, record_date):
        return None


def configure(data_dir):
    # Ignore inherited secrets and .env files before importing database/app modules.
    for key in list(os.environ):
        if key.startswith("AUTOLAVA_"):
            del os.environ[key]
    os.environ.update({
        "AUTOLAVA_DATABASE_PATH": str(data_dir / "acceptance.sqlite3"),
        "AUTOLAVA_JWT_SECRET": "acceptance-only-secret-with-at-least-32-bytes",
        "AUTOLAVA_BOOTSTRAP_USERNAME": USERNAME,
    })
    from app.core.config import Settings

    Settings.model_config["env_file"] = None


async def seed_owner():
    from app.core.database import async_session_factory, engine
    from app.scripts.create_admin import create_admin

    async with async_session_factory() as session, session.begin():
        assert await create_admin(session, USERNAME, PASSWORD)
    await engine.dispose()


def serve(data_dir, port):
    from alembic import command
    from alembic.config import Config
    import uvicorn

    configure(data_dir)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    asyncio.run(seed_owner())
    from app.main import create_app

    uvicorn.run(create_app(agent_model=ScriptedModel(), weather_service=OfflineWeather()),
                host="127.0.0.1", port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.data_dir:
        if not args.data_dir.is_dir() or any(args.data_dir.iterdir()):
            parser.error("--data-dir must be an existing empty disposable directory")
        serve(args.data_dir.resolve(), args.port)
    else:
        with TemporaryDirectory(prefix="autolava-acceptance-") as directory:
            serve(Path(directory), args.port)


if __name__ == "__main__":
    main()
