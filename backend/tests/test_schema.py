from datetime import datetime, timezone

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


def make_survey(**over):
    doc = {
        "ownerId": ObjectId(),
        "slug": "abc123XY",
        "title": "水果调查",
        "description": "",
        "allowAnonymous": False,
        "allowMultipleSubmit": False,
        "status": "draft",
        "deadline": None,
        "version": 1,
        "questions": [
            {
                "questionId": "q1",
                "order": 1,
                "type": "single",
                "title": "性别",
                "required": True,
                "options": [{"optionId": "o1", "text": "男"}, {"optionId": "o2", "text": "女"}],
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
                "options": [],
                "constraints": {"min": 0, "max": 120, "integerOnly": True},
                "logic": [{"when": {"op": "between", "value": [0, 17]}, "goto": "END"}],
            },
        ],
        "createdAt": NOW,
        "updatedAt": NOW,
        "schemaVersion": 1,
    }
    doc.update(over)
    return doc


def make_response(survey_id, **over):
    doc = {
        "surveyId": survey_id,
        "surveyVersion": 1,
        "respondentId": ObjectId(),
        "submitterKey": "user-1",
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
    ("deadline", "2026-01-01"),
    ("questions", [{"questionId": "q1", "order": 1, "type": "rating", "title": "x",
                    "required": True, "options": [], "constraints": {}, "logic": []}]),
    ("questions", [{"questionId": "q1", "order": 1, "type": "text", "title": "x",
                    "required": True, "options": [], "constraints": {"foo": 1}, "logic": []}]),
    ("questions", [{"questionId": "q1", "order": 1, "type": "single", "title": "x",
                    "required": True, "options": [], "constraints": {},
                    "logic": [{"when": {"op": "regex", "value": "a"}, "goto": "q2"}]}]),
])
def test_invalid_survey_rejected(db, field, value):
    with pytest.raises(WriteError):
        db.surveys.insert_one(make_survey(**{field: value}))


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
    db.responses.insert_one(make_response(sid, respondentId=None, submitterKey="hmac-abc"))
    with pytest.raises(WriteError):
        db.responses.insert_one(make_response(sid, respondentId="someone", submitterKey="k2"))


def test_init_db_is_idempotent(db):
    from app.db import init_db
    init_db(db)
    names = {ix["name"] for ix in db.responses.list_indexes()}
    assert {"survey_responses", "uniq_single_submission", "respondent"} <= names
