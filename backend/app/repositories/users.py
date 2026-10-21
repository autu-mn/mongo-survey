from datetime import datetime, timezone

from bson import ObjectId
from pymongo.database import Database

from app.db import SCHEMA_VERSION


def insert_user(db: Database, username: str, password_hash: str) -> dict:
    """P1 注册。用户名重复时由唯一索引抛出 DuplicateKeyError。"""
    doc = {
        "username": username,
        "passwordHash": password_hash,
        "createdAt": datetime.now(timezone.utc),
        "schemaVersion": SCHEMA_VERSION,
    }
    doc["_id"] = db.users.insert_one(doc).inserted_id
    return doc


def find_by_username(db: Database, username: str) -> dict | None:
    """P2 登录，走 uniq_username 索引。"""
    return db.users.find_one({"username": username})


def find_by_id(db: Database, user_id: ObjectId) -> dict | None:
    return db.users.find_one({"_id": user_id}, {"passwordHash": 0})


def usernames(db: Database, user_ids: list[ObjectId]) -> dict[ObjectId, str]:
    """P18 导出时批量查询填写者用户名（一次 $in 查询一批）。"""
    return {u["_id"]: u["username"] for u in db.users.find({"_id": {"$in": user_ids}}, {"username": 1})}
