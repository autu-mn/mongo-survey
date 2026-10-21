from datetime import datetime, timedelta, timezone

import jwt
import pytest
from bson import ObjectId
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.deps import optional_user
from app.errors import AppError
from app.security import JWT_ALGORITHM
from tests.conftest import register_and_login


def test_register_success_stores_hash_only(client, db):
    r = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice" and "createdAt" in body and "password" not in body
    doc = db.users.find_one({"username": "alice"})
    assert doc["passwordHash"].startswith("$2b$") and doc["passwordHash"] != "secret123"


def test_register_duplicate_username(client):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    r = client.post("/api/auth/register", json={"username": "alice", "password": "other456"})
    assert r.status_code == 409
    assert r.json()["code"] == "username_taken"


@pytest.mark.parametrize("payload", [
    {"username": "ab", "password": "secret123"},
    {"username": "a" * 33, "password": "secret123"},
    {"username": "has space", "password": "secret123"},
    {"username": "alice", "password": "12345"},
    {"username": "alice", "password": "密" * 25},
    {"username": "alice"},
])
def test_register_invalid_input(client, payload):
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_login_success_and_me(client):
    headers = register_and_login(client)
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


@pytest.mark.parametrize("username,password", [("alice", "wrongpass"), ("nobody", "secret123")])
def test_login_bad_credentials_same_message(client, username, password):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 401
    assert r.json() == {"code": "bad_credentials", "message": "用户名或密码错误", "details": None}


def test_me_without_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "login_required"


def _token(sub, delta=timedelta(hours=1), secret=None):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": sub, "username": "x", "iat": now, "exp": now + delta},
                      secret or settings.jwt_secret, algorithm=JWT_ALGORITHM)


def test_me_with_expired_token(client):
    r = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    token = _token(r.json()["id"], delta=timedelta(seconds=-1))
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["code"] == "token_expired"


@pytest.mark.parametrize("token_factory", [
    lambda uid: "not-a-jwt",
    lambda uid: _token(uid, secret="forged-secret"),
    lambda uid: _token(str(ObjectId())),
    lambda uid: _token("not-an-objectid"),
])
def test_me_with_invalid_token(client, token_factory):
    r = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    token = token_factory(r.json()["id"])
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_token"


def test_optional_user(client, db):
    assert optional_user(db, None) is None
    headers = register_and_login(client)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=headers["Authorization"][7:])
    assert optional_user(db, creds).username == "alice"
    with pytest.raises(AppError) as exc:
        optional_user(db, HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad"))
    assert exc.value.code == "invalid_token"
