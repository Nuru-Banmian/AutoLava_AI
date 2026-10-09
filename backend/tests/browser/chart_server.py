"""Isolated real HTTP/SSE browser fixture, with a controlled query/chat model."""
import asyncio
import os
import tempfile
from pathlib import Path

import uvicorn

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel
from tests.api.test_agent_chat_charts import trend_query, trend
from tests.api.test_agent_tools import save_day


class BrowserModel(QueryModel):
    def __init__(self):
        super().__init__([])

    async def stream_tools(self, messages, tools):
        import json
        from uuid import uuid4
        from app.agents.providers.bailian import ToolCall
        self.results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        latest = self.results[-1]
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if latest.get("skill"):
            action = "store_data_catalog", {}
        elif "domains" in latest:
            action = trend_query()(self)
        elif "targets" in latest:
            if "不用图" in question:
                yield "本期19，零值与未知日期分开解释。"
                return
            action = trend(self)
        else:
            yield "本期19，零值保留；未统计与未录入处断线。"
            return
        yield ToolCall(uuid4().hex, action[0], json.dumps(action[1]))


async def main():
    os.environ["AUTOLAVA_AGENT_CONTEXT_CHARS"] = "64000"
    with tempfile.TemporaryDirectory(prefix="autolava-266-browser-") as directory:
        async with chat_app(Path(directory), BrowserModel()) as (client, app, _):
            await save_day(client, "2026-07-01", 19)
            await save_day(client, "2026-07-02", 0)
            await save_day(client, "2026-07-03", None, "未统计")
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8066, lifespan="off"))
            await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
