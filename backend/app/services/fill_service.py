"""填写者一侧：入口状态判断、下一题、提交；以及创作者的预览。"""

from datetime import datetime

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import SCHEMA_VERSION
from app.deps import CurrentUser
from app.errors import AppError
from app.models.public import EntryOut, NextIn, NextOut, PublicOption, PublicQuestion, PublicSurvey, SubmitIn, SubmitOut
from app.models.survey import Completion
from app.repositories import responses as responses_repo
from app.repositories import surveys as surveys_repo
from app.security import submitter_key
from app.services import logic_engine
from app.services.survey_service import deadline_passed, get_owned, is_full, now_utc

ENDED_MESSAGES = {
    "closed": "问卷已关闭",
    "expired": "问卷已过截止时间",
    "full": "问卷已收满",
}


# ---------- 输出 ----------

def to_public(doc: dict, include_questions: bool) -> PublicSurvey:
    questions = []
    if include_questions:
        for i, q in enumerate(logic_engine.visible_questions(doc), start=1):
            questions.append(PublicQuestion(
                question_id=q["questionId"], number=i, type=q["type"], title=q["title"],
                description=q.get("description", ""), required=q["required"],
                options=[PublicOption(option_id=o["optionId"], text=o["text"])
                         for o in q["options"] if not o["hidden"]],
                constraints=q["constraints"],
            ))
    first = logic_engine.first_question_id(doc)
    s = doc["settings"]
    return PublicSurvey(
        slug=doc["slug"], title=doc["title"], description=doc["description"],
        require_login=s["requireLogin"], allow_anonymous=s["allowAnonymous"],
        allow_multiple_submit=s["allowMultipleSubmit"],
        first_question_id=None if first == logic_engine.END else first,
        questions=questions,
    )


# ---------- 入口状态 ----------

def load_public(db: Database, slug: str) -> dict:
    """不存在、已删除、草稿都对外表现为 404。"""
    doc = surveys_repo.find_by_slug(db, slug)
    if doc is None or doc["deletedAt"] is not None or doc["status"] == "draft":
        raise AppError(404, "survey_not_found", "问卷不存在或尚未发布")
    return doc


def _key_for(doc: dict, user: CurrentUser | None) -> str:
    return submitter_key(user.id if user else None, doc["_id"], doc["settings"]["allowAnonymous"])


def entry_state(db: Database, doc: dict, user: CurrentUser | None,
                now: datetime) -> tuple[str, str | None]:
    """判断顺序与页面流程图一致：已结束 → 需登录 → 已填过 → 可填写。"""
    if doc["status"] == "closed":
        return "ended", "closed"
    if deadline_passed(doc["settings"], now):
        return "ended", "expired"
    if is_full(doc):
        return "ended", "full"
    if doc["settings"]["requireLogin"] and user is None:
        return "login_required", None
    if (not doc["settings"]["allowMultipleSubmit"] and user is not None
            and responses_repo.has_single_submission(db, doc["_id"], _key_for(doc, user))):
        return "already_submitted", None
    return "ok", None


def _raise_for_state(state: str, reason: str | None) -> None:
    if state == "ended":
        raise AppError(409, "survey_ended", ENDED_MESSAGES[reason], {"reason": reason})
    if state == "login_required":
        raise AppError(401, "login_required", "该问卷需要登录后填写")
    if state == "already_submitted":
        raise AppError(409, "already_submitted", "你已经填写过该问卷")


def entry(db: Database, slug: str, user: CurrentUser | None) -> EntryOut:
    doc = load_public(db, slug)
    state, reason = entry_state(db, doc, user, now_utc())
    return EntryOut(state=state, reason=reason, survey=to_public(doc, include_questions=state == "ok"))


def _load_fillable(db: Database, slug: str, user: CurrentUser | None) -> dict:
    doc = load_public(db, slug)
    _raise_for_state(*entry_state(db, doc, user, now_utc()))
    return doc


# ---------- 填写 ----------

def _next(doc: dict, body: NextIn) -> NextOut:
    nxt, errors = logic_engine.step(doc, body.question_id, body.value)
    if errors:
        raise AppError(422, "invalid_answer", errors[0]["message"], errors)
    return NextOut(next=nxt)


def next_question(db: Database, slug: str, user: CurrentUser | None, body: NextIn) -> NextOut:
    """P14 只读问卷、不写库。"""
    return _next(_load_fillable(db, slug, user), body)


def submit(db: Database, slug: str, user: CurrentUser | None, body: SubmitIn) -> SubmitOut:
    """P15 提交：重放校验 → 原子占名额 → 插入答卷 → 失败归还名额。"""
    doc = _load_fillable(db, slug, user)

    result = logic_engine.replay(doc, body.answers)
    if not result.ok:
        raise AppError(422, "invalid_answer", result.errors[0]["message"], result.errors)

    now = now_utc()
    if not surveys_repo.reserve_slot(db, doc["_id"], now):
        latest = surveys_repo.find_by_slug(db, slug)
        state, reason = entry_state(db, latest, user, now)
        _raise_for_state(state, reason)
        raise AppError(409, "survey_ended", "问卷当前不可填写", {"reason": None})

    s = doc["settings"]
    response = {
        "surveyId": doc["_id"],
        "surveyVersion": doc["version"],
        "respondentId": user.id if user and not s["allowAnonymous"] else None,
        "submitterKey": _key_for(doc, user),
        "singleSubmission": not s["allowMultipleSubmit"],
        "submittedAt": now,
        "answers": result.answers,
        "path": result.path,
        "schemaVersion": SCHEMA_VERSION,
    }
    try:
        response_id = responses_repo.insert_response(db, response)
    except DuplicateKeyError:
        surveys_repo.release_slot(db, doc["_id"])
        raise AppError(409, "already_submitted", "你已经填写过该问卷")
    except Exception:
        surveys_repo.release_slot(db, doc["_id"])
        raise

    return SubmitOut(
        response_id=str(response_id),
        completion=Completion.model_validate(s["completion"]),
        allow_multiple_submit=s["allowMultipleSubmit"],
    )


# ---------- 预览（P9） ----------

def preview(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> PublicSurvey:
    """创作者本人预览：草稿也可以，不检查状态和登录，不写库。"""
    return to_public(get_owned(db, survey_id, owner_id), include_questions=True)


def preview_next(db: Database, survey_id: ObjectId, owner_id: ObjectId, body: NextIn) -> NextOut:
    return _next(get_owned(db, survey_id, owner_id), body)
