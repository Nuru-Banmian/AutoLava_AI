"""Calendar ranges in the authorized store's local natural days."""
from calendar import monthrange
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: str | None = None
    end: str | None = None
    preset: Literal["today", "yesterday", "this_week", "last_week", "this_month", "last_month",
                    "this_year", "last_year", "last_n_days", "last_n_weeks", "last_n_months",
                    "last_n_complete_days", "last_n_complete_weeks", "last_n_complete_months",
                    "same_period_last_year"] | None = None
    n: int | None = Field(default=None, ge=1, le=120000)
    all_history: bool | None = None
    base: dict | None = None

    @model_validator(mode="after")
    def valid(self):
        if sum([self.start is not None or self.end is not None,
                self.preset is not None, self.all_history is not None]) != 1:
            raise ValueError("Choose exact dates, preset or all_history")
        if self.all_history is not None and self.all_history is not True:
            raise ValueError("all_history must be true")
        if self.start is not None or self.end is not None:
            for value in (self.start, self.end):
                if value is None or date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Use YYYY-MM-DD start/end")
            if self.start > self.end:
                raise ValueError("start > end")
        if bool(self.preset and self.preset.startswith("last_n_")) != (self.n is not None):
            raise ValueError("Only last_n presets require n")
        if (self.preset == "same_period_last_year") != (self.base is not None):
            raise ValueError("same_period_last_year requires base range")
        if self.base is not None:
            if self.base.get("preset") == "same_period_last_year" or "base" in self.base:
                raise ValueError("No recursive base range")
            DateRange.model_validate(self.base)
        return self


def month_start(day, offset=0):
    number = day.year * 12 + day.month - 1 + offset
    year, month = divmod(number, 12)
    return date(year, month + 1, 1)


def previous_year(day):
    return date(day.year - 1, day.month, min(day.day, monthrange(day.year - 1, day.month)[1]))


def resolve_range(selection, today, history):
    notes = []
    if selection is None:
        start, end = today.replace(day=1), today
        notes.append("未指定范围，默认本月至今")
    elif selection.all_history:
        start = date.fromisoformat(history["start"]) if history["start"] else today
        end = today
        notes.append("全部历史边界已重新查询；无历史数据时范围为当地今天")
    elif selection.start:
        start, end = date.fromisoformat(selection.start), date.fromisoformat(selection.end)
    else:
        preset, n = selection.preset, selection.n or 1
        monday = today - timedelta(days=today.weekday())
        if preset == "today":
            start = end = today
        elif preset == "yesterday":
            start = end = today - timedelta(days=1)
        elif preset == "this_week":
            start, end = monday, today
        elif preset == "last_week":
            start, end = monday - timedelta(days=7), monday - timedelta(days=1)
        elif preset == "this_month":
            start, end = today.replace(day=1), today
        elif preset == "last_month":
            start, end = month_start(today, -1), today.replace(day=1) - timedelta(days=1)
        elif preset == "this_year":
            start, end = date(today.year, 1, 1), today
        elif preset == "last_year":
            start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        elif "days" in preset:
            end = today - timedelta(days=1) if "complete" in preset else today
            start = end - timedelta(days=n - 1)
        elif "weeks" in preset:
            end = monday - timedelta(days=1) if "complete" in preset else today
            start = monday - timedelta(weeks=n if "complete" in preset else n - 1)
        elif "months" in preset:
            end = today.replace(day=1) - timedelta(days=1) if "complete" in preset else today
            start = month_start(today, -n if "complete" in preset else 1 - n)
        else:
            base = resolve_range(DateRange.model_validate(selection.base), today, history)
            if base["range"] is None:
                raise ValueError("Base range has no valid dates")
            first, last = [date.fromisoformat(base["range"][k]) for k in ("start", "end")]
            start, end = previous_year(first), previous_year(last)
            # A complete calendar month/year maps to the complete corresponding period.
            if first.day == 1 and last.day == monthrange(last.year, last.month)[1]:
                end = end.replace(day=monthrange(end.year, end.month)[1])
            notes.append("按上一年对应月日映射；短月/闰日截到有效月末，不重复补点，不声称完整自然周")
    requested = {"start": start.isoformat(), "end": end.isoformat()}
    if end > today:
        notes.append("未来截止日期截到门店当地今天")
    end = min(end, today)
    return {"requested_range": requested, "range": {"start": start.isoformat(), "end": end.isoformat()} if start <= end else None,
            "local_date": today.isoformat(), "unfinished": end == today, "notes": notes}


def comparison_range(selection, comparison, today, current, history):
    """Explicit comparison dates win; calendar presets preserve cycle progress."""
    if comparison.range is not None:
        return resolve_range(comparison.range, today, history)
    first, last = (date.fromisoformat(current[key]) for key in ("start", "end"))
    if comparison.preset == "same_period_last_year":
        return resolve_range(DateRange(preset="same_period_last_year", base=current), today, history)
    preset = selection.preset if selection else "this_month"
    if preset and ("month" in preset or preset in ("this_year", "last_year")):
        months = 12 if preset in ("this_year", "last_year") else selection.n if "last_n" in preset else 1
        start_month, end_month = month_start(first, -months), month_start(last, -months)
        start = start_month.replace(day=min(first.day, monthrange(start_month.year, start_month.month)[1]))
        final_day = monthrange(end_month.year, end_month.month)[1] if last.day == monthrange(last.year, last.month)[1] else min(last.day, monthrange(end_month.year, end_month.month)[1])
        end = end_month.replace(day=final_day)
    elif preset and "week" in preset:
        offset = timedelta(weeks=selection.n if "last_n" in preset else 1)
        start, end = first - offset, last - offset
    elif first.day == 1 and last.day == monthrange(last.year, last.month)[1]:
        months = (last.year - first.year) * 12 + last.month - first.month + 1
        start = month_start(first, -months)
        end = first - timedelta(days=1)
    else:
        offset = timedelta(days=(last - first).days + 1)
        start, end = first - offset, last - offset
    value = resolve_range(DateRange(start=start.isoformat(), end=end.isoformat()), today, history)
    value["notes"].append("上期使用相同指标及筛选；当前周期按同进度，完整周期按完整边界；短月截到月末")
    return value
