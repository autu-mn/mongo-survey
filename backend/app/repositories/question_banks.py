"""【第二阶段新增】个人命名题库集合的 MongoDB 读写。"""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.db import SCHEMA_VERSION


def insert_bank(db: Database, owner_id: ObjectId, name: str) -> dict:
    now = datetime.now(timezone.utc)
    doc = {"ownerId": owner_id, "name": name, "itemIds": [],
           "createdAt": now, "updatedAt": now, "schemaVersion": SCHEMA_VERSION}
    doc["_id"] = db.question_banks.insert_one(doc).inserted_id
    return doc


def find_owned(db: Database, bank_id: ObjectId, owner_id: ObjectId) -> dict | None:
    return db.question_banks.find_one({"_id": bank_id, "ownerId": owner_id})


def list_by_owner(db: Database, owner_id: ObjectId) -> list[dict]:
    """P29：使用 uniq_owner_bank_name 的 ownerId 前缀。"""
    return list(db.question_banks.find({"ownerId": owner_id}).sort("name", 1))


def rename(db: Database, bank_id: ObjectId, owner_id: ObjectId, name: str) -> dict | None:
    return db.question_banks.find_one_and_update(
        {"_id": bank_id, "ownerId": owner_id},
        {"$set": {"name": name, "updatedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def add_item(db: Database, bank_id: ObjectId, owner_id: ObjectId,
             item_id: ObjectId) -> dict | None:
    return db.question_banks.find_one_and_update(
        {"_id": bank_id, "ownerId": owner_id},
        {"$addToSet": {"itemIds": item_id},
         "$set": {"updatedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def remove_item(db: Database, bank_id: ObjectId, owner_id: ObjectId,
                item_id: ObjectId) -> dict | None:
    return db.question_banks.find_one_and_update(
        {"_id": bank_id, "ownerId": owner_id},
        {"$pull": {"itemIds": item_id},
         "$set": {"updatedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def delete_owned(db: Database, bank_id: ObjectId, owner_id: ObjectId) -> bool:
    """只删除题库，不触碰题目身份、版本或问卷引用。"""
    return db.question_banks.delete_one({"_id": bank_id, "ownerId": owner_id}).deleted_count == 1
