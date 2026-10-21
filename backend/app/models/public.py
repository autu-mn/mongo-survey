from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.models.common import ApiModel
from app.models.survey import Completion

EntryState = Literal["ok", "ended", "login_required", "already_submitted"]
EndedReason = Literal["closed", "expired", "full"]


class PublicOption(ApiModel):
    option_id: str
    text: str


class PublicQuestion(ApiModel):
    """给填写者看的题目：不含跳转规则（跳转由后端计算），不含已隐藏的题目和选项。"""

    question_id: str
    number: int = Field(description="显示用题号，只对未隐藏的题连续编号")
    type: str
    title: str
    description: str
    required: bool
    options: list[PublicOption]
    constraints: dict


class PublicSurvey(ApiModel):
    slug: str
    title: str
    description: str
    require_login: bool
    allow_anonymous: bool
    allow_multiple_submit: bool
    first_question_id: str | None
    questions: list[PublicQuestion]


class DraftOut(ApiModel):
    """上次的填写进度（P19）。path 末尾为下一道要答的题。"""

    path: list[str]
    answers: dict[str, Any]
    last_visited_at: datetime


class EntryOut(ApiModel):
    """填写入口（P12 / P13）：告诉前端该显示哪个页面。"""

    state: EntryState
    reason: EndedReason | None = None
    survey: PublicSurvey
    draft: DraftOut | None = None
    draft_discarded: bool = Field(default=False, description="问卷已被修改，上次的进度已作废")


class NextIn(ApiModel):
    question_id: str
    value: Any = None


class NextOut(ApiModel):
    next: str = Field(description="下一题的 questionId，或 END")


class SubmitIn(ApiModel):
    answers: dict[str, Any] = Field(description="questionId → 答案；单选为 optionId，多选为 optionId 列表")


class SubmitOut(ApiModel):
    response_id: str
    completion: Completion
    allow_multiple_submit: bool
