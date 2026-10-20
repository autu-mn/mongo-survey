import json
from functools import lru_cache
from pathlib import Path

from pymongo import ASCENDING, DESCENDING, IndexModel, MongoClient
from pymongo.database import Database

from app.config import settings

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

SCHEMA_VERSION = 1

COLLECTIONS = ("users", "surveys", "responses")

INDEXES: dict[str, list[IndexModel]] = {
    "users": [
        IndexModel([("username", ASCENDING)], unique=True, name="uniq_username"),
    ],
    "surveys": [
        IndexModel([("slug", ASCENDING)], unique=True, name="uniq_slug"),
        IndexModel([("ownerId", ASCENDING), ("createdAt", DESCENDING)], name="owner_list"),
    ],
    "responses": [
        IndexModel([("surveyId", ASCENDING), ("submittedAt", DESCENDING)], name="survey_responses"),
        IndexModel(
            [("surveyId", ASCENDING), ("submitterKey", ASCENDING)],
            unique=True,
            partialFilterExpression={"singleSubmission": True},
            name="uniq_single_submission",
        ),
        IndexModel([("respondentId", ASCENDING)], name="respondent", sparse=True),
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


def init_db(db: Database) -> None:
    """建集合、注册 $jsonSchema 校验器、建索引；可重复执行。"""
    existing = set(db.list_collection_names())
    for name in COLLECTIONS:
        validator = {"$jsonSchema": load_schema(name)}
        if name in existing:
            db.command("collMod", name, validator=validator,
                       validationLevel="strict", validationAction="error")
        else:
            db.create_collection(name, validator=validator,
                                 validationLevel="strict", validationAction="error")
        db[name].create_indexes(INDEXES[name])


if __name__ == "__main__":
    init_db(get_db())
    print(f"initialized database '{settings.mongo_db}'")
