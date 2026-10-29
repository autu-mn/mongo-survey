"""【第二阶段新增】多个命名题库的输入。"""

from pydantic import Field

from app.models.common import ApiModel


class BankName(ApiModel):
    name: str = Field(min_length=1, max_length=100)
