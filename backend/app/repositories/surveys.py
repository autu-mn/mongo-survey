import copy
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
    # MongoDB 日期只精确到毫秒；updatedAt 用作乐观锁，返回给前端的值必须与库中一致
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


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


def copy_as_draft(db: Database, source: dict) -> dict:
    """【第二阶段新增】复制问卷快照、规则和来源，不复制答卷与发布状态。"""
    now = _now()
    doc = copy.deepcopy(source)
    doc.pop("_id", None)
    doc.update(status="draft", publishedAt=None, closedAt=None, deletedAt=None,
               responseCount=0, version=1, createdAt=now, updatedAt=now,
               schemaVersion=SCHEMA_VERSION)
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
    """带条件的原子更新；条件不满足返回 None。只支持 $set 与 $inc。

    updatedAt 是编辑页的乐观锁，必须每次更新都严格变大：同一毫秒内的两次保存若得到相同的
    updatedAt，持有旧值的窗口就能绕过冲突检测。因此用管道更新取 max(当前时间, 旧值 + 1 毫秒)。
    所有写入的值都用 $literal 包裹，避免以 $ 开头的文本（如题目标题）被当成字段引用。
    """
    flt = _owned(survey_id, owner_id) | (extra_filter or {})
    fields = {k: {"$literal": v} for k, v in update.get("$set", {}).items()}
    fields |= {k: {"$add": [f"${k}", n]} for k, n in update.get("$inc", {}).items()}
    fields["updatedAt"] = {"$max": [_now(), {"$add": ["$updatedAt", 1]}]}
    return db.surveys.find_one_and_update(flt, [{"$set": fields}], return_document=ReturnDocument.AFTER)


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


def save_editor_changes(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                        expected_updated_at: datetime, set_fields: dict,
                        bump_version: bool, require_draft: bool = False) -> dict | None:
    """P8 编辑页保存：以读取时的 updatedAt 作为乐观锁条件整体写回题目数组。
    期间若有其他窗口修改过问卷，条件不匹配，返回 None。"""
    update = {"$set": dict(set_fields)}
    if bump_version:
        update["$inc"] = {"version": 1}
    flt = {"updatedAt": expected_updated_at}
    if require_draft:
        flt["status"] = "draft"
    return update_owned(db, survey_id, owner_id, update, extra_filter=flt)


def find_active(db: Database, survey_id: ObjectId) -> dict | None:
    """按 ID 读取未删除的问卷（不限创作者），用于填写者查看自己的答卷。"""
    return db.surveys.find_one({"_id": survey_id, "deletedAt": None})


def find_by_slug(db: Database, slug: str) -> dict | None:
    """P12 / P14 填写者通过链接打开问卷，走 uniq_slug 索引。"""
    return db.surveys.find_one({"slug": slug})


def reserve_slot(db: Database, survey_id: ObjectId, now: datetime) -> bool:
    """P15 第一步：原子地占用一个答卷名额。

    问卷可填写（已发布、未删除、未截止、未满额）的检查与 responseCount + 1 在同一条
    更新语句中完成，多人同时提交也不会超过上限。"""
    res = db.surveys.update_one(
        {
            "_id": survey_id,
            "status": "published",
            "deletedAt": None,
            "$and": [
                {"$or": [{"settings.deadline": None}, {"settings.deadline": {"$gt": now}}]},
                {"$or": [{"settings.maxResponses": None},
                         {"$expr": {"$lt": ["$responseCount", "$settings.maxResponses"]}}]},
            ],
        },
        {"$inc": {"responseCount": 1}},
    )
    return res.modified_count == 1


def release_slot(db: Database, survey_id: ObjectId) -> None:
    """插入答卷失败时归还名额。"""
    db.surveys.update_one({"_id": survey_id, "responseCount": {"$gt": 0}},
                          {"$inc": {"responseCount": -1}})


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
