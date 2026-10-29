"""【第二阶段新增】题目身份、版本历史及共享授权（P24–P28）。"""

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.errors import AppError
from app.models.question import QuestionIn
from app.models.question_item import ItemCreate, SharingUpdate, VersionCreate
from app.repositories import question_items, question_versions, users
from app.services import question_service, rule_checker


def parse_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise AppError(422, "validation_error", "ID 格式不正确")


def can_read(item: dict, user_id: ObjectId) -> bool:
    return (item["ownerId"] == user_id or item["visibility"] == "public"
            or (item["visibility"] == "selected" and user_id in item["sharedUserIds"]))


def get_readable(db, item_id: ObjectId, user_id: ObjectId) -> dict:
    item = question_items.find_by_id(db, item_id)
    if item is None or not can_read(item, user_id):
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    return item


def get_readable_history(db, item_id: ObjectId, user_id: ObjectId) -> dict:
    """既有本人问卷可看历史与统计；选入新问卷仍使用当前共享权限。"""
    item = question_items.find_by_id(db, item_id)
    if item is None or (not can_read(item, user_id)
                        and not question_items.has_owned_reference(db, item_id, user_id)):
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    return item


def get_owned(db, item_id: ObjectId, user_id: ObjectId) -> dict:
    item = question_items.find_by_id(db, item_id)
    if item is None or item["ownerId"] != user_id:
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    return item


def version_out(version: dict) -> dict:
    return {"id": str(version["_id"]), "itemId": str(version["itemId"]),
            "versionNo": version["versionNo"],
            "parentVersionId": str(version["parentVersionId"]) if version["parentVersionId"] else None,
            "content": {key: version[key] for key in question_versions.CONTENT_FIELDS},
            "createdAt": version["createdAt"]}


def item_out(item: dict, latest: dict | None) -> dict:
    return {"id": str(item["_id"]), "ownerId": str(item["ownerId"]),
            "visibility": item["visibility"],
            "sharedUserIds": [str(uid) for uid in item["sharedUserIds"]],
            "createdAt": item["createdAt"], "updatedAt": item["updatedAt"],
            "latestVersion": version_out(latest) if latest else None}


def _content_from_input(body: QuestionIn, parent: dict | None = None) -> dict:
    old = None
    if parent is not None:
        old = {**parent, "questionId": "item"}
    taken = {o["optionId"] for o in parent["options"]} if parent else set()
    options = question_service._build_options(body, old, taken)
    content = {"type": body.type, "title": body.title, "description": body.description,
               "required": body.required, "options": options,
               "constraints": body.constraints.to_doc()}
    synthetic = {**content, "questionId": "item", "order": 1, "hidden": False,
                 "logic": [], "defaultGoto": None}
    errors = rule_checker.check_questions([synthetic])
    if errors:
        raise AppError(422, "invalid_question", "题目设置不合法", errors)
    return content


def list_items(db, user_id: ObjectId, scope: str, limit: int, offset: int) -> list[dict]:
    if scope == "mine":
        items = question_items.list_owned(db, user_id, limit, offset)
    elif scope == "shared":
        public = question_items.list_public(db, limit + offset)
        selected = question_items.list_shared_with(db, user_id, limit + offset)
        items = sorted({i["_id"]: i for i in public + selected if i["ownerId"] != user_id}.values(),
                       key=lambda i: (i["createdAt"], i["_id"]), reverse=True)[offset:offset + limit]
    else:
        raise AppError(422, "validation_error", "scope 必须是 mine 或 shared")
    return [item_out(item, question_versions.find_latest(db, item["_id"])) for item in items]


def create_item(db, user_id: ObjectId, body: ItemCreate) -> dict:
    if body.source_version_id:
        source = question_versions.find_by_id(db, parse_id(body.source_version_id))
        if source is None:
            raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
        get_readable(db, source["itemId"], user_id)
        content = {key: source[key] for key in question_versions.CONTENT_FIELDS}
    else:
        content = _content_from_input(body.content)
    item = question_items.insert_item(db, user_id)
    version = question_versions.insert_version(db, item["_id"], 1, None, content)
    return item_out(item, version)


def list_versions(db, item_id: ObjectId, user_id: ObjectId) -> list[dict]:
    get_readable_history(db, item_id, user_id)
    return [version_out(v) for v in question_versions.list_by_item(db, item_id)]


def create_version(db, item_id: ObjectId, user_id: ObjectId, body: VersionCreate) -> dict:
    get_owned(db, item_id, user_id)
    parent = question_versions.find_by_id(db, parse_id(body.parent_version_id))
    if parent is None or parent["itemId"] != item_id:
        raise AppError(422, "invalid_parent_version", "父版本不属于这道题")
    content = _content_from_input(body.content, parent) if body.content else {
        key: parent[key] for key in question_versions.CONTENT_FIELDS}
    for _ in range(8):
        latest = question_versions.find_latest(db, item_id)
        number = latest["versionNo"] + 1
        try:
            return version_out(question_versions.insert_version(db, item_id, number,
                                                                 parent["_id"], content))
        except DuplicateKeyError:
            continue
    raise AppError(409, "version_conflict", "同时创建版本发生冲突，请重试")


def update_sharing(db, item_id: ObjectId, user_id: ObjectId, body: SharingUpdate) -> dict:
    get_owned(db, item_id, user_id)
    targets = []
    for username in body.usernames:
        target = users.find_by_username(db, username)
        if target is None:
            raise AppError(422, "unknown_share_user", f"用户 {username} 不存在")
        if target["_id"] == user_id:
            raise AppError(422, "invalid_share_user", "无需把题目共享给自己")
        targets.append(target["_id"])
    updated = question_items.set_sharing(db, item_id, user_id, body.visibility, targets)
    if updated is None:
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    return item_out(updated, question_versions.find_latest(db, item_id))
