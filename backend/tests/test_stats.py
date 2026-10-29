"""统计与导出测试：用固定的 5 份答卷核对计数、占比、平均值、单题统计与 CSV。"""

import csv
import io

import pytest

from tests.conftest import register_and_login
from tests.helpers import build_demo_survey, opt

SETTINGS = {"requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": True,
            "deadline": None, "maxResponses": None}


@pytest.fixture
def alice(client):
    return register_and_login(client, "alice")


@pytest.fixture
def bob(client):
    return register_and_login(client, "bob")


def fill(client, headers, s, qs, plan):
    """plan 为 [(题目键, 答案), ...]；单选 / 多选写选项文字。"""
    answers = {}
    for key, value in plan:
        q = qs[key]
        if q["type"] == "single":
            value = opt(q, value)
        elif q["type"] == "multiple":
            value = [opt(q, v) for v in value]
        answers[q["questionId"]] = value
    r = client.post(f"/api/public/surveys/{s['slug']}/responses", json={"answers": answers}, headers=headers)
    assert r.status_code == 201, r.text


@pytest.fixture
def filled(client, alice, bob):
    s, qs = build_demo_survey(client, alice, settings=SETTINGS)
    plans = [
        [("q1", "女"), ("q2", ["苹果", "香蕉"]), ("q3", 25), ("q4", "多点水果")],
        [("q1", "男"), ("q3", 15)],                                   # <18 结束
        [("q1", "男"), ("q3", 40)],                                   # Q4 选填未答
        [("q1", "其他"), ("q2", ["苹果", "葡萄"])],                     # 含葡萄结束
        [("q1", "女"), ("q2", ["苹果", "西瓜", "香蕉"]), ("q3", 30), ("q4", "=1+1")],
    ]
    for plan in plans:
        fill(client, bob, s, qs, plan)
    return s, qs


def by_text(stat):
    return {o["text"]: (o["count"], o["ratio"]) for o in stat["options"]}


def test_survey_stats(client, alice, filled):
    s, _ = filled
    r = client.get(f"/api/surveys/{s['id']}/stats", headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert body["totalResponses"] == 5
    q1, q2, q3, q4 = body["questions"]

    assert q1["answeredCount"] == 5 and q1["skippedCount"] == 0
    assert by_text(q1) == {"男": (2, 0.4), "女": (2, 0.4), "其他": (1, 0.2)}

    assert q2["answeredCount"] == 3 and q2["skippedCount"] == 2
    assert by_text(q2) == {"苹果": (3, 1.0), "香蕉": (2, 0.6667), "西瓜": (1, 0.3333), "葡萄": (1, 0.3333)}

    assert q3["answeredCount"] == 4
    assert q3["average"] == 27.5 and q3["min"] == 15 and q3["max"] == 40
    assert q3["values"] == [25, 15, 40, 30]

    assert q4["answeredCount"] == 2 and q4["values"] == ["多点水果", "=1+1"]
    assert q4["options"] is None and q4["average"] is None


def test_single_question_stats(client, alice, filled):
    s, qs = filled
    r = client.get(f"/api/surveys/{s['id']}/stats/{qs['q2']['questionId']}", headers=alice)
    body = r.json()
    assert body["totalResponses"] == 5 and len(body["questions"]) == 1
    assert by_text(body["questions"][0])["苹果"] == (3, 1.0)
    r = client.get(f"/api/surveys/{s['id']}/stats/q_nope", headers=alice)
    assert r.status_code == 404


def test_stats_with_no_responses(client, alice):
    s, _ = build_demo_survey(client, alice)
    body = client.get(f"/api/surveys/{s['id']}/stats", headers=alice).json()
    assert body["totalResponses"] == 0
    assert all(o["count"] == 0 and o["ratio"] == 0 for o in body["questions"][0]["options"])
    assert body["questions"][2]["average"] is None and body["questions"][2]["values"] == []


def test_legacy_hidden_option_and_question_keep_history(client, db, alice, filled):
    s, qs = filled
    q2 = qs["q2"]
    keep = [{"optionId": o["optionId"], "text": o["text"]} for o in q2["options"] if o["text"] != "西瓜"]
    rejected = client.put(f"/api/surveys/{s['id']}/questions/{q2['questionId']}", headers=alice,
                          json={"type": "multiple", "title": q2["title"], "required": True, "options": keep,
                                "constraints": {"minSelect": 2, "maxSelect": 3}})
    assert rejected.status_code == 409 and rejected.json()["code"] == "published_question_locked"
    # 模拟第一阶段已形成的隐藏标记；第二阶段仍须正确读取旧数据。
    from bson import ObjectId
    doc = db.surveys.find_one({"_id": ObjectId(s["id"])})
    for option in doc["questions"][1]["options"]:
        if option["text"] == "西瓜":
            option["hidden"] = True
    doc["questions"][3]["hidden"] = True
    db.surveys.update_one({"_id": doc["_id"]}, {"$set": {"questions": doc["questions"]}})

    body = client.get(f"/api/surveys/{s['id']}/stats", headers=alice).json()
    melon = next(o for o in body["questions"][1]["options"] if o["text"] == "西瓜")
    assert melon["hidden"] is True and melon["count"] == 1
    assert body["questions"][3]["hidden"] is True and body["questions"][3]["answeredCount"] == 2


def test_stats_only_for_owner(client, alice, bob, filled):
    s, _ = filled
    assert client.get(f"/api/surveys/{s['id']}/stats", headers=bob).status_code == 404
    assert client.get(f"/api/surveys/{s['id']}/export.csv", headers=bob).status_code == 404


def test_stats_aggregation_uses_index(db, filled):
    from bson import ObjectId
    from app.repositories.responses import stats_pipeline
    s, _ = filled
    plan = db.command("explain", {"aggregate": "responses",
                                  "pipeline": stats_pipeline(ObjectId(s["id"])), "cursor": {}},
                      verbosity="queryPlanner")
    assert "survey_responses" in str(plan)


def test_export_query_sorted_by_index(db, filled):
    from bson import ObjectId
    from app.repositories.responses import iter_for_export
    s, _ = filled
    plan = str(iter_for_export(db, ObjectId(s["id"])).explain()["queryPlanner"]["winningPlan"])
    assert "survey_responses" in plan and "'stage': 'SORT'" not in plan


def read_csv(client, s, headers):
    r = client.get(f"/api/surveys/{s['id']}/export.csv", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    assert r.content.startswith("\ufeff".encode("utf-8"))
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def test_export_csv(client, alice, filled):
    s, _ = filled
    rows = read_csv(client, s, alice)
    assert rows[0] == ["序号", "提交时间", "填写者", "你的性别", "你喜欢的水果", "年龄", "其他建议"]
    assert len(rows) == 6
    assert rows[1][0] == "1" and rows[1][2] == "bob"
    assert rows[1][3:] == ["女", "苹果；香蕉", "25", "多点水果"]
    assert rows[2][3:] == ["男", "", "15", ""]
    assert rows[5][6] == "'=1+1"   # 防公式注入


def test_export_anonymous_survey(client, alice, bob):
    s, qs = build_demo_survey(client, alice, settings={**SETTINGS, "allowAnonymous": True})
    fill(client, bob, s, qs, [("q1", "男"), ("q3", 10)])
    rows = read_csv(client, s, alice)
    assert rows[1][2] == "匿名"


def test_export_streams_in_chunks(client, alice, bob, monkeypatch):
    from app.services import export_service
    monkeypatch.setattr(export_service, "CHUNK", 2)
    s, qs = build_demo_survey(client, alice, settings=SETTINGS)
    for age in (20, 30, 40, 50, 60):
        fill(client, bob, s, qs, [("q1", "男"), ("q3", age)])
    rows = read_csv(client, s, alice)
    assert [r[0] for r in rows[1:]] == ["1", "2", "3", "4", "5"]
    assert [r[5] for r in rows[1:]] == ["20", "30", "40", "50", "60"]
