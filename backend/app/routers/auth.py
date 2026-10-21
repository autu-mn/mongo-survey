from fastapi import APIRouter
from pymongo.errors import DuplicateKeyError

from app.deps import DB, RequiredUser
from app.errors import AppError
from app.models.auth import Credentials, TokenOut, UserOut
from app.repositories import users as users_repo
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _user_out(doc: dict) -> UserOut:
    return UserOut(id=str(doc["_id"]), username=doc["username"], created_at=doc["createdAt"])


@router.post("/register", response_model=UserOut, status_code=201, summary="注册（P1）")
def register(body: Credentials, db: DB):
    try:
        doc = users_repo.insert_user(db, body.username, hash_password(body.password))
    except DuplicateKeyError:
        raise AppError(409, "username_taken", "用户名已存在")
    return _user_out(doc)


@router.post("/login", response_model=TokenOut, summary="登录（P2）")
def login(body: Credentials, db: DB):
    doc = users_repo.find_by_username(db, body.username)
    if not verify_password(body.password, doc["passwordHash"] if doc else None):
        raise AppError(401, "bad_credentials", "用户名或密码错误")
    token, expires_in = create_access_token(str(doc["_id"]), doc["username"])
    return TokenOut(access_token=token, expires_in=expires_in, user=_user_out(doc))


@router.get("/me", response_model=UserOut, summary="当前登录用户")
def me(user: RequiredUser, db: DB):
    return _user_out(users_repo.find_by_id(db, user.id))
