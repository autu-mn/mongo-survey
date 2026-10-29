"""【第二阶段新增】独立题目、不可变版本及共享的请求模型。"""

from typing import Literal

from pydantic import Field, model_validator

from app.models.common import ApiModel
from app.models.question import QuestionIn


class ItemCreate(ApiModel):
    content: QuestionIn | None = None
    source_version_id: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.content is None) == (self.source_version_id is None):
            raise ValueError("content 和 sourceVersionId 必须且只能提供一个")
        return self


class VersionCreate(ApiModel):
    parent_version_id: str
    content: QuestionIn | None = None  # 省略时复制旧版，作为“恢复旧版”


class SharingUpdate(ApiModel):
    visibility: Literal["private", "public", "selected"]
    usernames: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_targets(self):
        if self.visibility != "selected" and self.usernames:
            raise ValueError("仅定向共享可填写 usernames")
        if self.visibility == "selected" and not self.usernames:
            raise ValueError("定向共享至少需要一名用户")
        if len(self.usernames) != len(set(self.usernames)):
            raise ValueError("共享用户名不能重复")
        return self
