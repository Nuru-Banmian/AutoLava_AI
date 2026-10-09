"""Disposable migrated HTTP/SSE server for Issue 268 real-browser acceptance."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn

from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_chat_charts import trend, trend_query
from tests.api.test_agent_saved_charts import SavedModel
from tests.api.test_agent_tools import save_day


class BrowserSavedModel(SavedModel):
    def __init__(self):
        super().__init__([])

    async def stream_tools(self, messages, tools):
        self.results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        latest = self.results[-1]
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if latest.get("source") == "saved_chart":
            yield "依据旧图首日19，原查询时间见来源说明。"
            return
        if latest.get("skill") and "旧图" in question:
            description = next(m["content"].split("历史图描述：")[-1] for m in reversed(messages)
                               if isinstance(m.get("content"), str) and "历史图描述：" in m["content"])
            chart = json.loads(description)
            action = "store_chart", {"operation": "read_saved", "message_id": chart["message_id"], "chart_id": chart["chart_id"]}
        elif latest.get("skill"):
            action = "store_data_catalog", {}
        elif "domains" in latest:
            action = trend_query()(self)
        elif "targets" in latest:
            action = trend(self)
        else:
            yield "营业额19，真实零保留，未统计和未录入为空。"
            return
        yield ToolCall(uuid4().hex, action[0], json.dumps(action[1]))


async def main():
    os.environ["AUTOLAVA_AGENT_CONTEXT_CHARS"] = "64000"
    from app.core.config import get_settings
    get_settings.cache_clear()
    with tempfile.TemporaryDirectory(prefix="autolava-268-browser-") as directory:
        async with chat_app(Path(directory), BrowserSavedModel()) as (client, app, _):
            await save_day(client, "2026-07-01", 19)
            await save_day(client, "2026-07-02", 0)
            await save_day(client, "2026-07-03", None, "未统计")
            await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8068, lifespan="off")).serve()


if __name__ == "__main__":
    asyncio.run(main())
