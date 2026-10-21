"""填写入口、下一题、预览、提交测试（包括并发）。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.deps import CurrentUser
from app.errors import AppError
from app.models.public import SubmitIn
from app.repositories import responses as responses_repo
from app.services import fill_service
from tests.conftest import register_and_login
from tests.helpers import build_demo_survey, opt

ALL_DEFAULT = {"requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": False,
               "deadline": None, "maxResponses": None}


@pytest.fixture
def alice(client):
    return register_and_login(client, "alice")


@pytest.fixture
def bob(client):
    return register_and_login(client, "bob")


def entry(client, slug, headers=None):
    return client.get(f"/api/public/surveys/{slug}", headers=headers or {})


def female_path_answers(qs):
    """女 → Q2（苹果、香蕉）→ 按顺序 Q3（25）→ Q4。"""
    q1, q2, q3, q4 = qs["q1"], qs["q2"], qs["q3"], qs["q4"]
    return {q1["questionId"]: opt(q1, "女"),
            q2["questionId"]: [opt(q2, "苹果"), opt(q2, "香蕉")],
            q3["questionId"]: 25,
            q4["questionId"]: "多点水果"}


def submit(client, slug, answers, headers=None):
    return client.post(f"/api/public/surveys/{slug}/responses", json={"answers": answers},
                       headers=headers or {})


# ---------- 入口状态 ----------

def test_entry_not_found_for_unknown_draft_and_deleted(client, alice):
    assert entry(client, "nosuchslug").status_code == 404
    draft, _ = build_demo_survey(client, alice, publish=False)
    assert entry(client, draft["slug"], alice).status_code == 404
    s, _ = build_demo_survey(client, alice)
    client.delete(f"/api/surveys/{s['id']}", headers=alice)
    assert entry(client, s["slug"], alice).json()["code"] == "survey_not_found"


def test_entry_login_required_hides_questions(client, alice):
    s, _ = build_demo_survey(client, alice)
    body = entry(client, s["slug"]).json()
    assert body["state"] == "login_required"
    assert body["survey"]["title"] == "示例问卷" and body["survey"]["questions"] == []


def test_entry_ok_returns_public_questions(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    client.delete(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}", headers=alice)
    body = entry(client, s["slug"], bob).json()
    assert body["state"] == "ok"
    questions = body["survey"]["questions"]
    assert [q["number"] for q in questions] == [1, 2, 3]          # 隐藏的 Q4 不出现
    assert all("logic" not in q and "hidden" not in q for q in questions)
    assert body["survey"]["firstQuestionId"] == qs["q1"]["questionId"]


@pytest.mark.parametrize("setup,reason", [
    (lambda c, h, s, db: c.post(f"/api/surveys/{s['id']}/close", headers=h), "closed"),
    (lambda c, h, s, db: db.surveys.update_one(
        {"_id": ObjectId(s["id"])},
        {"$set": {"settings.deadline": datetime.now(timezone.utc) - timedelta(seconds=1)}}), "expired"),
    (lambda c, h, s, db: db.surveys.update_one(
        {"_id": ObjectId(s["id"])}, {"$set": {"settings.maxResponses": 1, "responseCount": 1}}), "full"),
])
def test_entry_ended(client, alice, bob, db, setup, reason):
    s, qs = build_demo_survey(client, alice)
    setup(client, alice, s, db)
    body = entry(client, s["slug"], bob).json()
    assert body["state"] == "ended" and body["reason"] == reason and body["survey"]["questions"] == []
    r = submit(client, s["slug"], female_path_answers(qs), bob)
    assert r.status_code == 409 and r.json()["code"] == "survey_ended"
    assert r.json()["details"] == {"reason": reason}


# ---------- 下一题 ----------

def test_next_follows_rules(client, alice, bob):
    s, qs = build_demo_survey(client, alice)
    url = f"/api/public/surveys/{s['slug']}/next"
    q1, q2, q3 = qs["q1"], qs["q2"], qs["q3"]
    cases = [
        (q1, opt(q1, "男"), q3["questionId"]),
        (q1, opt(q1, "女"), q2["questionId"]),
        (q1, opt(q1, "其他"), q2["questionId"]),
        (q2, [opt(q2, "苹果"), opt(q2, "葡萄")], "END"),
        (q2, [opt(q2, "苹果"), opt(q2, "香蕉")], q3["questionId"]),
        (q3, 17, "END"),
        (q3, 30, qs["q4"]["questionId"]),
    ]
    for q, value, expected in cases:
        r = client.post(url, json={"questionId": q["questionId"], "value": value}, headers=bob)
        assert r.status_code == 200 and r.json()["next"] == expected, (q["title"], value, r.text)


def test_next_reports_validation_error(client, alice, bob):
    s, qs = build_demo_survey(client, alice)
    url = f"/api/public/surveys/{s['slug']}/next"
    r = client.post(url, json={"questionId": qs["q2"]["questionId"], "value": [opt(qs["q2"], "苹果")]},
                    headers=bob)
    assert r.status_code == 422 and r.json()["message"] == "至少选择 2 项"
    r = client.post(url, json={"questionId": qs["q3"]["questionId"], "value": 30.5}, headers=bob)
    assert r.json()["message"] == "必须为整数"
    r = client.post(url, json={"questionId": qs["q1"]["questionId"], "value": opt(qs["q1"], "男")})
    assert r.status_code == 401


# ---------- 提交 ----------

def test_submit_success_stores_path_and_answers(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    r = submit(client, s["slug"], female_path_answers(qs), bob)
    assert r.status_code == 201, r.text
    assert r.json()["completion"]["message"] == "感谢您的填写！"

    doc = db.responses.find_one({"_id": ObjectId(r.json()["responseId"])})
    bob_id = db.users.find_one({"username": "bob"})["_id"]
    assert doc["respondentId"] == bob_id and doc["submitterKey"] == f"u:{bob_id}"
    assert doc["singleSubmission"] is True and doc["surveyVersion"] == s["version"]
    assert doc["path"] == [qs[k]["questionId"] for k in ("q1", "q2", "q3", "q4")]
    assert [a["type"] for a in doc["answers"]] == ["single", "multiple", "number", "text"]
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 1


def test_submit_male_path_skips_q2(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    q1, q3 = qs["q1"], qs["q3"]
    r = submit(client, s["slug"], {q1["questionId"]: opt(q1, "男"), q3["questionId"]: 15}, bob)
    assert r.status_code == 201
    doc = db.responses.find_one({})
    assert doc["path"] == [q1["questionId"], q3["questionId"]]   # 男 → Q3，<18 → 结束


def test_submit_rejects_forged_path(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    answers = female_path_answers(qs)
    answers[qs["q1"]["questionId"]] = opt(qs["q1"], "男")   # 男应跳过 Q2，却带了 Q2 的答案
    r = submit(client, s["slug"], answers, bob)
    assert r.status_code == 422
    assert r.json()["details"][0]["questionId"] == qs["q2"]["questionId"]
    assert db.responses.count_documents({}) == 0
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 0


def test_submit_missing_required(client, alice, bob):
    s, qs = build_demo_survey(client, alice)
    q1 = qs["q1"]
    r = submit(client, s["slug"], {q1["questionId"]: opt(q1, "女")}, bob)
    assert r.status_code == 422
    assert r.json()["details"] == [{"questionId": qs["q2"]["questionId"], "message": "此题为必答题"}]


def test_submit_requires_login(client, alice):
    s, qs = build_demo_survey(client, alice)
    r = submit(client, s["slug"], female_path_answers(qs))
    assert r.status_code == 401 and r.json()["code"] == "login_required"


def test_single_submission(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    assert submit(client, s["slug"], female_path_answers(qs), bob).status_code == 201
    assert entry(client, s["slug"], bob).json()["state"] == "already_submitted"
    r = submit(client, s["slug"], female_path_answers(qs), bob)
    assert r.status_code == 409 and r.json()["code"] == "already_submitted"
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 1


def test_multiple_submission_allowed(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice, settings={**ALL_DEFAULT, "allowMultipleSubmit": True})
    for _ in range(3):
        assert submit(client, s["slug"], female_path_answers(qs), bob).status_code == 201
    assert entry(client, s["slug"], bob).json()["state"] == "ok"
    assert db.responses.count_documents({}) == 3


def test_anonymous_submission_hides_identity_but_dedupes(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice, settings={**ALL_DEFAULT, "allowAnonymous": True})
    assert submit(client, s["slug"], female_path_answers(qs), bob).status_code == 201
    doc = db.responses.find_one({})
    bob_id = str(db.users.find_one({"username": "bob"})["_id"])
    assert doc["respondentId"] is None
    assert doc["submitterKey"].startswith("a:") and bob_id not in doc["submitterKey"]
    assert submit(client, s["slug"], female_path_answers(qs), bob).status_code == 409


def test_guest_submission_when_login_not_required(client, alice, db):
    s, qs = build_demo_survey(client, alice, settings={**ALL_DEFAULT, "requireLogin": False,
                                                        "allowMultipleSubmit": True})
    assert entry(client, s["slug"]).json()["state"] == "ok"
    assert submit(client, s["slug"], female_path_answers(qs)).status_code == 201
    assert submit(client, s["slug"], female_path_answers(qs)).status_code == 201
    keys = [d["submitterKey"] for d in db.responses.find({})]
    assert all(k.startswith("g:") for k in keys) and len(set(keys)) == 2


def test_completion_redirect_returned(client, alice, bob):
    s, qs = build_demo_survey(client, alice, settings={
        **ALL_DEFAULT, "completion": {"message": "谢谢参与", "redirectUrl": "https://example.com/done"}})
    r = submit(client, s["slug"], female_path_answers(qs), bob)
    assert r.json()["completion"] == {"message": "谢谢参与", "redirectUrl": "https://example.com/done"}


def test_insert_failure_releases_slot(client, alice, bob, db, monkeypatch):
    s, qs = build_demo_survey(client, alice)

    def boom(*_):
        raise RuntimeError("disk full")

    monkeypatch.setattr(responses_repo, "insert_response", boom)
    with pytest.raises(RuntimeError):
        submit(client, s["slug"], female_path_answers(qs), bob)
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 0


# ---------- 并发 ----------

def _users(db, client, n):
    result = []
    for i in range(n):
        register_and_login(client, f"user{i}")
        u = db.users.find_one({"username": f"user{i}"})
        result.append(CurrentUser(id=u["_id"], username=u["username"]))
    return result


def _try_submit(db, slug, user, answers):
    try:
        fill_service.submit(db, slug, user, SubmitIn(answers=answers))
        return "ok"
    except AppError as e:
        return e.code


def test_concurrent_submissions_respect_max_responses(client, alice, db):
    s, qs = build_demo_survey(client, alice, settings={**ALL_DEFAULT, "maxResponses": 3})
    users = _users(db, client, 8)
    answers = female_path_answers(qs)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda u: _try_submit(db, s["slug"], u, answers), users))
    assert results.count("ok") == 3
    assert set(results) == {"ok", "survey_ended"}
    assert db.responses.count_documents({}) == 3
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 3


def test_reserve_fails_after_precheck_passed(client, alice, bob, db, monkeypatch):
    """状态检查通过之后、占名额之前，问卷被别人填满：原子占名额必须失败并返回"已收满"。"""
    s, qs = build_demo_survey(client, alice, settings={**ALL_DEFAULT, "maxResponses": 1})
    stale = db.surveys.find_one({"_id": ObjectId(s["id"])})        # 检查时读到的旧文档：还差 1 份
    db.surveys.update_one({"_id": stale["_id"]}, {"$set": {"responseCount": 1}})  # 期间被别人填满
    monkeypatch.setattr(fill_service, "_load_fillable", lambda *_: stale)
    r = submit(client, s["slug"], female_path_answers(qs), bob)
    assert r.status_code == 409 and r.json()["code"] == "survey_ended"
    assert r.json()["details"] == {"reason": "full"}
    assert db.responses.count_documents({}) == 0
    assert db.surveys.find_one({"_id": stale["_id"]})["responseCount"] == 1


def test_concurrent_duplicate_submissions_by_same_user(client, alice, db):
    s, qs = build_demo_survey(client, alice)
    user = _users(db, client, 1)[0]
    answers = female_path_answers(qs)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _try_submit(db, s["slug"], user, answers), range(6)))
    assert results.count("ok") == 1
    assert set(results) == {"ok", "already_submitted"}
    assert db.responses.count_documents({}) == 1
    assert db.surveys.find_one({"_id": ObjectId(s["id"])})["responseCount"] == 1


# ---------- 预览 ----------

def test_preview_draft_without_writing(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice, publish=False)
    r = client.get(f"/api/surveys/{s['id']}/preview", headers=alice)
    assert r.status_code == 200 and len(r.json()["questions"]) == 4
    r = client.post(f"/api/surveys/{s['id']}/preview/next", headers=alice,
                    json={"questionId": qs["q1"]["questionId"], "value": opt(qs["q1"], "男")})
    assert r.json()["next"] == qs["q3"]["questionId"]
    assert client.get(f"/api/surveys/{s['id']}/preview", headers=bob).status_code == 404
    assert db.responses.count_documents({}) == 0


def test_has_single_submission_uses_partial_index(client, alice, bob, db):
    s, qs = build_demo_survey(client, alice)
    submit(client, s["slug"], female_path_answers(qs), bob)
    plan = db.responses.find({"surveyId": ObjectId(s["id"]), "submitterKey": "u:x",
                              "singleSubmission": True}).explain()["queryPlanner"]["winningPlan"]
    assert "uniq_single_submission" in str(plan)
