from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.repositories import surveys as surveys_repo
from tests.conftest import register_and_login

NOW = datetime.now(timezone.utc)


def visible_question(qid="q1", order=1, hidden=False):
    return {"questionId": qid, "order": order, "type": "text", "title": "意见",
            "required": False, "hidden": hidden, "options": [], "constraints": {}, "logic": []}


@pytest.fixture
def alice(client):
    return register_and_login(client, "alice")


@pytest.fixture
def bob(client):
    return register_and_login(client, "bob")


def create(client, headers, title="水果调查"):
    r = client.post("/api/surveys", json={"title": title, "description": "说明"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def add_question_directly(db, survey_id, **kw):
    """第 5 步编辑器完成前，直接写库模拟"已添加题目"。"""
    db.surveys.update_one({"_id": ObjectId(survey_id)},
                          {"$push": {"questions": visible_question(**kw)}})


def published(client, db, headers):
    s = create(client, headers)
    add_question_directly(db, s["id"])
    r = client.post(f"/api/surveys/{s['id']}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 新建与默认值 ----------

def test_create_defaults(client, alice):
    s = create(client, alice)
    assert s["status"] == "draft" and s["displayStatus"] == "draft"
    assert len(s["slug"]) == 8 and s["slug"].isalnum()
    assert s["responseCount"] == 0 and s["version"] == 1 and s["questions"] == []
    assert s["settings"] == {
        "requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": False,
        "deadline": None, "maxResponses": None,
        "completion": {"message": "感谢您的填写！", "redirectUrl": None},
    }


@pytest.mark.parametrize("payload", [{"title": ""}, {"title": "x" * 201}, {}])
def test_create_invalid(client, alice, payload):
    assert client.post("/api/surveys", json=payload, headers=alice).status_code == 422


def test_create_requires_login(client):
    r = client.post("/api/surveys", json={"title": "x"})
    assert r.status_code == 401 and r.json()["code"] == "login_required"


def test_slug_collision_retries(client, alice, monkeypatch):
    slugs = iter(["SAMESLUG", "SAMESLUG", "OTHERSLG"])
    monkeypatch.setattr(surveys_repo, "generate_slug", lambda: next(slugs))
    assert create(client, alice)["slug"] == "SAMESLUG"
    assert create(client, alice)["slug"] == "OTHERSLG"


# ---------- 列表与权限 ----------

def test_list_only_own_sorted_desc(client, alice, bob):
    create(client, alice, "A1")
    create(client, bob, "B1")
    create(client, alice, "A2")
    r = client.get("/api/surveys", headers=alice)
    assert [s["title"] for s in r.json()] == ["A2", "A1"]
    assert "questions" not in r.json()[0]


@pytest.mark.parametrize("method,path", [
    ("get", ""), ("delete", ""), ("get", "/settings"), ("post", "/publish"),
    ("post", "/close"), ("post", "/reopen"), ("post", "/recount"),
])
def test_other_users_survey_is_404(client, alice, bob, method, path):
    s = create(client, alice)
    r = getattr(client, method)(f"/api/surveys/{s['id']}{path}", headers=bob)
    assert r.status_code == 404 and r.json()["code"] == "survey_not_found"


def test_bad_id_is_404(client, alice):
    assert client.get("/api/surveys/not-an-id", headers=alice).status_code == 404
    assert client.get(f"/api/surveys/{ObjectId()}", headers=alice).status_code == 404


# ---------- 分享设置 ----------

def test_settings_roundtrip(client, alice):
    s = create(client, alice)
    body = {
        "requireLogin": True, "allowAnonymous": True, "allowMultipleSubmit": True,
        "deadline": "2030-01-01T00:00:00+08:00", "maxResponses": 100,
        "completion": {"message": "谢谢", "redirectUrl": "https://example.com/x"},
    }
    r = client.put(f"/api/surveys/{s['id']}/settings", json=body, headers=alice)
    assert r.status_code == 200, r.text
    got = client.get(f"/api/surveys/{s['id']}/settings", headers=alice).json()
    assert got["allowAnonymous"] is True and got["maxResponses"] == 100
    assert datetime.fromisoformat(got["deadline"]) == datetime(2029, 12, 31, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize("patch", [
    {"requireLogin": False, "allowMultipleSubmit": False},
    {"maxResponses": 0},
    {"deadline": "2030-01-01T00:00:00"},
    {"completion": {"message": "x", "redirectUrl": "javascript:alert(1)"}},
])
def test_settings_invalid(client, alice, patch):
    s = create(client, alice)
    body = {"requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": False,
            "deadline": None, "maxResponses": None,
            "completion": {"message": "", "redirectUrl": None}} | patch
    r = client.put(f"/api/surveys/{s['id']}/settings", json=body, headers=alice)
    assert r.status_code == 422


def test_guest_fill_allowed_only_with_multiple_submit(client, alice):
    s = create(client, alice)
    body = {"requireLogin": False, "allowMultipleSubmit": True}
    r = client.put(f"/api/surveys/{s['id']}/settings", json=body, headers=alice)
    assert r.status_code == 200 and r.json()["requireLogin"] is False


# ---------- 状态流转 ----------

def test_publish_requires_visible_question(client, db, alice):
    s = create(client, alice)
    r = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "no_questions"
    add_question_directly(db, s["id"], hidden=True)
    r = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert r.json()["code"] == "no_questions"


def test_publish_success_and_not_twice(client, db, alice):
    s = published(client, db, alice)
    assert s["status"] == "published" and s["displayStatus"] == "open" and s["publishedAt"]
    r = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"


def test_publish_rejected_when_deadline_passed(client, db, alice):
    s = create(client, alice)
    add_question_directly(db, s["id"])
    client.put(f"/api/surveys/{s['id']}/settings", headers=alice,
               json={"deadline": (NOW - timedelta(hours=1)).isoformat()})
    r = client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "deadline_passed"


def test_close_and_reopen(client, db, alice):
    s = published(client, db, alice)
    r = client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    assert r.json()["status"] == "closed" and r.json()["closedAt"]
    assert client.post(f"/api/surveys/{s['id']}/close", headers=alice).status_code == 409
    r = client.post(f"/api/surveys/{s['id']}/reopen", headers=alice)
    assert r.json()["status"] == "published" and r.json()["closedAt"] is None


def test_cannot_close_draft_or_reopen_published(client, db, alice):
    s = create(client, alice)
    assert client.post(f"/api/surveys/{s['id']}/close", headers=alice).status_code == 409
    p = published(client, db, alice)
    assert client.post(f"/api/surveys/{p['id']}/reopen", headers=alice).status_code == 409


def test_display_status_expired_and_full(client, db, alice):
    s = published(client, db, alice)
    sid = ObjectId(s["id"])
    db.surveys.update_one({"_id": sid}, {"$set": {"settings.maxResponses": 2, "responseCount": 2}})
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).json()["displayStatus"] == "full"
    db.surveys.update_one({"_id": sid}, {"$set": {"settings.deadline": NOW - timedelta(seconds=1)}})
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).json()["displayStatus"] == "expired"


# ---------- 软删除与计数校准 ----------

def test_soft_delete(client, db, alice):
    s = create(client, alice)
    assert client.delete(f"/api/surveys/{s['id']}", headers=alice).status_code == 204
    assert client.get("/api/surveys", headers=alice).json() == []
    assert client.get(f"/api/surveys/{s['id']}", headers=alice).status_code == 404
    assert client.delete(f"/api/surveys/{s['id']}", headers=alice).status_code == 404
    doc = db.surveys.find_one({"_id": ObjectId(s["id"])})
    assert doc is not None and doc["deletedAt"] is not None


def test_recount(client, db, alice):
    s = published(client, db, alice)
    sid = ObjectId(s["id"])
    for i in range(3):
        db.responses.insert_one({
            "surveyId": sid, "surveyVersion": 1, "respondentId": None,
            "submitterKey": f"g:{i}", "singleSubmission": False, "submittedAt": NOW,
            "answers": [], "path": [], "schemaVersion": 1,
        })
    db.surveys.update_one({"_id": sid}, {"$set": {"responseCount": 7}})
    r = client.post(f"/api/surveys/{s['id']}/recount", headers=alice)
    assert r.json()["responseCount"] == 3
