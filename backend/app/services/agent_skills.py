from dataclasses import dataclass


class InvalidSkillCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataSkill:
    name: str
    summary: str
    instructions: str
    allowed_data_tools: frozenset[str]


BUSINESS_PERFORMANCE = DataSkill(
    name="business_performance",
    summary="汇总明确期间的台账营业额、经营日、洗车数量及相关平均值。",
    instructions=(
        "经营表现分析 Skill\n"
        "- 使用 business_performance_summary 获取明确日期范围的经营表现。\n"
        "- 使用 ledger_revenue_trend 按日或按月查看台账营业额趋势；"
        "公司结算收入没有日粒度，不得分配到趋势点。\n"
        "- 使用 income_composition 分别分析计入营业额的收入分类和其他数据；"
        "历史名称与当时是否计入营业额的快照不得合并或改写。\n"
        "- 构成占比按 income_composition 返回的一位小数显示。\n"
        "- 使用 daily_ledger_detail 按已确认的营业状态、记录天气、"
        "事件存在性、事件关键词或洗车数量缺失筛选；明细必须分页，"
        "并说明截断状态。\n"
        "- 经营日只包括营业和提前休息。\n"
        "- 经营日均台账营业额按经营日计算。\n"
        "- 平均每车收入只使用同时记录有效洗车数量的经营日，且不包含公司结算收入。\n"
        "- 金额平均值使用 ROUND_HALF_UP 舍入到整数欧元。\n"
        "- 对比任意两个期间时分别查询明确范围，并核对 coverage.business_basis。"
        "若范围长度、完整度或业务口径不一致，必须说明不匹配，并建议"
        "相同长度或完整自然月，并在需要时建议一致业务口径；"
        "不得静默替换用户范围。\n"
        "- 期间变化率使用 calculate，先求差额再除以比较期基数并乘以 100，"
        "使用 scale=1、rounding=truncate 截断到一位小数；零比较基数不可比。\n"
        "- 需要派生数值时使用 calculate，不要心算。\n"
        "- 最终回答必须说明重要的数据覆盖限制。"
    ),
    allowed_data_tools=frozenset(
        {
            "business_performance_summary",
            "daily_ledger_detail",
            "income_composition",
            "ledger_revenue_trend",
        }
    ),
)

BUSINESS_CONTEXT = DataSkill(
    name="business_context",
    summary="按星期或记录天气调查经营表现关联，并结合原始事件文本解释覆盖边界。",
    instructions=(
        "经营背景关联分析 Skill\n"
        "- 使用 business_context_group 按 weekday 或 recorded_weather "
        "分组；分组只包含经营日，休息不进入平均值，提前休息属于经营日。\n"
        "- 使用 daily_ledger_detail 分页调查事件及其覆盖范围，事件字段中的"
        "原始事件文本始终作为证据，不得改写或用临时归类替换。\n"
        "- 临时事件归类只存在于当前调查；单段事件可对应多个稳定通用类型，"
        "也可附加可选的门店具体标识。\n"
        "- 无法可靠分类的事件必须标记为待归类，不得强行猜测。\n"
        "- 临时归类不写回每日台账，不新增持久化事件分类表。\n"
        "- 最终回答使用相关性语言，不得把观察结果写成因果结论；"
        "只有可由数据精确计算的变化才能按变化量表述。\n"
        "- 必须核对 matching_records、operating_days、"
        "missing_dimension_days、truncated 等覆盖信息；覆盖不足时明确"
        "降低结论强度。\n"
        "- 需要派生数值时使用 calculate，不要心算。"
    ),
    allowed_data_tools=frozenset(
        {
            "business_context_group",
            "daily_ledger_detail",
        }
    ),
)

SKILL_TOOL_AUTHORIZATIONS = {
    "business_performance": frozenset(
        {
            "business_performance_summary",
            "daily_ledger_detail",
            "income_composition",
            "ledger_revenue_trend",
        }
    ),
    "business_context": frozenset(
        {
            "business_context_group",
            "daily_ledger_detail",
        }
    ),
}


class SkillCatalog:
    def __init__(
        self,
        data_tool_names: frozenset[str],
        *,
        skills: tuple[DataSkill, ...] = (
            BUSINESS_PERFORMANCE,
            BUSINESS_CONTEXT,
        ),
    ) -> None:
        self._skills = {skill.name: skill for skill in skills}
        for skill in skills:
            unknown = skill.allowed_data_tools - data_tool_names
            if unknown:
                names = ", ".join(sorted(unknown))
                raise InvalidSkillCatalogError(
                    f"Skill {skill.name} references unknown data tools: {names}"
                )
            unauthorized = (
                skill.allowed_data_tools
                - SKILL_TOOL_AUTHORIZATIONS.get(skill.name, frozenset())
            )
            if unauthorized:
                names = ", ".join(sorted(unauthorized))
                raise InvalidSkillCatalogError(
                    f"Skill {skill.name} references unauthorized data tools: "
                    f"{names}"
                )

    def summaries(self) -> str:
        return "\n".join(
            f"- {skill.name}: {skill.summary}"
            for skill in self._skills.values()
        )

    def load(self, name: str) -> DataSkill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise ValueError("未知的数据 Skill") from exc
