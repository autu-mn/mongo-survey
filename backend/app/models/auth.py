from datetime import datetime

from pydantic import Field, field_validator

from app.models.common import ApiModel


class Credentials(ApiModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^\S+$",
                          description="3 至 32 个字符，不能包含空白")
    password: str = Field(min_length=6, max_length=72)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("密码过长（bcrypt 最多 72 字节）")
        return v


class UserOut(ApiModel):
    id: str
    username: str
    created_at: datetime


class TokenOut(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
