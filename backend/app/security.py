from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

JWT_ALGORITHM = "HS256"

# 用户不存在时也做一次哈希比较，使"用户不存在"和"密码错误"耗时相同，避免枚举用户名
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    ok = bcrypt.checkpw(password.encode("utf-8"), (password_hash or _DUMMY_HASH).encode())
    return ok and password_hash is not None


def create_access_token(user_id: str, username: str) -> tuple[str, int]:
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict:
    """失败时抛出 jwt.ExpiredSignatureError 或 jwt.InvalidTokenError。"""
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
