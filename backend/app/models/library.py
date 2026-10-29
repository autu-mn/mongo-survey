"""【第二阶段新增】问卷编辑页的题目版本引用输入。"""

from pydantic import Field

from app.models.common import ApiModel


class VersionSelection(ApiModel):
    version_id: str = Field(min_length=1)


class SaveToLibrary(ApiModel):
    bank_id: str | None = None
