"""【第二阶段新增】命名题库管理与收录权限（P29）。"""

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.errors import AppError
from app.repositories import question_banks, question_items, question_versions
from app.services import question_item_service as item_service


def _not_found() -> AppError:
    return AppError(404, "question_bank_not_found", "题库不存在")


def _out(db, doc: dict, include_items: bool = False) -> dict:
    result = {"id": str(doc["_id"]), "name": doc["name"],
              "itemCount": len(doc["itemIds"]), "createdAt": doc["createdAt"],
              "updatedAt": doc["updatedAt"]}
    if include_items:
        items = []
        for item_id in doc["itemIds"]:
            item = question_items.find_by_id(db, item_id)
            available = item is not None and item_service.can_read(item, doc["ownerId"])
            items.append({"itemId": str(item_id), "available": available,
                          "item": item_service.item_out(item, question_versions.find_latest(db, item_id))
                          if available else None})
        result["items"] = items
    return result


def list_banks(db, owner_id: ObjectId) -> list[dict]:
    return [_out(db, bank) for bank in question_banks.list_by_owner(db, owner_id)]


def get_bank(db, bank_id: ObjectId, owner_id: ObjectId) -> dict:
    doc = question_banks.find_owned(db, bank_id, owner_id)
    if doc is None:
        raise _not_found()
    return _out(db, doc, True)


def create_bank(db, owner_id: ObjectId, name: str) -> dict:
    try:
        return _out(db, question_banks.insert_bank(db, owner_id, name))
    except DuplicateKeyError:
        raise AppError(409, "bank_name_taken", "同名题库已存在")


def rename_bank(db, bank_id: ObjectId, owner_id: ObjectId, name: str) -> dict:
    try:
        updated = question_banks.rename(db, bank_id, owner_id, name)
    except DuplicateKeyError:
        raise AppError(409, "bank_name_taken", "同名题库已存在")
    if updated is None:
        raise _not_found()
    return _out(db, updated, True)


def delete_bank(db, bank_id: ObjectId, owner_id: ObjectId) -> None:
    if not question_banks.delete_owned(db, bank_id, owner_id):
        raise _not_found()


def add_item(db, bank_id: ObjectId, owner_id: ObjectId, item_id: ObjectId) -> dict:
    if question_banks.find_owned(db, bank_id, owner_id) is None:
        raise _not_found()
    item_service.get_readable(db, item_id, owner_id)
    updated = question_banks.add_item(db, bank_id, owner_id, item_id)
    if updated is None:
        raise _not_found()
    return _out(db, updated, True)


def remove_item(db, bank_id: ObjectId, owner_id: ObjectId, item_id: ObjectId) -> dict:
    updated = question_banks.remove_item(db, bank_id, owner_id, item_id)
    if updated is None:
        raise _not_found()
    return _out(db, updated, True)
