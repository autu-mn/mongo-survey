import json
from functools import lru_cache
from pathlib import Path

from pymongo import ASCENDING, DESCENDING, IndexModel, MongoClient
from pymongo.database import Database

from app.config import settings

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

SCHEMA_VERSION = 1

COLLECTIONS = ("users", "surveys", "responses", "drafts")

INDEXES: dict[str, list[IndexModel]] = {
    "users": [
        IndexModel([("username", ASCENDING)], unique=True, name="uniq_username"),
    ],
    "surveys": [
        IndexModel([("slug", ASCENDING)], unique=True, name="uniq_slug"),
        IndexModel(
            [("ownerId", ASCENDING), ("deletedAt", ASCENDING), ("createdAt", DESCENDING)],
            name="owner_active_list",
        ),
    ],
    "responses": [
        IndexModel(
            [("surveyId", ASCENDING), ("submittedAt", ASCENDING), ("_id", ASCENDING)],
            name="survey_responses",
        ),
        IndexModel(
            [("surveyId", ASCENDING), ("submitterKey", ASCENDING)],
            unique=True,
            partialFilterExpression={"singleSubmission": True},
            name="uniq_single_submission",
        ),
        IndexModel([("respondentId", ASCENDING), ("submittedAt", DESCENDING)], name="respondent_history"),
    ],
    "drafts": [
        IndexModel([("userId", ASCENDING), ("surveyId", ASCENDING)], unique=True, name="uniq_user_survey"),
        IndexModel([("userId", ASCENDING), ("lastVisitedAt", DESCENDING)], name="user_recent"),
        IndexModel([("lastVisitedAt", ASCENDING)], name="ttl_last_visited",
                   expireAfterSeconds=settings.draft_ttl_days * 86400),
    ],
}


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / f"{name}.schema.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def get_client() -> MongoClient:
    return MongoClient(settings.mongo_uri, tz_aware=True)


def get_db() -> Database:
    return get_client()[settings.mongo_db]


_INDEX_OPTIONS = ("unique", "sparse", "partialFilterExpression", "expireAfterSeconds")


def _same_index(existing: dict, declared: dict) -> bool:
    if list(existing["key"].items()) != list(declared["key"].items()):
        return False
    return all(existing.get(opt) == declared.get(opt) for opt in _INDEX_OPTIONS)


def init_db(db: Database) -> None:
    """建集合、注册 $jsonSchema 校验器、同步索引；可重复执行。

    INDEXES 是索引的唯一来源：未声明的旧索引、以及同名但定义已改变的索引会被删除后重建。
    """
    existing = set(db.list_collection_names())
    for name in COLLECTIONS:
        validator = {"$jsonSchema": load_schema(name)}
        if name in existing:
            db.command("collMod", name, validator=validator,
                       validationLevel="strict", validationAction="error")
        else:
            db.create_collection(name, validator=validator,
                                 validationLevel="strict", validationAction="error")
        declared = {ix.document["name"]: ix.document for ix in INDEXES[name]}
        for ix in db[name].list_indexes():
            if ix["name"] == "_id_":
                continue
            if ix["name"] not in declared or not _same_index(ix, declared[ix["name"]]):
                db[name].drop_index(ix["name"])
        db[name].create_indexes(INDEXES[name])


if __name__ == "__main__":
    init_db(get_db())
    print(f"initialized database '{settings.mongo_db}'")
