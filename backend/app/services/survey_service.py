from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from app.errors import AppError
from app.models.survey import Settings, SurveyCreate, SurveyDetail, SurveyListItem
from app.repositories import surveys as repo


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_survey_id(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except (InvalidId, TypeError):
        raise not_found()


def not_found() -> AppError:
    # 别人的问卷与不存在的问卷返回相同结果，不暴露问卷是否存在
    return AppError(404, "survey_not_found", "问卷不存在")


def deadline_passed(settings: dict, now: datetime) -> bool:
    deadline = settings.get("deadline")
    return deadline is not None and deadline <= now


def is_full(doc: dict) -> bool:
    limit = doc["settings"].get("maxResponses")
    return limit is not None and doc.get("responseCount", 0) >= limit


def display_status(doc: dict, now: datetime) -> str:
    """列表和管理页显示的状态。已截止、已满额不存库，按当前时间和计数实时得出。"""
    if doc["status"] != "published":
        return doc["status"]
    if deadline_passed(doc["settings"], now):
        return "expired"
    if is_full(doc):
        return "full"
    return "open"


def to_list_item(doc: dict, now: datetime) -> SurveyListItem:
    return SurveyListItem(
        id=str(doc["_id"]),
        title=doc["title"],
        slug=doc["slug"],
        status=doc["status"],
        display_status=display_status(doc, now),
        response_count=doc["responseCount"],
        deadline=doc["settings"].get("deadline"),
        max_responses=doc["settings"].get("maxResponses"),
        created_at=doc["createdAt"],
        updated_at=doc["updatedAt"],
    )


def to_detail(doc: dict, now: datetime) -> SurveyDetail:
    base = to_list_item(doc, now).model_dump()
    # 【第二阶段修改】来源 ID 在库中为 ObjectId，API 输出为字符串。
    questions = []
    for question in doc["questions"]:
        out = dict(question)
        for key in ("sourceItemId", "sourceVersionId"):
            if out.get(key) is not None:
                out[key] = str(out[key])
        questions.append(out)
    return SurveyDetail(
        **base,
        description=doc["description"],
        settings=Settings.from_doc(doc["settings"]),
        version=doc["version"],
        question_count=sum(1 for q in doc["questions"] if not q["hidden"]),
        published_at=doc.get("publishedAt"),
        closed_at=doc.get("closedAt"),
        questions=questions,
    )


def get_owned(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    doc = repo.find_owned(db, survey_id, owner_id)
    if doc is None:
        raise not_found()
    return doc


def create_survey(db: Database, owner_id: ObjectId, body: SurveyCreate) -> dict:
    return repo.insert_survey(db, owner_id, body.title, body.description, Settings().to_doc())


def list_surveys(db: Database, owner_id: ObjectId) -> list[SurveyListItem]:
    now = now_utc()
    return [to_list_item(d, now) for d in repo.list_by_owner(db, owner_id)]


def update_settings(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                    settings: Settings) -> dict:
    doc = repo.set_settings(db, survey_id, owner_id, settings.to_doc())
    if doc is None:
        raise not_found()
    return doc


def _open_filter(now: datetime) -> dict:
    """发布 / 重新开放的前提：至少一道未隐藏的题，且截止时间未过。"""
    return {
        "questions": {"$elemMatch": {"hidden": False}},
        "$or": [{"settings.deadline": None}, {"settings.deadline": {"$gt": now}}],
    }


def _explain_open_failure(doc: dict, expected_status: str, now: datetime) -> AppError:
    if doc["status"] != expected_status:
        return AppError(409, "invalid_transition",
                        f"当前状态为 {doc['status']}，不能执行该操作")
    if not any(not q["hidden"] for q in doc["questions"]):
        return AppError(409, "no_questions", "问卷至少需要一道题目才能发布")
    if deadline_passed(doc["settings"], now):
        return AppError(409, "deadline_passed", "截止时间已过，请先修改截止时间")
    return AppError(409, "conflict", "操作失败，请刷新后重试")


def publish(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    now = now_utc()
    # 【第二阶段修改】发布前给未关联题目固定来源，发布和快照写入同一次原子状态流转。
    current = get_owned(db, survey_id, owner_id)
    if current["status"] != "draft" or not any(not q["hidden"] for q in current["questions"]) or deadline_passed(current["settings"], now):
        raise _explain_open_failure(current, "draft", now)
    from app.services.library_service import ensure_source
    import copy

    questions = copy.deepcopy(current["questions"])
    for q in questions:
        item_id, version_id = ensure_source(db, survey_id, owner_id, q)
        q["sourceItemId"] = item_id
        q["sourceVersionId"] = version_id
    doc = repo.transition_status(db, survey_id, owner_id, ["draft"], "published",
                                 extra_filter={**_open_filter(now), "updatedAt": current["updatedAt"]},
                                 extra_set={"publishedAt": now, "questions": questions})
    if doc is None:
        raise _explain_open_failure(get_owned(db, survey_id, owner_id), "draft", now)
    return doc


def copy_survey(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    source = get_owned(db, survey_id, owner_id)
    return repo.copy_as_draft(db, source)


def reopen(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    now = now_utc()
    doc = repo.transition_status(db, survey_id, owner_id, ["closed"], "published",
                                 extra_filter=_open_filter(now),
                                 extra_set={"closedAt": None})
    if doc is None:
        raise _explain_open_failure(get_owned(db, survey_id, owner_id), "closed", now)
    return doc


def close(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    doc = repo.transition_status(db, survey_id, owner_id, ["published"], "closed",
                                 extra_set={"closedAt": now_utc()})
    if doc is None:
        current = get_owned(db, survey_id, owner_id)
        raise AppError(409, "invalid_transition",
                       f"当前状态为 {current['status']}，只有已发布的问卷可以关闭")
    return doc


def delete(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> None:
    if not repo.soft_delete(db, survey_id, owner_id):
        raise not_found()


def recount(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> dict:
    doc = repo.recount_responses(db, survey_id, owner_id)
    if doc is None:
        raise not_found()
    return doc
