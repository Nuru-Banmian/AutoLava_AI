"""Default summary policy; explicit detail, chart and comparison requests win."""
import re
from calendar import monthrange
from datetime import date


def month_followup_range(question: str, today: date) -> dict | None:
    """Resolve a month-only followup, not a comparison or detailed date request."""
    match = re.fullmatch(r"\s*(?:那)?(上上|上|本|这个)个?月(?:的)?(?:呢)?[？?。！!\s]*", question)
    if not match:
        return None
    offset = {"上上": -2, "上": -1, "本": 0, "这个": 0}[match[1]]
    absolute = today.year * 12 + today.month - 1 + offset
    year, month = divmod(absolute, 12)
    month += 1
    end = today if offset == 0 else date(year, month, monthrange(year, month)[1])
    return {"start": date(year, month, 1).isoformat(), "end": end.isoformat()}


def summary_period(question: str) -> str | None:
    if re.search(r"明细|每天|每日|逐日|逐月|每月|各月|按|分组|分类|构成|来源|图|趋势|比较|对比|同比|环比|排名|最高|最低|拆|细|\d+月\d+日|\d{4}-\d{2}-\d{2}", question):
        return None
    if not re.search(r"收入|营业额|营收|revenue|income", question, re.I):
        return None
    if re.search(r"全年|今年|去年|年度|年收入|\d{4}年", question) and not re.search(r"月|周|星期", question):
        return "year"
    if re.search(r"月", question) and not re.search(r"周|星期", question):
        return "month"
    return None


def needs_summary(target, period: str | None, today: date) -> bool:
    if period is None:
        return False
    if target.fields or target.filters or target.top_n or set(target.group_by) - {period}:
        return True
    selection = target.range
    if selection is None:
        return period != "month"
    if selection.preset:
        return selection.preset not in {f"this_{period}", f"last_{period}"}
    if not selection.start:
        return True
    start, end = date.fromisoformat(selection.start), date.fromisoformat(selection.end)
    if period == "month":
        full = start.day == 1 and start.year == end.year and start.month == end.month
        cutoff = end.day == monthrange(end.year, end.month)[1] or end == today
    else:
        full = start.month == 1 and start.day == 1 and start.year == end.year
        cutoff = (end.month == 12 and end.day == 31) or end == today
    return not (full and cutoff)
