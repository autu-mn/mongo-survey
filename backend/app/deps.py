from dataclasses import dataclass
from typing import Annotated

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.db import get_db
from app.errors import AppError
from app.repositories import users as users_repo
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: ObjectId
    username: str


DB = Annotated[Database, Depends(get_db)]


def _resolve_user(db: Database, creds: HTTPAuthorizationCredentials | None) -> CurrentUser | None:
    if creds is None:
        return None
    try:
        payload = decode_access_token(creds.credentials)
        user_id = ObjectId(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "登录已过期，请重新登录")
    except (jwt.InvalidTokenError, KeyError, InvalidId):
        raise AppError(401, "invalid_token", "登录凭证无效")
    user = users_repo.find_by_id(db, user_id)
    if user is None:
        raise AppError(401, "invalid_token", "登录凭证无效")
    return CurrentUser(id=user["_id"], username=user["username"])


def optional_user(
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser | None:
    """填写入口等页面：未登录返回 None，带了无效凭证仍报错。"""
    return _resolve_user(db, creds)


def require_user(
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    user = _resolve_user(db, creds)
    if user is None:
        raise AppError(401, "login_required", "请先登录")
    return user


OptionalUser = Annotated[CurrentUser | None, Depends(optional_user)]
RequiredUser = Annotated[CurrentUser, Depends(require_user)]
