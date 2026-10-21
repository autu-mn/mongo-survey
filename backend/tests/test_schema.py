from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

NOW = datetime.now(timezone.utc)


def make_user(**over):
    doc = {
        "username": "alice",
        "passwordHash": "$2b$12$" + "x" * 53,
        "createdAt": NOW,
        "schemaVersion": 1,
    }
    doc.update(over)
    return doc


def make_settings(**over):
    s = {
        "requireLogin": True,
        "allowAnonymous": False,
        "allowMultipleSubmit": False,
        "deadline": None,
        "maxResponses": None,
        "completion": {"message": "感谢填写", "redirectUrl": None},
    }
    s.update(over)
    return s


def make_survey(**over):
    doc = {
        "ownerId": ObjectId(),
        "slug": "abc123XY",
        "title": "水果调查",
        "description": "",
        "status": "draft",
        "settings": make_settings(),
        "version": 1,
        "responseCount": 0,
        "questions": [
            {
                "questionId": "q1",
                "order": 1,
                "type": "single",
                "title": "性别",
                "required": True,
                "hidden": False,
                "options": [
                    {"optionId": "o1", "text": "男", "hidden": False},
                    {"optionId": "o2", "text": "女", "hidden": False},
                ],
                "constraints": {},
                "logic": [{"when": {"op": "eq", "value": "o1"}, "goto": "q3"}],
                "defaultGoto": None,
            },
            {
                "questionId": "q2",
                "order": 2,
                "type": "number",
                "title": "年龄",
                "required": False,
                "hidden": False,
                "options": [],
                "constraints": {"min": 0, "max": 120, "integerOnly": True},
                "logic": [{"when": {"op": "between", "value": [0, 17]}, "goto": "END"}],
            },
        ],
        "createdAt": NOW,
        "updatedAt": NOW,
        "deletedAt": None,
        "schemaVersion": 1,
    }
    doc.update(over)
    return doc


def make_question(**over):
    q = {"questionId": "q1", "order": 1, "type": "text", "title": "x", "required": True,
         "hidden": False, "options": [], "constraints": {}, "logic": []}
    q.update(over)
    return q


def make_response(survey_id, **over):
    doc = {
        "surveyId": survey_id,
        "surveyVersion": 1,
        "respondentId": ObjectId(),
        "submitterKey": "u:user-1",
        "singleSubmission": True,
        "submittedAt": NOW,
        "answers": [
            {"questionId": "q1", "type": "single", "value": "o2"},
            {"questionId": "q2", "type": "number", "value": 20},
        ],
        "path": ["q1", "q2"],
        "schemaVersion": 1,
    }
    doc.update(over)
    return doc


def test_valid_documents_accepted(db):
    db.users.insert_one(make_user())
    sid = db.surveys.insert_one(make_survey()).inserted_id
    db.responses.insert_one(make_response(sid))
    assert db.responses.count_documents({"surveyId": sid}) == 1


def test_username_unique(db):
    db.users.insert_one(make_user())
    with pytest.raises(DuplicateKeyError):
        db.users.insert_one(make_user())


def test_user_unknown_field_rejected(db):
    with pytest.raises(WriteError):
        db.users.insert_one(make_user(password="plain"))


def test_slug_unique_and_pattern(db):
    db.surveys.insert_one(make_survey())
    with pytest.raises(DuplicateKeyError):
        db.surveys.insert_one(make_survey())
    with pytest.raises(WriteError):
        db.surveys.insert_one(make_survey(slug="a b"))


@pytest.mark.parametrize("field,value", [
    ("status", "archived"),
    ("responseCount", -1),
    ("deletedAt", "yesterday"),
    ("questions", [make_question(type="rating")]),
    ("questions", [make_question(constraints={"foo": 1})]),
    ("questions", [make_question(type="single",
                                 logic=[{"when": {"op": "regex", "value": "a"}, "goto": "q2"}])]),
    ("questions", [make_question(type="single", options=[{"optionId": "o1", "text": "A"}])]),
    ("settings", make_settings(deadline="2026-01-01")),
    ("settings", make_settings(maxResponses=0)),
    ("settings", make_settings(completion={"message": "", "redirectUrl": "javascript:alert(1)"})),
    ("settings", {"requireLogin": True}),
])
def test_invalid_survey_rejected(db, field, value):
    with pytest.raises(WriteError):
        db.surveys.insert_one(make_survey(**{field: value}))


def test_completion_redirect_https_accepted(db):
    s = make_settings(completion={"message": "谢谢", "redirectUrl": "https://example.com/thanks"})
    db.surveys.insert_one(make_survey(settings=s))


def test_single_submission_enforced_by_partial_index(db):
    sid = db.surveys.insert_one(make_survey()).inserted_id
    db.responses.insert_one(make_response(sid))
    with pytest.raises(DuplicateKeyError):
        db.responses.insert_one(make_response(sid))


def test_multiple_submission_allowed_when_not_single(db):
    sid = db.surveys.insert_one(make_survey()).inserted_id
    db.responses.insert_one(make_response(sid, singleSubmission=False))
    db.responses.insert_one(make_response(sid, singleSubmission=False))
    assert db.responses.count_documents({"surveyId": sid}) == 2


def test_anonymous_response_has_null_respondent(db):
    sid = db.surveys.insert_one(make_survey()).inserted_id
    db.responses.insert_one(make_response(sid, respondentId=None, submitterKey="a:hmac-abc"))
    with pytest.raises(WriteError):
        db.responses.insert_one(make_response(sid, respondentId="someone", submitterKey="k2"))


def test_max_responses_quota_under_concurrency(db):
    """20 个并发占位请求，上限 5，只能有 5 个成功。"""
    sid = db.surveys.insert_one(
        make_survey(status="published", settings=make_settings(maxResponses=5))
    ).inserted_id

    def reserve(_):
        res = db.surveys.update_one(
            {
                "_id": sid,
                "status": "published",
                "$or": [
                    {"settings.maxResponses": None},
                    {"$expr": {"$lt": ["$responseCount", "$settings.maxResponses"]}},
                ],
            },
            {"$inc": {"responseCount": 1}},
        )
        return res.modified_count

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(reserve, range(20)))

    assert sum(results) == 5
    assert db.surveys.find_one({"_id": sid})["responseCount"] == 5


def test_owner_list_uses_index_without_sort(db):
    owner = ObjectId()
    for i in range(30):
        db.surveys.insert_one(make_survey(
            ownerId=owner if i % 2 else ObjectId(),
            slug=f"slug{i:04d}",
            createdAt=NOW - timedelta(minutes=i),
            deletedAt=None if i % 3 else NOW,
        ))
    cursor = db.surveys.find({"ownerId": owner, "deletedAt": None}).sort("createdAt", -1)
    plan = cursor.explain()["queryPlanner"]["winningPlan"]
    plan_text = str(plan)
    assert "owner_active_list" in plan_text
    assert "'stage': 'SORT'" not in plan_text
    assert all(d["deletedAt"] is None for d in cursor.clone())


def test_init_db_is_idempotent_and_drops_stale_index(db):
    from app.db import init_db
    db.surveys.create_index([("ownerId", 1), ("createdAt", -1)], name="owner_list")
    init_db(db)
    names = {ix["name"] for ix in db.surveys.list_indexes()}
    assert names == {"_id_", "uniq_slug", "owner_active_list"}
    names = {ix["name"] for ix in db.responses.list_indexes()}
    assert {"survey_responses", "uniq_single_submission", "respondent"} <= names
