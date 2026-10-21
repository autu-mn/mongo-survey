import os

os.environ["MONGO_DB"] = "survey_system_test"

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_client, init_db
from app.main import app


@pytest.fixture
def db():
    client = get_client()
    client.drop_database(settings.mongo_db)
    database = client[settings.mongo_db]
    init_db(database)
    yield database
    client.drop_database(settings.mongo_db)


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def register_and_login(client: TestClient, username: str = "alice", password: str = "secret123") -> dict:
    """注册并登录，返回带 Authorization 的请求头。"""
    client.post("/api/auth/register", json={"username": username, "password": password})
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}
