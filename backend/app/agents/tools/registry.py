from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.skills.loader import SkillError
from app.agents.tools.calculate import CalculateInput, calculate
from app.agents.tools.store_chart import ChartInput, store_chart
from app.agents.tools.store_catalog import CatalogInput, store_data_catalog
from app.agents.tools.store_query import QueryInput, store_query
from app.agents.tools.store_overview import OverviewInput, store_overview


class SkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str = Field(min_length=1, max_length=64)


class ResourceInput(SkillInput):
    path: str = Field(min_length=1, max_length=240)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    execute: Callable

    def schema(self):
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.arguments.model_json_schema(),
        }}


class ToolRegistry:
    def __init__(self, definitions):
        self.tools = {}
        for tool in definitions:
            if tool.name in self.tools:
                raise ValueError(f"Duplicate tool: {tool.name}")
            self.tools[tool.name] = tool

    def bind(self, enabled):
        if len(set(enabled)) != len(enabled):
            raise ValueError("Duplicate enabled tool")
        missing = set(enabled) - self.tools.keys()
        if missing:
            raise ValueError(f"Unknown enabled tools: {sorted(missing)}")
        return BoundTools({name: self.tools[name] for name in enabled})


class BoundTools:
    def __init__(self, tools):
        self.tools = tools

    @property
    def schemas(self):
        return [tool.schema() for name, tool in self.tools.items()
                if name != "store_overview" or "store_query" not in self.tools]

    async def execute(self, call, storage, context):
        # All tools (including skill reads) share fresh authorization and generation fencing.
        async with storage.sessions() as session:
            run = await storage.authorize_run(session, context.scope, context.run_id)
            if run.generation != context.generation:
                raise RuntimeError("Tool context generation mismatch")
            tool = self.tools.get(call.name)
            if tool is None:
                return {"error": "tool_not_authorized"}
            try:
                arguments = tool.arguments.model_validate_json(call.arguments)
            except ValidationError:
                return {"error": "invalid_tool_arguments", "message": "Use the advertised JSON schema"}
            try:
                result = await tool.execute(session, context, arguments)
            except SkillError:
                result = {"error": "skill_resource_denied"}
        # Fresh session avoids authorizing against an ORM snapshot after an external wait.
        async with storage.sessions() as session:
            await storage.authorize_run(session, context.scope, context.run_id)
        return result


def default_registry(skills):
    async def read_skill(session, context, args):
        return {"skill": args.skill, "body": skills.body(args.skill)}

    async def read_resource(session, context, args):
        return {"skill": args.skill, "path": args.path,
                "body": skills.resource(args.skill, args.path)}

    return ToolRegistry([
        Tool("store_chart", "从本轮完整result_ref快照生成折线图草稿（不是当前页）；只选block、时间维度及同单位系列，不传数值。随最终回复保存，失败不能宣称生成。", ChartInput, store_chart),
        Tool("store_data_catalog", "发现当前授权门店已上线受控数据，参数为空；有效目录可跨轮复用。", CatalogInput, store_data_catalog),
        Tool("store_query", "批量只读查询或continuations续页至多6目标；完整行默认50/最多200，未读须说明部分完成；目录失效新查询整批不执行。", QueryInput, store_query),
        Tool("calculate", "临时十进制四则运算（正负号、小数、括号）；只传expression。"
             "结果为字符串，exact=false须说明有限表示，error不能当成功。"
             "经营工具已计算的指标不重算，计算照常计入工具预算。",
             CalculateInput, calculate),
        Tool("store_overview", "只读查询当前授权门店1至366天经营概览，返回范围、覆盖及指标口径。",
             OverviewInput, store_overview),
        Tool("read_skill", "按需读取已启用技能正文，技能不会扩大工具权限。", SkillInput, read_skill),
        Tool("read_skill_resource", "按需读取已启用技能的相对文本参考资料，不能执行脚本。",
             ResourceInput, read_resource),
    ])
