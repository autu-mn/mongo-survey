"""断点续填（drafts）与"我参与的问卷"测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.config import settings
from tests.conftest import register_and_login
from tests.helpers import build_demo_survey, opt

MULTI = {"requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": True,
         "deadline": None, "maxResponses": None}


@pytest.fixture
def alice(client):
    return register_and_login(client, "alice")


@pytest.fixture
def bob(client):
    return register_and_login(client, "bob")


def entry(client, slug, headers=None):
    return client.get(f"/api/public/surveys/{slug}", headers=headers or {}).json()


def nxt(client, slug, headers, qid, value):
    r = client.post(f"/api/public/surveys/{slug}/next", json={"questionId": qid, "value": value}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["next"]


def draft_of(db, username, survey_id):
    uid = db.users.find_one({"username": username})["_id"]
    return db.drafts.find_one({"userId": uid, "surveyId": ObjectId(survey_id)})


# ---------- 记录访问与保存进度 ----------

def test_entry_creates_draft_for_logged_in_user_only(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice, settings={**MULTI, "requireLogin": False})
    entry(client, s["slug"])                        # 访客
    assert db.drafts.count_documents({}) == 0
    body = entry(client, s["slug"], bob)
    assert body["draft"]["path"] == [qs["q1"]["questionId"]] and body["draft"]["answers"] == {}
    entry(client, s["slug"], bob)                   # 再次访问不会产生第二份
    assert db.drafts.count_documents({}) == 1


def test_next_saves_answer_and_path(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q2, q3 = qs["q1"], qs["q2"], qs["q3"]
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "女"))
    nxt(client, s["slug"], bob, q2["questionId"], [opt(q2, "苹果"), opt(q2, "香蕉")])
    nxt(client, s["slug"], bob, q3["questionId"], "30")
    d = draft_of(db, "bob", s["id"])
    assert d["path"] == [q1["questionId"], q2["questionId"], q3["questionId"], qs["q4"]["questionId"]]
    assert d["answers"][q3["questionId"]] == 30          # 保存规范化后的数值
    assert entry(client, s["slug"], bob)["draft"]["path"][-1] == qs["q4"]["questionId"]


def test_changing_earlier_answer_truncates_path(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q2, q3 = qs["q1"], qs["q2"], qs["q3"]
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "女"))                       # 女 → Q2
    nxt(client, s["slug"], bob, q2["questionId"], [opt(q2, "苹果"), opt(q2, "香蕉")])   # → Q3
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "男"))                       # 回到 Q1 改成男 → Q3
    d = draft_of(db, "bob", s["id"])
    assert d["path"] == [q1["questionId"], q3["questionId"]]


def test_last_question_ends_path(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q3 = qs["q1"], qs["q3"]
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "男"))
    assert nxt(client, s["slug"], bob, q3["questionId"], 10) == "END"
    assert draft_of(db, "bob", s["id"])["path"] == [q1["questionId"], q3["questionId"]]


def test_text_answer_starting_with_dollar_is_stored_literally(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q3, q4 = qs["q1"], qs["q3"], qs["q4"]
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "男"))
    nxt(client, s["slug"], bob, q3["questionId"], 30)
    nxt(client, s["slug"], bob, q4["questionId"], "$path")
    assert draft_of(db, "bob", s["id"])["answers"][q4["questionId"]] == "$path"


def test_next_without_entry_still_creates_draft(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    nxt(client, s["slug"], bob, qs["q1"]["questionId"], opt(qs["q1"], "女"))
    d = draft_of(db, "bob", s["id"])
    assert d["path"] == [qs["q1"]["questionId"], qs["q2"]["questionId"]] and d["surveyVersion"] == s["version"]


# ---------- 进度作废、重新开始、提交后删除 ----------

def test_draft_discarded_when_survey_changed(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, qs["q1"]["questionId"], opt(qs["q1"], "女"))
    client.put(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}/logic", headers=alice, json={"rules": []})
    client.post(f"/api/surveys/{s['id']}/questions", headers=alice,
                json={"type": "text", "title": "新增的题"})         # version + 1
    body = entry(client, s["slug"], bob)
    assert body["draftDiscarded"] is True
    assert body["draft"]["path"] == [qs["q1"]["questionId"]] and body["draft"]["answers"] == {}


def test_restart_deletes_draft(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    entry(client, s["slug"], bob)
    assert client.delete(f"/api/public/surveys/{s['slug']}/draft", headers=bob).status_code == 204
    assert draft_of(db, "bob", s["id"]) is None
    assert client.delete(f"/api/public/surveys/{s['slug']}/draft").status_code == 401


def test_submit_deletes_draft(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q3 = qs["q1"], qs["q3"]
    entry(client, s["slug"], bob)
    nxt(client, s["slug"], bob, q1["questionId"], opt(q1, "男"))
    r = client.post(f"/api/public/surveys/{s['slug']}/responses", headers=bob,
                    json={"answers": {q1["questionId"]: opt(q1, "男"), q3["questionId"]: 10}})
    assert r.status_code == 201
    assert draft_of(db, "bob", s["id"]) is None


def test_no_draft_when_survey_not_fillable(client, db, alice, bob):
    s, _ = build_demo_survey(client, alice)
    client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    assert entry(client, s["slug"], bob)["draft"] is None
    assert db.drafts.count_documents({}) == 0


# ---------- 我参与的问卷 ----------

def test_participations(client, db, alice, bob):
    s1, q1s = build_demo_survey(client, alice, settings=MULTI)        # bob 填写中
    s2, q2s = build_demo_survey(client, alice)                        # bob 已提交（实名）
    s3, q3s = build_demo_survey(client, alice, settings={**MULTI, "allowAnonymous": True})  # bob 已提交（匿名）

    entry(client, s1["slug"], bob)
    nxt(client, s1["slug"], bob, q1s["q1"]["questionId"], opt(q1s["q1"], "女"))
    for s, qs in ((s2, q2s), (s3, q3s)):
        client.post(f"/api/public/surveys/{s['slug']}/responses", headers=bob, json={"answers": {
            qs["q1"]["questionId"]: opt(qs["q1"], "男"), qs["q3"]["questionId"]: 10}})

    body = client.get("/api/me/participations", headers=bob).json()
    assert [x["slug"] for x in body["inProgress"]] == [s1["slug"]]
    item = body["inProgress"][0]
    assert item["answeredCount"] == 1 and item["totalQuestions"] == 4 and item["canContinue"] is True
    assert [x["slug"] for x in body["submitted"]] == [s2["slug"]]      # 匿名答卷不出现

    assert client.get("/api/me/participations", headers=alice).json() == {"inProgress": [], "submitted": []}


def test_participations_hide_deleted_and_mark_closed(client, db, alice, bob):
    s1, _ = build_demo_survey(client, alice)
    s2, _ = build_demo_survey(client, alice)
    entry(client, s1["slug"], bob)
    entry(client, s2["slug"], bob)
    client.delete(f"/api/surveys/{s1['id']}", headers=alice)
    client.post(f"/api/surveys/{s2['id']}/close", headers=alice)
    items = client.get("/api/me/participations", headers=bob).json()["inProgress"]
    assert [x["slug"] for x in items] == [s2["slug"]]
    assert items[0]["displayStatus"] == "closed" and items[0]["canContinue"] is False


def test_participations_requires_login(client):
    assert client.get("/api/me/participations").status_code == 401


# ---------- 查看我的答卷 ----------

def test_my_response(client, db, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1, q3 = qs["q1"], qs["q3"]
    client.post(f"/api/public/surveys/{s['slug']}/responses", headers=bob,
                json={"answers": {q1["questionId"]: opt(q1, "男"), q3["questionId"]: 10}})
    rid = client.get("/api/me/participations", headers=bob).json()["submitted"][0]["responseId"]

    body = client.get(f"/api/me/responses/{rid}", headers=bob).json()
    assert body["title"] == "示例问卷" and len(body["items"]) == 4
    first, second, third = body["items"][:3]
    assert [o["text"] for o in first["options"] if o["chosen"]] == ["男"]
    assert second["answered"] is False                             # 被跳过的 Q2
    assert third["value"] == 10

    assert client.get(f"/api/me/responses/{rid}", headers=alice).status_code == 404   # 别人的答卷
    assert client.get("/api/me/responses/not-an-id", headers=bob).status_code == 404


# ---------- 数据库层 ----------

def test_unique_and_ttl_indexes(db):
    idx = {i["name"]: i for i in db.drafts.list_indexes()}
    assert idx["uniq_user_survey"]["unique"] is True
    assert idx["ttl_last_visited"]["expireAfterSeconds"] == settings.draft_ttl_days * 86400
    now = datetime.now(timezone.utc)
    doc = {"userId": ObjectId(), "surveyId": ObjectId(), "surveyVersion": 1, "answers": {}, "path": [],
           "createdAt": now, "lastVisitedAt": now, "schemaVersion": 1}
    db.drafts.insert_one(dict(doc))
    with pytest.raises(DuplicateKeyError):
        db.drafts.insert_one(dict(doc))


def test_participation_queries_use_indexes(client, db, alice, bob):
    s, _ = build_demo_survey(client, alice)
    entry(client, s["slug"], bob)
    uid = db.users.find_one({"username": "bob"})["_id"]
    drafts_plan = db.drafts.find({"userId": uid}).sort("lastVisitedAt", -1).explain()["queryPlanner"]["winningPlan"]
    assert "user_recent" in str(drafts_plan) and "'stage': 'SORT'" not in str(drafts_plan)
    resp_plan = db.responses.find({"respondentId": uid}).sort("submittedAt", -1).explain()["queryPlanner"]["winningPlan"]
    assert "respondent_history" in str(resp_plan) and "'stage': 'SORT'" not in str(resp_plan)


def test_draft_older_than_ttl_is_eligible_for_removal(db):
    """TTL 后台任务每 60 秒运行一次，测试中只验证过期判定条件：超过期限的文档会被索引选中。"""
    old = datetime.now(timezone.utc) - timedelta(days=settings.draft_ttl_days + 1)
    db.drafts.insert_one({"userId": ObjectId(), "surveyId": ObjectId(), "surveyVersion": 1, "answers": {},
                          "path": [], "createdAt": old, "lastVisitedAt": old, "schemaVersion": 1})
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.draft_ttl_days * 86400)
    assert db.drafts.count_documents({"lastVisitedAt": {"$lt": cutoff}}) == 1
