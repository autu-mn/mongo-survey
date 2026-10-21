import secrets
import string
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import SCHEMA_VERSION

SLUG_ALPHABET = string.ascii_letters + string.digits
SLUG_LENGTH = 8
SLUG_MAX_ATTEMPTS = 5

LIST_PROJECTION = {
    "title": 1, "slug": 1, "status": 1, "responseCount": 1,
    "settings.deadline": 1, "settings.maxResponses": 1,
    "createdAt": 1, "updatedAt": 1,
}


def generate_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned(survey_id: ObjectId, owner_id: ObjectId) -> dict:
    """所有创作者操作的基础条件：本人的、未删除的问卷。"""
    return {"_id": survey_id, "ownerId": owner_id, "deletedAt": None}


def insert_survey(db: Database, owner_id: ObjectId, title: str, description: str,
                  settings: dict) -> dict:
    """新建草稿。slug 由唯一索引保证不重复，冲突时换一个重试。"""
    now = _now()
    doc = {
        "ownerId": owner_id,
        "title": title,
        "description": description,
        "status": "draft",
        "settings": settings,
        "publishedAt": None,
        "closedAt": None,
        "version": 1,
        "responseCount": 0,
        "questions": [],
        "createdAt": now,
        "updatedAt": now,
        "deletedAt": None,
        "schemaVersion": SCHEMA_VERSION,
    }
    for _ in range(SLUG_MAX_ATTEMPTS):
        doc["slug"] = generate_slug()
        doc.pop("_id", None)
        try:
            doc["_id"] = db.surveys.insert_one(doc).inserted_id
            return doc
        except DuplicateKeyError as e:
            if "slug" not in (e.details or {}).get("keyPattern", {}):
                raise
    raise RuntimeError("无法生成不重复的问卷链接")


def list_by_owner(db: Database, owner_id: ObjectId) -> list[dict]:
    """P3 我的问卷列表：走 owner_active_list 索引，按创建时间倒序，只取列表字段。"""
    cursor = (db.surveys
              .find({"ownerId": owner_id, "deletedAt": None}, LIST_PROJECTION)
              .sort("createdAt", -1))
    return list(cursor)


def find_owned(db: Database, survey_id: ObjectId, owner_id: ObjectId,
               projection: dict | None = None) -> dict | None:
    """P4 / P7 / P10 按 ID 读取本人的问卷。"""
    return db.surveys.find_one(_owned(survey_id, owner_id), projection)


def update_owned(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                 update: dict, extra_filter: dict | None = None) -> dict | None:
    """带条件的原子更新；条件不满足返回 None。"""
    flt = _owned(survey_id, owner_id) | (extra_filter or {})
    update.setdefault("$set", {})["updatedAt"] = _now()
    return db.surveys.find_one_and_update(flt, update, return_document=ReturnDocument.AFTER)


def set_settings(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                 settings: dict) -> dict | None:
    """P11 保存分享设置：整体替换 settings 子文档。"""
    return update_owned(db, survey_id, owner_id, {"$set": {"settings": settings}})


def transition_status(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                      from_status: list[str], to_status: str,
                      extra_filter: dict | None = None,
                      extra_set: dict | None = None) -> dict | None:
    """P5 / P11 状态流转：把"当前状态必须是 from_status"写进更新条件，
    检查和修改在同一次原子操作中完成，并发点击也不会出现非法流转。"""
    flt = {"status": {"$in": from_status}} | (extra_filter or {})
    return update_owned(db, survey_id, owner_id,
                        {"$set": {"status": to_status, **(extra_set or {})}}, flt)


def soft_delete(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> bool:
    """P6 软删除：只写 deletedAt，答卷保留。"""
    now = _now()
    res = db.surveys.update_one(_owned(survey_id, owner_id),
                                {"$set": {"deletedAt": now, "updatedAt": now}})
    return res.modified_count == 1


def recount_responses(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict | None:
    """用 responses 中的实际数量校准冗余计数器 responseCount。"""
    actual = db.responses.count_documents({"surveyId": survey_id})
    return update_owned(db, survey_id, owner_id, {"$set": {"responseCount": actual}})
