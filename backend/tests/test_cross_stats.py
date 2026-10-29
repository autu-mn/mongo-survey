"""【第二阶段新增】新答卷精确归版、旧答案单列和跨卷统计权限。"""

from copy import deepcopy

from bson import ObjectId

from tests.conftest import register_and_login
from tests.helpers import create_survey, single


def _create_item(client, headers):
    r = client.post("/api/question-items", headers=headers,
                    json={"content": single("年龄段", "成年", "未成年")})
    assert r.status_code == 201
    return r.json()


def _survey_with_version(client, headers, version_id):
    survey = create_survey(client, headers)
    r = client.post(f"/api/surveys/{survey['id']}/questions/from-library", headers=headers,
                    json={"versionId": version_id})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/surveys/{survey['id']}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _answer(client, headers, survey, option_text):
    q = survey["questions"][0]
    value = next(o["optionId"] for o in q["options"] if o["text"] == option_text)
    r = client.post(f"/api/public/surveys/{survey['slug']}/responses", headers=headers,
                    json={"answers": {q["questionId"]: value}})
    assert r.status_code == 201, r.text
    return r.json()


def test_new_answers_are_exactly_versioned_and_old_answers_separate(client, db):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    charlie = register_and_login(client, "charlie")
    item = _create_item(client, alice)
    v1 = item["latestVersion"]["id"]
    v2 = client.post(f"/api/question-items/{item['id']}/versions", headers=alice,
                     json={"parentVersionId": v1,
                           "content": single("新年龄段", "成年", "未成年")}).json()["id"]
    s1 = _survey_with_version(client, alice, v1)
    s2 = _survey_with_version(client, alice, v2)
    _answer(client, bob, s1, "成年")
    _answer(client, charlie, s2, "未成年")
    answer1 = db.responses.find_one({"surveyId": ObjectId(s1["id"])})
    answer2 = db.responses.find_one({"surveyId": ObjectId(s2["id"])})
    assert answer1["answers"][0]["questionVersionId"] == ObjectId(v1)
    assert answer2["answers"][0]["questionVersionId"] == ObjectId(v2)
    # 模拟第一阶段同一问卷的旧答卷：有 questionId，但没有可核实的版本 ID。
    old = deepcopy(answer1)
    old.pop("_id")
    old["submitterKey"] = "legacy:another"
    old["answers"][0].pop("questionVersionId")
    db.responses.insert_one(old)
    v1_stats = client.get(f"/api/question-items/{item['id']}/versions/{v1}/stats", headers=alice)
    v2_stats = client.get(f"/api/question-items/{item['id']}/versions/{v2}/stats", headers=alice)
    assert v1_stats.status_code == v2_stats.status_code == 200
    assert v1_stats.json()["answeredCount"] == 1 and v1_stats.json()["unattributedCount"] == 1
    assert v2_stats.json()["answeredCount"] == 1 and v2_stats.json()["unattributedCount"] == 0
    assert v1_stats.json()["options"][0]["count"] == 1
    assert v2_stats.json()["options"][1]["count"] == 1
    # 第一阶段单卷统计仍读取所有答卷，包括无法归版的旧答卷。
    assert client.get(f"/api/surveys/{s1['id']}/stats", headers=alice).json()["totalResponses"] == 2


def test_cross_stats_only_own_surveys_and_revoked_access(client):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    charlie = register_and_login(client, "charlie")
    item = _create_item(client, alice)
    vid = item["latestVersion"]["id"]
    client.put(f"/api/question-items/{item['id']}/sharing", headers=alice,
               json={"visibility": "public"})
    bob_survey = _survey_with_version(client, bob, vid)
    _answer(client, charlie, bob_survey, "成年")
    url = f"/api/question-items/{item['id']}/versions/{vid}/stats"
    assert client.get(url, headers=alice).json()["answeredCount"] == 0
    assert client.get(url, headers=bob).json()["answeredCount"] == 1
    client.put(f"/api/question-items/{item['id']}/sharing", headers=alice,
               json={"visibility": "private"})
    assert client.get(url, headers=bob).json()["answeredCount"] == 1
    detail = client.get(f"/api/question-items/{item['id']}", headers=bob)
    assert detail.status_code == 200 and detail.json()["canSelectNew"] is False
    assert client.get(f"/api/question-items/{item['id']}/versions", headers=bob).status_code == 200
    assert client.post("/api/question-items", headers=bob,
                       json={"sourceVersionId": vid}).status_code == 404
    assert client.get(url, headers=charlie).status_code == 404
    assert client.get(url, headers=alice).json()["answeredCount"] == 0
    assert client.get(f"/api/question-items/{item['id']}/versions/{ObjectId()}/stats",
                      headers=alice).status_code == 404
