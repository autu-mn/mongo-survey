"""个人主页：我参与的问卷（P22 / P23）与查看我的答卷。"""

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from app.errors import AppError
from app.models.me import InProgressItem, MyAnswerItem, MyOption, MyResponse, Participations, SubmittedItem
from app.repositories import drafts as drafts_repo
from app.repositories import responses as responses_repo
from app.repositories import surveys as surveys_repo
from app.services.survey_service import display_status, now_utc


def participations(db: Database, user_id: ObjectId) -> Participations:
    now = now_utc()
    in_progress = []
    for d in drafts_repo.list_with_surveys(db, user_id):
        s = d["survey"]
        visible = set(s["visibleIds"])
        answered = sum(1 for q in d["path"] if q in visible and d["answers"].get(q) is not None)
        status = display_status(s, now)
        in_progress.append(InProgressItem(
            slug=s["slug"], title=s["title"], display_status=status,
            answered_count=answered, total_questions=len(visible),
            last_visited_at=d["lastVisitedAt"], can_continue=status == "open",
        ))
    submitted = [
        SubmittedItem(response_id=str(r["_id"]), slug=r["survey"]["slug"], title=r["survey"]["title"],
                      display_status=display_status(r["survey"], now), submitted_at=r["submittedAt"])
        for r in responses_repo.list_mine_with_surveys(db, user_id)
    ]
    return Participations(in_progress=in_progress, submitted=submitted)


def my_response(db: Database, user_id: ObjectId, raw_id: str) -> MyResponse:
    not_found = AppError(404, "response_not_found", "答卷不存在")
    try:
        response_id = ObjectId(raw_id)
    except (InvalidId, TypeError):
        raise not_found
    resp = responses_repo.find_mine(db, response_id, user_id)
    survey = surveys_repo.find_active(db, resp["surveyId"]) if resp else None
    if resp is None or survey is None:
        raise not_found

    by_q = {a["questionId"]: a["value"] for a in resp["answers"]}
    items = []
    for q in sorted(survey["questions"], key=lambda x: x["order"]):
        answered = q["questionId"] in by_q
        if q["hidden"] and not answered:
            continue
        value = by_q.get(q["questionId"])
        item = MyAnswerItem(order=q["order"], title=q["title"], type=q["type"],
                            hidden=q["hidden"], answered=answered)
        if q["type"] in ("single", "multiple"):
            chosen = set(value if isinstance(value, list) else [value] if value else [])
            item.options = [MyOption(text=o["text"], chosen=o["optionId"] in chosen, hidden=o["hidden"])
                            for o in q["options"] if not o["hidden"] or o["optionId"] in chosen]
        else:
            item.value = value
        items.append(item)
    return MyResponse(title=survey["title"], slug=survey["slug"], submitted_at=resp["submittedAt"], items=items)
