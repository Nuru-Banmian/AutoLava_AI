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
                if isinstance(arguments, ChartInput):
                    arguments = arguments.root
            except ValidationError as exc:
                message = "Use the advertised JSON schema"
                if call.name == "store_query":
                    message += ("; new queries require catalog_version and targets, each with a unique "
                                "id and domain plus fields OR metrics. targets must be a JSON array, "
                                "not a JSON-encoded string. Correct arguments and retry before answering. Pagination is unavailable; request a smaller date range.")
                    if any(error["loc"] == ("targets",) and error["type"] == "list_type"
                           for error in exc.errors(include_input=False)):
                        message += (
                            ' targets形状错误：必须直接传数组，不能传带引号的JSON文本。示例结构：'
                            '{"catalog_version":"使用当前目录版本","targets":[{"id":"day",'
                            '"domain":"daily_ledger","range":{"start":"2026-06-20",'
                            '"end":"2026-06-20"},"fields":["date","is_open","daily_revenue"]}]}。'
                            '请按用户日期重建对象数组；不连续日期可分别使用独立目标，重试成功前不回答数值。')
                return {"error": "invalid_tool_arguments", "message": message}
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
        Tool("store_chart", "create须result_ref/dimension/series/type/title；用本轮store_query完整快照制图，不传值。图表追问重新查询最新数据，复用近期日期/指标/分组；缺信息先追问。旧图保留查看。图型/容量依技能；prepared随回复保存。", ChartInput, store_chart),
        Tool("store_data_catalog", "发现当前授权门店已上线受控数据，参数为空；有效目录可跨轮复用。", CatalogInput, store_data_catalog),
        Tool("store_query", "批量只读查询至多6目标；月/年先汇总、周趋势按天，细问再拆分；单次明细最多200完整行，容量不足如实说明并缩小范围新查；不支持续页。", QueryInput, store_query),
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
