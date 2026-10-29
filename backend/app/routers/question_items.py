"""【第二阶段新增】题目版本和共享 API。"""

from fastapi import APIRouter, Query

from app.deps import DB, RequiredUser
from app.models.question_item import ItemCreate, SharingUpdate, VersionCreate
from app.services import question_item_service as svc
from app.services import library_service
from app.services import cross_stats_service
from app.repositories import question_versions, users

router = APIRouter(prefix="/api/question-items", tags=["题目版本与共享"])


@router.get("")
def list_items(user: RequiredUser, db: DB, scope: str = "mine", limit: int = Query(50, ge=1, le=100),
               offset: int = Query(0, ge=0)):
    return svc.list_items(db, user.id, scope, limit, offset)


@router.post("", status_code=201)
def create_item(body: ItemCreate, user: RequiredUser, db: DB):
    return svc.create_item(db, user.id, body)


@router.get("/{item_id}")
def get_item(item_id: str, user: RequiredUser, db: DB):
    item = svc.get_readable_history(db, svc.parse_id(item_id), user.id)
    result = svc.item_out(item, question_versions.find_latest(db, item["_id"]))
    result["canSelectNew"] = svc.can_read(item, user.id)
    if item["ownerId"] == user.id:
        names = users.usernames(db, item["sharedUserIds"])
        result["sharedUsernames"] = [names[uid] for uid in item["sharedUserIds"] if uid in names]
    return result


@router.get("/{item_id}/versions")
def list_versions(item_id: str, user: RequiredUser, db: DB):
    return svc.list_versions(db, svc.parse_id(item_id), user.id)


@router.get("/{item_id}/usage")
def usage(item_id: str, user: RequiredUser, db: DB):
    return library_service.usage(db, svc.parse_id(item_id), user.id)


@router.get("/{item_id}/versions/{version_id}/stats")
def version_stats(item_id: str, version_id: str, user: RequiredUser, db: DB):
    return cross_stats_service.version_stats(db, svc.parse_id(item_id),
                                             svc.parse_id(version_id), user.id)


@router.post("/{item_id}/versions", status_code=201)
def create_version(item_id: str, body: VersionCreate, user: RequiredUser, db: DB):
    return svc.create_version(db, svc.parse_id(item_id), user.id, body)


@router.put("/{item_id}/sharing")
def update_sharing(item_id: str, body: SharingUpdate, user: RequiredUser, db: DB):
    return svc.update_sharing(db, svc.parse_id(item_id), user.id, body)
