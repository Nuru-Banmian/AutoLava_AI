from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
import unicodedata

from app.agent.contracts import EventTypeCode


EVENT_TYPE_ANALYSIS_VERSION = "event_type_rules.v1"


@dataclass(frozen=True)
class ClassifiedEventType:
    code: EventTypeCode
    name: str


_EVENT_TYPE_RULES: Sequence[tuple[ClassifiedEventType, re.Pattern[str]]] = (
    (
        ClassifiedEventType(EventTypeCode.ACCESS_DISRUPTION, "通行受阻"),
        re.compile(r"封路|道路施工|道路封闭|交通管制|入口封闭|无法通行", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.EQUIPMENT_ISSUE, "设备问题"),
        re.compile(r"设备|故障|检修|维修|停机|坏了", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.LOCAL_EVENT, "当地事件"),
        re.compile(r"活动|节庆|节日|比赛|展会|集市|演出", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.PROMOTION, "促销"),
        re.compile(r"促销|优惠|折扣|满减|赠送|coupon|promotion", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.SCHEDULE_CHANGE, "营业时间变化"),
        re.compile(r"提前关|提前休息|晚开|延迟营业|临时关门|缩短营业", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.STAFFING_ISSUE, "人员问题"),
        re.compile(r"员工|人手|缺勤|请假|罢工|人员不足", re.IGNORECASE),
    ),
    (
        ClassifiedEventType(EventTypeCode.WEATHER_DISRUPTION, "天气影响"),
        re.compile(r"暴雨|雷雨|泥雨|降雨|下雨|降雪|大雪|冰雹|高温|低温|大风", re.IGNORECASE),
    ),
)


def normalize_event_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def classify_event_types(text: str) -> list[ClassifiedEventType]:
    normalized = normalize_event_text(text)
    return [event_type for event_type, pattern in _EVENT_TYPE_RULES if pattern.search(normalized)]
