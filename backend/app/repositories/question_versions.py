"""【第二阶段新增】不可变题目版本的 MongoDB 读写。版本正文只允许插入。"""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo.database import Database

from app.db import SCHEMA_VERSION


CONTENT_FIELDS = ("type", "title", "description", "required", "options", "constraints")


def content_from_question(question: dict) -> dict:
    """迁移/保存题目：提取与具体问卷的顺序、隐藏和跳转无关的定义。"""
    return {name: question.get(name, "" if name == "description" else None)
            for name in CONTENT_FIELDS}


def insert_version(db: Database, item_id: ObjectId, version_no: int,
                   parent_version_id: ObjectId | None, content: dict) -> dict:
    """P27：插入后没有更新接口；同一题目版本号由唯一索引保证不重复。"""
    doc = {
        "itemId": item_id,
        "versionNo": version_no,
        "parentVersionId": parent_version_id,
        **{name: content[name] for name in CONTENT_FIELDS},
        "createdAt": datetime.now(timezone.utc),
        "schemaVersion": SCHEMA_VERSION,
    }
    doc["_id"] = db.question_versions.insert_one(doc).inserted_id
    return doc


def find_by_id(db: Database, version_id: ObjectId) -> dict | None:
    return db.question_versions.find_one({"_id": version_id})


def find_number(db: Database, item_id: ObjectId, version_no: int) -> dict | None:
    return db.question_versions.find_one({"itemId": item_id, "versionNo": version_no})


def find_latest(db: Database, item_id: ObjectId) -> dict | None:
    """P26：走 uniq_item_version 前缀，按版本号倒序取首个。"""
    return db.question_versions.find_one({"itemId": item_id}, sort=[("versionNo", -1)])


def list_by_item(db: Database, item_id: ObjectId) -> list[dict]:
    """P26：按版本号正序展示版本关系。"""
    return list(db.question_versions.find({"itemId": item_id}).sort("versionNo", 1))
