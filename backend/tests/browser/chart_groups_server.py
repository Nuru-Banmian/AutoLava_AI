"""Ticket 267 browser server: real tools, HTTP/SSE and migrated disposable SQLite."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn

from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_chart_groups import chart, composition_query, long_query, seed_composition
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import save_day


class BrowserGroupsModel(QueryModel):
    def __init__(self):
        super().__init__([])

    async def stream_tools(self, messages, tools):
        self.results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        latest = self.results[-1]
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if "构成" in question:
            request = composition_query()
            creation = chart(type="stacked_bar", dimension="month", series=["amount"], series_by="category", title="收入构成")
        elif "排名" in question:
            request = query([{"id": "rank", "domain": "daily_ledger",
                "range": {"start": "2026-07-01", "end": "2026-08-31"},
                "fields": ["date", "daily_revenue"], "top_n": 3,
                "order_by": [{"field": "daily_revenue", "direction": "desc"}]}])
            creation = chart(type="horizontal_bar", dimension="date", series=["daily_revenue"], title="最高三天")
        elif "比较" in question:
            request = query([{"id": "compare", "domain": "monthly_income",
                "range": {"start": "2026-07-01", "end": "2026-08-31"},
                "metrics": ["daily_ledger_revenue", "confirmed_settlement_income", "total_wash_count"],
                "group_by": ["month"]}])
            creation = chart(type="grouped_bar", dimension="month",
                series=["daily_ledger_revenue", "confirmed_settlement_income", "total_wash_count"], title="月度比较")
        else:
            request = long_query()
            creation = chart(title="完整长趋势")
        if latest.get("skill"):
            action = "store_data_catalog", {}
        elif "domains" in latest:
            action = request(self)
        elif "targets" in latest or ("超量" in question and sum(r.get("status") == "prepared" for r in self.results) < 3 and not latest.get("error")):
            action = creation(self)
        else:
            yield "图表请求已处理，成功图随回复保存。"
            return
        yield ToolCall(uuid4().hex, action[0], json.dumps(action[1]))


async def main():
    os.environ["AUTOLAVA_AGENT_CONTEXT_CHARS"] = "64000"
    with tempfile.TemporaryDirectory(prefix="autolava-267-browser-") as directory:
        async with chat_app(Path(directory), BrowserGroupsModel()) as (client, app, _):
            await save_day(client, "2024-01-01", 19)
            await save_day(client, "2026-07-04", 99)
            await seed_composition(client)
            await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8067, lifespan="off")).serve()


if __name__ == "__main__":
    asyncio.run(main())
