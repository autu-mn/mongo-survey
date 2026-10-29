"""【第二阶段新增】题目身份集合的 MongoDB 读写；授权判断留给 service 层。"""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo.database import Database

from app.db import SCHEMA_VERSION


def insert_item(db: Database, owner_id: ObjectId, *,
                origin_survey_id: ObjectId | None = None,
                origin_question_id: str | None = None) -> dict:
    """P25 / P31 / 迁移：建立私有题目身份。问卷来源的唯一性由索引兜底。"""
    if (origin_survey_id is None) != (origin_question_id is None):
        raise ValueError("迁移来源的问卷 ID 与题目 ID 必须同时提供")
    now = datetime.now(timezone.utc)
    doc = {
        "ownerId": owner_id,
        "visibility": "private",
        "sharedUserIds": [],
        "createdAt": now,
        "updatedAt": now,
        "schemaVersion": SCHEMA_VERSION,
    }
    if origin_survey_id is not None:
        doc.update(originSurveyId=origin_survey_id, originQuestionId=origin_question_id)
    doc["_id"] = db.question_items.insert_one(doc).inserted_id
    return doc


def find_by_id(db: Database, item_id: ObjectId) -> dict | None:
    return db.question_items.find_one({"_id": item_id})


def find_by_origin(db: Database, survey_id: ObjectId, question_id: str) -> dict | None:
    """迁移：走 uniq_legacy_origin，避免重复创建。"""
    return db.question_items.find_one({"originSurveyId": survey_id,
                                       "originQuestionId": question_id})


def list_owned(db: Database, owner_id: ObjectId, limit: int = 50, offset: int = 0) -> list[dict]:
    """P24：按 owner_items 索引读取。"""
    return list(db.question_items.find({"ownerId": owner_id}).sort([("createdAt", -1), ("_id", -1)])
                .skip(offset).limit(limit))


def list_public(db: Database, limit: int = 50) -> list[dict]:
    """P24：按 public_items 索引读取。"""
    return list(db.question_items.find({"visibility": "public"})
                .sort([("createdAt", -1), ("_id", -1)]).limit(limit))


def list_shared_with(db: Database, user_id: ObjectId, limit: int = 50) -> list[dict]:
    """P24：按 shared_items 多键索引读取定向共享。"""
    return list(db.question_items.find({"visibility": "selected", "sharedUserIds": user_id})
                .sort([("createdAt", -1), ("_id", -1)]).limit(limit))


def set_sharing(db: Database, item_id: ObjectId, owner_id: ObjectId,
                visibility: str, shared_user_ids: list[ObjectId]) -> dict | None:
    """P28：只有所有者条件命中才更新；业务层校验被共享用户是否存在。"""
    from pymongo import ReturnDocument

    return db.question_items.find_one_and_update(
        {"_id": item_id, "ownerId": owner_id},
        {"$set": {"visibility": visibility, "sharedUserIds": shared_user_ids,
                  "updatedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def has_owned_reference(db: Database, item_id: ObjectId, owner_id: ObjectId) -> bool:
    """P33/P34：共享撤销后，仅允许已有本人问卷查看来源历史。"""
    return db.surveys.find_one({"ownerId": owner_id, "deletedAt": None,
                                "questions.sourceItemId": item_id}, {"_id": 1}) is not None
