from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(ge=0)


class ChatSubmit(ChatGeneration):
    content: str = Field(min_length=1, max_length=6000)
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value.strip()


class ChartSegment(BaseModel):
    index: int
    count: int
    total_range: dict[str, str]


class ChartDescriptor(BaseModel):
    chart_id: str
    schema_version: Literal[1] = 1
    type: Literal["line", "grouped_bar", "stacked_bar", "horizontal_bar"]
    title: str
    unit: str
    range: dict[str, str] | None
    point_count: int
    segment: ChartSegment | None = None
    queried_at: str | None = None
    source: Literal["store_query", "saved_chart"] | None = None


class ChartValue(BaseModel):
    exact: str | None
    plot: float | None
    status: str


class ChartPoint(BaseModel):
    dimension: str | int
    state: str
    values: dict[str, ChartValue]


class ChartPayload(BaseModel):
    type: Literal["line", "grouped_bar", "stacked_bar", "horizontal_bar"]
    title: str
    dimension: str
    granularity: str
    unit: str
    range: dict[str, str]
    queried_at: str
    unfinished: bool
    coverage: dict
    notes: list[str]
    series: list[dict[str, str]]
    points: list[ChartPoint]
    segment: ChartSegment | None = None
    y_domain: list[float] | None = None


class ChatChart(BaseModel):
    chart_id: str
    message_id: int
    schema_version: Literal[1] = 1
    payload: ChartPayload
    source: dict
    created_at: str


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: Literal["user", "assistant"]
    content: str
    charts: list[ChartDescriptor] = Field(default_factory=list)


class ChatRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    generation: int
    request_id: str | None
    status: Literal["running", "completed", "failed"]
    output: str
    error_code: str | None
    model: str
    calls: int
    usage: dict[str, int] | None


class ChatConversation(BaseModel):
    generation: int = 0
    messages: list[ChatMessage]
    run: ChatRun | None
    next_before: int | None = None
