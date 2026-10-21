from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.models.common import ApiModel

DisplayStatus = Literal["draft", "open", "expired", "full", "closed"]


class SurveyCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class Completion(ApiModel):
    message: str = Field(default="感谢您的填写！", max_length=1000)
    redirect_url: str | None = Field(default=None, max_length=2000, pattern=r"^https?://\S+$")


class Settings(ApiModel):
    """分享设置页（P10 / P11）的全部内容，与 surveys.settings 子文档一一对应。"""

    require_login: bool = True
    allow_anonymous: bool = False
    allow_multiple_submit: bool = False
    deadline: AwareDatetime | None = Field(default=None, description="必须带时区，例如 2026-11-01T00:00:00+08:00")
    max_responses: int | None = Field(default=None, ge=1)
    completion: Completion = Field(default_factory=Completion)

    @model_validator(mode="after")
    def _single_submit_needs_login(self):
        if not self.allow_multiple_submit and not self.require_login:
            raise ValueError("限制每人只能填写一次时，必须要求填写者登录")
        return self

    def to_doc(self) -> dict:
        return {
            "requireLogin": self.require_login,
            "allowAnonymous": self.allow_anonymous,
            "allowMultipleSubmit": self.allow_multiple_submit,
            "deadline": self.deadline,
            "maxResponses": self.max_responses,
            "completion": {
                "message": self.completion.message,
                "redirectUrl": self.completion.redirect_url,
            },
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "Settings":
        return cls.model_validate(doc)


class SurveyListItem(ApiModel):
    """列表页（P3）只返回这些字段。"""

    id: str
    title: str
    slug: str
    status: Literal["draft", "published", "closed"]
    display_status: DisplayStatus
    response_count: int
    deadline: datetime | None
    max_responses: int | None
    created_at: datetime
    updated_at: datetime


class SurveyDetail(SurveyListItem):
    """管理页 / 编辑页（P4 / P7）。"""

    description: str
    settings: Settings
    version: int
    question_count: int
    published_at: datetime | None
    closed_at: datetime | None
    questions: list[dict]
