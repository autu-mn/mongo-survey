from typing import Any, Literal

from pydantic import Field

from app.models.common import ApiModel

QuestionType = Literal["single", "multiple", "text", "number"]
LogicOp = Literal[
    "eq", "ne", "in",
    "includes", "includesAny", "includesAll", "equalsSet",
    "gt", "gte", "lt", "lte", "between",
]


class OptionIn(ApiModel):
    option_id: str | None = Field(default=None, description="已有选项带上 ID；新选项留空，由后端生成")
    text: str = Field(min_length=1, max_length=200)


class Constraints(ApiModel):
    min_select: int | None = Field(default=None, ge=0)
    max_select: int | None = Field(default=None, ge=1)
    exact_select: int | None = Field(default=None, ge=1)
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1, le=5000)
    min: int | float | None = None
    max: int | float | None = None
    integer_only: bool | None = None

    def to_doc(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


class QuestionIn(ApiModel):
    """添加题目 / 修改题目。跳转规则单独保存（LogicIn）。"""

    type: QuestionType
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    required: bool = False
    options: list[OptionIn] = Field(default_factory=list, max_length=50)
    constraints: Constraints = Field(default_factory=Constraints)


class RuleCondition(ApiModel):
    op: LogicOp
    value: Any


class LogicRuleIn(ApiModel):
    when: RuleCondition
    goto: str = Field(min_length=1, description="目标 questionId，或 END")


class LogicIn(ApiModel):
    """编辑页某道题的跳转规则区：若干条"如果……则跳到……"，加一条"否则跳到……"。"""

    rules: list[LogicRuleIn] = Field(default_factory=list, max_length=50)
    default_goto: str | None = None


class ReorderIn(ApiModel):
    question_ids: list[str] = Field(description="全部题目（含已隐藏）的新顺序")


class SurveyPatch(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
