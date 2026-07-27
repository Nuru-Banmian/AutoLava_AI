from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemKnowledgeEntry:
    """One reviewed, packaged source in the physically bounded knowledge space."""

    id: str
    title: str
    content: str
    keywords: tuple[str, ...]
    why_patterns: tuple[str, ...]


# This tuple is the source boundary. Search never accepts a path, URL, database
# handle, or runtime file reader, so sources outside this reviewed package cannot
# enter the model context.
APPROVED_SYSTEM_KNOWLEDGE: tuple[SystemKnowledgeEntry, ...] = (
    SystemKnowledgeEntry(
        id="product.daily-ledger",
        title="每日台账",
        content=(
            "每日台账用于记录选定日期的营业状态、经营金额，以及可选的洗车数量、"
            "记录天气和事件。营业状态只能是营业、休息或提前休息。"
        ),
        keywords=("每日台账", "记账", "营业状态", "洗车数量", "记录天气", "事件"),
        why_patterns=(
            r"(?:要)?记录(?:营业状态|经营金额|洗车数量|天气|事件)",
        ),
    ),
    SystemKnowledgeEntry(
        id="product.business-records",
        title="营业记录筛选视图",
        content=(
            "营业记录视图用于按受控月份范围查看已有每日台账。Agent 只能准备打开"
            "已注册视图和设置受控筛选；页面切换本身不会创建、修改或删除经营数据。"
        ),
        keywords=("营业记录", "筛选", "月份", "查看记录", "界面导航"),
        why_patterns=(
            r"(?:要)?按月份范围查看",
            r"(?:要)?使用受控筛选",
            r"(?:是)?只读(?:视图)?",
        ),
    ),
    SystemKnowledgeEntry(
        id="domain.operating-day",
        title="经营日",
        content=(
            "营业或提前休息属于经营日，休息不属于经营日。经营日均台账营业额"
            "使用经营日数量作为分母，并且不包含公司结算收入。"
        ),
        keywords=("经营日", "提前休息", "经营日均台账营业额"),
        why_patterns=(
            r"不包括休息日",
            r"提前休息属于经营日",
            r"使用经营日数量作为分母",
        ),
    ),
    SystemKnowledgeEntry(
        id="capability.agent",
        title="Agent 能力边界",
        content=(
            "Agent 可以解释 AutoLava 产品和操作、调查当前门店的经营证据，并连接到"
            "批准的只读页面或筛选视图。它不是通用助手，也不能执行经营写入、任意网址"
            "跳转、导入导出或完整备份下载。"
        ),
        keywords=("Agent", "能力", "AutoLava", "帮助", "只读", "导航"),
        why_patterns=(
            r"(?:是)?只读(?:能力)?",
            r"(?:只)?调查当前门店",
            r"不是通用助手",
        ),
    ),
    SystemKnowledgeEntry(
        id="product.company-settlement",
        title="公司结算",
        content=(
            "公司结算用于登记结算公司的开票记录并跟踪整笔到账。已确认金额按开票月份"
            "计入月度总收入；关闭功能后不能继续操作，但历史已确认金额仍保留在分析中。"
        ),
        keywords=("公司结算", "结算公司", "开票记录", "到账确认", "月度总收入"),
        why_patterns=(
            r"(?:要)?按开票月份计入",
            r"(?:要)?到账确认",
            r"计入月度总收入",
        ),
    ),
)

_TOKEN = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)
_TERM_NORMALIZER = re.compile(r"[\s“”\"'《》【】（）()，,。.!！?？:：;；]+")
_HELP_AFTER_TERM = re.compile(
    r"^.{0,12}(?:怎么用|如何使用|怎么操作|如何操作|是什么|什么意思|"
    r"有哪些功能|有什么功能|在哪里|哪里可以|能否|是否|会不会|"
    r"会.{0,12}吗|可以.{0,12}吗|如何查看|如何记录|如何设置|如何筛选)"
)
_HELP_BEFORE_TERM = re.compile(
    r"(?:介绍|说明|解释|怎么用|如何使用|怎么操作|如何操作|帮助我了解)\s*$"
)


def search_system_knowledge(query: str, *, limit: int = 4) -> list[SystemKnowledgeEntry]:
    normalized = query.casefold().strip()
    tokens = set(_TOKEN.findall(normalized))
    ranked: list[tuple[int, SystemKnowledgeEntry]] = []
    for entry in APPROVED_SYSTEM_KNOWLEDGE:
        searchable = " ".join((entry.title, entry.content, *entry.keywords)).casefold()
        score = sum(3 for keyword in entry.keywords if keyword.casefold() in normalized)
        score += sum(1 for token in tokens if token in searchable)
        if normalized in searchable:
            score += 5
        if score:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [entry for _, entry in ranked[:limit]]


def is_system_help_request(query: str) -> bool:
    """Keep approved product terms from turning unrelated tasks into product help."""

    normalized = query.strip()
    if not normalized:
        return False
    exact_term = _TERM_NORMALIZER.sub("", normalized).casefold()
    for entry in APPROVED_SYSTEM_KNOWLEDGE:
        for term in (entry.title, *entry.keywords):
            normalized_term = _TERM_NORMALIZER.sub("", term).casefold()
            if exact_term == normalized_term:
                return True
            for match in re.finditer(re.escape(term), normalized, re.IGNORECASE):
                before = normalized[: match.start()]
                after = normalized[match.end() :]
                if _why_question_matches_entry(before, after, entry.why_patterns):
                    return True
                if _HELP_BEFORE_TERM.search(before):
                    return True
                if _HELP_AFTER_TERM.match(after):
                    return True
    return False


def _why_question_matches_entry(
    before: str,
    after: str,
    approved_patterns: tuple[str, ...],
) -> bool:
    if re.search(r"为什么\s*$", before):
        residual = after
    elif re.match(r"^\s*为什么", after):
        residual = re.sub(r"^\s*为什么", "", after, count=1)
    else:
        return False
    normalized_residual = _TERM_NORMALIZER.sub("", residual).casefold()
    return any(
        re.fullmatch(pattern, normalized_residual, re.IGNORECASE) is not None
        for pattern in approved_patterns
    )
