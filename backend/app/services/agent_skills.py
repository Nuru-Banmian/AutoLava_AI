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
        "- 经营日只包括营业和提前休息。\n"
        "- 经营日均台账营业额按经营日计算。\n"
        "- 平均每车收入只使用同时记录有效洗车数量的经营日，且不包含公司结算收入。\n"
        "- 金额平均值使用 ROUND_HALF_UP 舍入到整数欧元。\n"
        "- 需要派生数值时使用 calculate，不要心算。\n"
        "- 最终回答必须说明重要的数据覆盖限制。"
    ),
    allowed_data_tools=frozenset({"business_performance_summary"}),
)


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
