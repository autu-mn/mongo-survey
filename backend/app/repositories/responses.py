from bson import ObjectId
from pymongo.database import Database


def has_single_submission(db: Database, survey_id: ObjectId, key: str) -> bool:
    """P13 是否已填过。条件中必须带 singleSubmission: true，
    查询才能命中部分索引 uniq_single_submission（部分索引只对满足其过滤条件的查询生效）。"""
    return db.responses.find_one(
        {"surveyId": survey_id, "submitterKey": key, "singleSubmission": True},
        {"_id": 1},
    ) is not None


def insert_response(db: Database, doc: dict) -> ObjectId:
    """P15 第二步：插入答卷。限制每人一次时，重复提交由唯一部分索引抛出 DuplicateKeyError。"""
    return db.responses.insert_one(doc).inserted_id
