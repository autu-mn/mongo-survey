"""填写进度（drafts 集合）：P19 至 P22。"""

from datetime import datetime

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import SCHEMA_VERSION

LIST_LIMIT = 50


def _key(user_id: ObjectId, survey_id: ObjectId) -> dict:
    return {"userId": user_id, "surveyId": survey_id}


def _upsert(db: Database, flt: dict, update, **kw):
    """唯一索引上的并发 upsert 可能有一方报 DuplicateKeyError，此时文档已存在，重试一次即为更新。"""
    try:
        return db.drafts.update_one(flt, update, upsert=True, **kw)
    except DuplicateKeyError:
        return db.drafts.update_one(flt, update, upsert=True, **kw)


def touch(db: Database, user_id: ObjectId, survey: dict, first_qid: str, now: datetime) -> dict:
    """P19 打开问卷：有进度则更新访问时间，没有则新建；返回最新的进度文档。"""
    _upsert(db, _key(user_id, survey["_id"]), {
        "$set": {"lastVisitedAt": now},
        "$setOnInsert": {
            "surveyVersion": survey["version"], "answers": {}, "path": [first_qid],
            "createdAt": now, "schemaVersion": SCHEMA_VERSION,
        },
    })
    return db.drafts.find_one(_key(user_id, survey["_id"]))


def reset(db: Database, user_id: ObjectId, survey: dict, first_qid: str, now: datetime) -> dict:
    """问卷版本已变：清空进度，从第一题重新开始。"""
    db.drafts.update_one(_key(user_id, survey["_id"]), {"$set": {
        "surveyVersion": survey["version"], "answers": {}, "path": [first_qid], "lastVisitedAt": now,
    }})
    return db.drafts.find_one(_key(user_id, survey["_id"]))


def save_step(db: Database, user_id: ObjectId, survey: dict, qid: str, value,
              next_qid: str | None, now: datetime) -> None:
    """P20 保存一题。管道更新在一条语句里完成：写入答案、把路径截断到这道题、接上下一题。

    用户点"上一题"改了前面的答案时，这道题之后的旧路径随之作废；两个标签页同时操作也不会互相覆盖。
    """
    next_list = [next_qid] if next_qid else []
    path_expr = {"$let": {
        "vars": {"p": {"$ifNull": ["$path", []]}},
        "in": {"$let": {
            "vars": {"i": {"$indexOfArray": ["$$p", qid]}},
            "in": {"$concatArrays": [
                {"$cond": [{"$gt": ["$$i", 0]}, {"$slice": ["$$p", "$$i"]},
                           {"$cond": [{"$eq": ["$$i", 0]}, [], "$$p"]}]},
                [qid],
                next_list,
            ]},
        }},
    }}
    _upsert(db, _key(user_id, survey["_id"]), [{"$set": {
        "path": path_expr,
        f"answers.{qid}": {"$literal": value},
        "lastVisitedAt": now,
        "surveyVersion": {"$ifNull": ["$surveyVersion", survey["version"]]},
        "createdAt": {"$ifNull": ["$createdAt", now]},
        "schemaVersion": {"$ifNull": ["$schemaVersion", SCHEMA_VERSION]},
    }}])


def delete(db: Database, user_id: ObjectId, survey_id: ObjectId) -> None:
    """P21 提交成功或重新开始。"""
    db.drafts.delete_one(_key(user_id, survey_id))


def list_with_surveys(db: Database, user_id: ObjectId) -> list[dict]:
    """P22 我参与的问卷（填写中）：走 user_recent 索引，$lookup 取问卷标题和状态；已删除的问卷被过滤掉。"""
    return list(db.drafts.aggregate([
        {"$match": {"userId": user_id}},
        {"$sort": {"lastVisitedAt": -1}},
        {"$limit": LIST_LIMIT},
        {"$lookup": {
            "from": "surveys", "localField": "surveyId", "foreignField": "_id", "as": "survey",
            "pipeline": [
                {"$match": {"deletedAt": None}},
                {"$project": {
                    "title": 1, "slug": 1, "status": 1, "settings": 1, "responseCount": 1, "version": 1,
                    "visibleIds": {"$map": {
                        "input": {"$filter": {"input": "$questions", "cond": {"$eq": ["$$this.hidden", False]}}},
                        "in": "$$this.questionId",
                    }},
                }},
            ],
        }},
        {"$unwind": "$survey"},
    ]))
