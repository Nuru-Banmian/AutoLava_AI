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

SKILL_TOOL_AUTHORIZATIONS = {
    "business_performance": frozenset(
        {
            "business_performance_summary",
            "daily_ledger_detail",
            "income_composition",
            "ledger_revenue_trend",
        }
    ),
}


class SkillCatalog:
    def __init__(
        self,
        data_tool_names: frozenset[str],
        *,
        skills: tuple[DataSkill, ...] = (BUSINESS_PERFORMANCE,),
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
