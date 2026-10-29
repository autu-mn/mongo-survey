"""【第二阶段新增】多题库、版本引用、复制及发布冻结的 API 回归。"""

from copy import deepcopy

from bson import ObjectId

from tests.conftest import register_and_login
from tests.helpers import add_question, create_survey, single


def item(client, headers):
    r = client.post("/api/question-items", headers=headers,
                    json={"content": single("你的年龄段", "成年", "未成年")})
    assert r.status_code == 201, r.text
    return r.json()


def bank(client, headers, name="常用题"):
    r = client.post("/api/question-banks", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def select(client, headers, survey_id, version_id, *, replace_qid=None, if_match=None):
    path = f"/api/surveys/{survey_id}/questions"
    if replace_qid:
        path += f"/{replace_qid}/from-library"
        method = client.put
    else:
        path += "/from-library"
        method = client.post
    return method(path, headers={**headers, **({"If-Match": if_match} if if_match else {})},
                  json={"versionId": version_id})


def test_multiple_banks_membership_and_deletion_keeps_item(client, db):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    q = item(client, alice)
    a = bank(client, alice, "常用题")
    b = bank(client, alice, "教学题")
    assert client.post("/api/question-banks", headers=alice, json={"name": "常用题"}).json()["code"] == "bank_name_taken"
    assert {x["name"] for x in client.get("/api/question-banks", headers=alice).json()} == {"常用题", "教学题"}
    for bank_id in (a["id"], b["id"]):
        path = f"/api/question-banks/{bank_id}/items/{q['id']}"
        assert client.put(path, headers=alice).status_code == 200
        assert client.put(path, headers=alice).json()["itemCount"] == 1
    assert client.get(f"/api/question-banks/{a['id']}", headers=bob).status_code == 404
    assert client.put(f"/api/question-banks/{a['id']}/items/{q['id']}", headers=bob).status_code == 404
    assert client.put(f"/api/question-banks/{b['id']}", headers=alice,
                      json={"name": "问卷题"}).json()["name"] == "问卷题"
    assert client.delete(f"/api/question-banks/{a['id']}", headers=alice).status_code == 204
    assert client.get(f"/api/question-banks/{b['id']}", headers=alice).json()["itemCount"] == 1
    assert db.question_items.count_documents({}) == 1
    assert db.question_versions.count_documents({}) == 1


def test_two_surveys_reuse_exact_version_and_copy_preserves_snapshot(client, db):
    alice = register_and_login(client)
    q = item(client, alice)
    first = q["latestVersion"]
    revised = client.post(f"/api/question-items/{q['id']}/versions", headers=alice,
                          json={"parentVersionId": first["id"],
                                "content": single("今年年龄段", "成年", "未成年")}).json()
    s1 = create_survey(client, alice, "去年问卷")
    s2 = create_survey(client, alice, "今年问卷")
    v1 = select(client, alice, s1["id"], first["id"])
    v2 = select(client, alice, s2["id"], revised["id"])
    assert v1.status_code == v2.status_code == 201
    old = v1.json()["questions"][0]
    new = v2.json()["questions"][0]
    assert old["title"] == "你的年龄段" and new["title"] == "今年年龄段"
    assert old["sourceVersionId"] == first["id"] and new["sourceVersionId"] == revised["id"]
    assert old["questionId"] != new["questionId"]
    assert client.post(f"/api/surveys/{s1['id']}/publish", headers=alice).status_code == 200
    copied = client.post(f"/api/surveys/{s1['id']}/copy", headers=alice).json()
    assert copied["status"] == "draft" and copied["slug"] != s1["slug"]
    assert copied["responseCount"] == 0 and copied["questions"] == v1.json()["questions"]
    assert client.get(f"/api/surveys/{s1['id']}", headers=alice).json()["questions"] == v1.json()["questions"]
    replacement = select(client, alice, copied["id"], revised["id"],
                         replace_qid=copied["questions"][0]["questionId"])
    assert replacement.status_code == 200
    assert replacement.json()["questions"][0]["title"] == "今年年龄段"
    assert client.get(f"/api/surveys/{s1['id']}", headers=alice).json()["questions"][0]["title"] == "你的年龄段"
    assert db.responses.count_documents({"surveyId": ObjectId(copied["id"])}) == 0


def test_publish_freezes_all_question_operations_and_old_link(client):
    alice = register_and_login(client)
    q = item(client, alice)
    s = create_survey(client, alice)
    chosen = select(client, alice, s["id"], q["latestVersion"]["id"]).json()
    qid = chosen["questions"][0]["questionId"]
    pub = client.post(f"/api/surveys/{s['id']}/publish", headers=alice).json()
    before = deepcopy(pub["questions"])
    calls = [
        client.post(f"/api/surveys/{s['id']}/questions", headers=alice,
                    json=single("新题", "A", "B")),
        client.put(f"/api/surveys/{s['id']}/questions/{qid}", headers=alice,
                   json=single("改题", "A", "B")),
        client.delete(f"/api/surveys/{s['id']}/questions/{qid}", headers=alice),
        client.post(f"/api/surveys/{s['id']}/questions/{qid}/restore", headers=alice),
        client.put(f"/api/surveys/{s['id']}/questions/order", headers=alice,
                   json={"questionIds": [qid]}),
        client.put(f"/api/surveys/{s['id']}/questions/{qid}/logic", headers=alice,
                   json={"rules": []}),
        select(client, alice, s["id"], q["latestVersion"]["id"]),
    ]
    assert all(r.status_code == 409 and r.json()["code"] == "published_question_locked" for r in calls)
    closed = client.post(f"/api/surveys/{s['id']}/close", headers=alice)
    assert closed.status_code == 200
    assert select(client, alice, s["id"], q["latestVersion"]["id"]).status_code == 409
    after = client.get(f"/api/surveys/{s['id']}", headers=alice).json()
    assert after["questions"] == before and after["slug"] == s["slug"]


def test_save_existing_question_and_publish_autolinks(client, db):
    alice = register_and_login(client)
    b = bank(client, alice)
    s = create_survey(client, alice)
    updated = add_question(client, alice, s["id"], **single("现有题", "A", "B"))
    qid = updated["questions"][0]["questionId"]
    saved = client.post(f"/api/surveys/{s['id']}/questions/{qid}/save-to-library",
                        headers=alice, json={"bankId": b["id"]})
    assert saved.status_code == 201
    item_id = saved.json()["itemId"]
    assert saved.json()["survey"]["questions"][0]["sourceItemId"] == item_id
    again = client.post(f"/api/surveys/{s['id']}/questions/{qid}/save-to-library",
                        headers=alice, json={"bankId": b["id"]})
    assert again.json()["itemId"] == item_id
    assert client.get(f"/api/question-banks/{b['id']}", headers=alice).json()["itemCount"] == 1
    assert db.question_items.count_documents({}) == 1
    assert client.put(f"/api/surveys/{s['id']}/questions/{qid}", headers=alice,
                      json=single("原位改题", "A", "B")).json()["code"] == "versioned_question_locked"
    another = add_question(client, alice, s["id"], **single("未关联题", "C", "D"))
    published = client.post(f"/api/surveys/{s['id']}/publish", headers=alice).json()
    assert all(q.get("sourceVersionId") for q in published["questions"])
    assert db.question_items.count_documents({}) == 2
    assert published["questions"][1]["title"] == another["questions"][1]["title"]


def test_usage_privacy_and_revoked_share_keeps_existing_survey(client, db):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    q = item(client, alice)
    qid, vid = q["id"], q["latestVersion"]["id"]
    assert client.get(f"/api/question-items/{qid}/usage", headers=bob).status_code == 404
    client.put(f"/api/question-items/{qid}/sharing", headers=alice,
               json={"visibility": "selected", "usernames": ["bob"]})
    s = create_survey(client, bob, "Bob 的问卷")
    assert select(client, bob, s["id"], vid).status_code == 201
    assert select(client, bob, s["id"], vid).status_code == 201
    published = client.post(f"/api/surveys/{s['id']}/publish", headers=bob).json()
    assert len(published["questions"]) == 2
    owner_view = client.get(f"/api/question-items/{qid}/usage", headers=alice).json()
    assert owner_view["ownSurveys"] == [] and owner_view["otherSurveyCount"] == 1
    bob_view = client.get(f"/api/question-items/{qid}/usage", headers=bob).json()
    assert len(bob_view["ownSurveys"]) == 1 and bob_view["otherSurveyCount"] == 0
    assert bob_view["ownSurveys"][0]["versionIds"] == [vid]
    client.put(f"/api/question-items/{qid}/sharing", headers=alice,
               json={"visibility": "private"})
    assert select(client, bob, create_survey(client, bob)["id"], vid).status_code == 404
    revoked_view = client.get(f"/api/question-items/{qid}/usage", headers=bob)
    assert revoked_view.status_code == 200
    assert len(revoked_view.json()["ownSurveys"]) == 1
    assert revoked_view.json()["otherSurveyCount"] == 0
    assert client.get(f"/api/surveys/{s['id']}", headers=bob).json()["questions"] == published["questions"]
    assert client.get(f"/api/public/surveys/{published['slug']}", headers=bob).status_code == 200
    assert db.surveys.count_documents({"questions.sourceItemId": ObjectId(qid)}) == 1


def test_if_match_and_bank_revocation(client):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    q = item(client, alice)
    client.put(f"/api/question-items/{q['id']}/sharing", headers=alice,
               json={"visibility": "public"})
    b = bank(client, bob)
    path = f"/api/question-banks/{b['id']}/items/{q['id']}"
    assert client.put(path, headers=bob).status_code == 200
    s = create_survey(client, bob)
    stale = s["updatedAt"]
    first = select(client, bob, s["id"], q["latestVersion"]["id"], if_match=stale)
    assert first.status_code == 201
    second = select(client, bob, s["id"], q["latestVersion"]["id"], if_match=stale)
    assert second.status_code == 409 and second.json()["code"] == "edit_conflict"
    client.put(f"/api/question-items/{q['id']}/sharing", headers=alice,
               json={"visibility": "private"})
    detail = client.get(f"/api/question-banks/{b['id']}", headers=bob).json()
    assert detail["items"][0]["available"] is False
    assert client.put(path, headers=bob).status_code == 404
    assert client.delete(path, headers=bob).status_code == 200


def test_published_legacy_question_can_only_gain_source_metadata(client, db):
    alice = register_and_login(client)
    s = create_survey(client, alice)
    draft = add_question(client, alice, s["id"], **single("旧题", "A", "B"))
    published = client.post(f"/api/surveys/{s['id']}/publish", headers=alice).json()
    original = deepcopy(published["questions"][0])
    # 模拟第一阶段的已发布问卷：题目快照存在，但尚未写来源字段。
    doc = db.surveys.find_one({"_id": ObjectId(s["id"])})
    doc["questions"][0].pop("sourceItemId")
    doc["questions"][0].pop("sourceVersionId")
    db.surveys.update_one({"_id": doc["_id"]}, {"$set": {"questions": doc["questions"]}})
    saved = client.post(f"/api/surveys/{s['id']}/questions/{original['questionId']}/save-to-library",
                        headers=alice, json={})
    assert saved.status_code == 201
    after = saved.json()["survey"]["questions"][0]
    assert after == original and saved.json()["survey"]["version"] == published["version"]
    assert client.put(f"/api/surveys/{s['id']}/questions/{original['questionId']}",
                      headers=alice, json=single("改题", "A", "B")).status_code == 409
