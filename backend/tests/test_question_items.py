"""【第二阶段新增】独立题目版本与共享的 API、权限及不可变性测试。"""

from bson import ObjectId

from tests.conftest import register_and_login


ROOT = "/api/question-items"
SINGLE = {"type": "single", "title": "你的年龄段", "required": True,
          "options": [{"text": "成年"}, {"text": "未成年"}]}


def create(client, headers, content=SINGLE):
    response = client.post(ROOT, json={"content": content}, headers=headers)
    assert response.status_code == 201, response.json()
    return response.json()


def test_create_validate_and_version_history(client, db):
    alice = register_and_login(client)
    invalid = client.post(ROOT, json={"content": {"type": "single", "title": "X",
                                                    "options": [{"text": "only"}]}}, headers=alice)
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_question"
    assert db.question_items.count_documents({}) == 0
    item = create(client, alice)
    first = item["latestVersion"]
    assert item["visibility"] == "private" and first["versionNo"] == 1
    assert all(o["optionId"] for o in first["content"]["options"])
    restored = client.post(f"{ROOT}/{item['id']}/versions",
                           json={"parentVersionId": first["id"]}, headers=alice)
    assert restored.status_code == 201
    assert restored.json()["versionNo"] == 2
    assert restored.json()["parentVersionId"] == first["id"]
    assert restored.json()["content"] == first["content"]
    changed = {"type": "single", "title": "今年年龄段", "required": True,
               "options": [{"optionId": o["optionId"], "text": o["text"]}
                           for o in first["content"]["options"]]}
    fork = client.post(f"{ROOT}/{item['id']}/versions",
                       json={"parentVersionId": first["id"], "content": changed}, headers=alice)
    assert fork.status_code == 201 and fork.json()["versionNo"] == 3
    assert fork.json()["parentVersionId"] == first["id"]
    history = client.get(f"{ROOT}/{item['id']}/versions", headers=alice).json()
    assert [v["versionNo"] for v in history] == [1, 2, 3]
    assert history[0]["content"]["title"] == "你的年龄段"
    assert history[1]["content"]["title"] == "你的年龄段"
    assert history[2]["content"]["title"] == "今年年龄段"
    assert db.question_versions.find_one({"_id": ObjectId(first["id"])})["title"] == "你的年龄段"


def test_private_public_selected_and_revoke(client, db):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    charlie = register_and_login(client, "charlie")
    item = create(client, alice)
    path = f"{ROOT}/{item['id']}"
    original = item["latestVersion"]
    assert client.get(f"{path}/versions", headers=bob).status_code == 404
    assert client.post(ROOT, json={"sourceVersionId": original["id"]}, headers=bob).status_code == 404
    assert client.put(f"{path}/sharing", json={"visibility": "public"}, headers=bob).status_code == 404
    assert client.post(f"{path}/versions", json={"parentVersionId": original["id"]},
                       headers=bob).status_code == 404
    assert client.put(f"{path}/sharing", json={"visibility": "selected",
                                               "usernames": ["nobody"]}, headers=alice).status_code == 422
    assert client.put(f"{path}/sharing", json={"visibility": "selected",
                                               "usernames": ["bob"]}, headers=alice).status_code == 200
    assert len(client.get(f"{path}/versions", headers=bob).json()) == 1
    assert client.get(f"{path}/versions", headers=charlie).status_code == 404
    copied = client.post(ROOT, json={"sourceVersionId": original["id"]}, headers=bob)
    assert copied.status_code == 201
    assert copied.json()["ownerId"] != item["ownerId"]
    assert copied.json()["latestVersion"]["content"] == original["content"]
    assert client.put(f"{path}/sharing", json={"visibility": "private"}, headers=alice).status_code == 200
    assert client.get(f"{path}/versions", headers=bob).status_code == 404
    assert client.get(f"{ROOT}/{copied.json()['id']}/versions", headers=bob).status_code == 200
    assert client.put(f"{path}/sharing", json={"visibility": "public"}, headers=alice).status_code == 200
    assert len(client.get(f"{path}/versions", headers=charlie).json()) == 1
    shared_ids = {i["id"] for i in client.get(ROOT, params={"scope": "shared"}, headers=charlie).json()}
    assert item["id"] in shared_ids and copied.json()["id"] not in shared_ids
    assert db.question_versions.find_one({"_id": ObjectId(original["id"])})["title"] == "你的年龄段"


def test_parent_access_input_and_login(client):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    a = create(client, alice)
    b = create(client, bob)
    assert client.get(ROOT).status_code == 401
    assert client.post(ROOT, json={"content": SINGLE, "sourceVersionId": a["latestVersion"]["id"]},
                       headers=alice).status_code == 422
    assert client.post(f"{ROOT}/{a['id']}/versions",
                       json={"parentVersionId": b["latestVersion"]["id"]}, headers=alice).json()["code"] == "invalid_parent_version"
    assert client.get(f"{ROOT}/bad-id/versions", headers=alice).status_code == 422
    assert client.get(f"{ROOT}/{ObjectId()}/versions", headers=alice).status_code == 404


def test_shared_list_and_version_validation(client):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    item = create(client, alice)
    path = f"{ROOT}/{item['id']}"
    assert client.get(ROOT, params={"scope": "mine"}, headers=alice).json()[0]["id"] == item["id"]
    assert client.get(ROOT, params={"scope": "other"}, headers=alice).status_code == 422
    assert client.put(f"{path}/sharing", json={"visibility": "selected", "usernames": ["bob", "bob"]},
                      headers=alice).status_code == 422
    assert client.put(f"{path}/sharing", json={"visibility": "selected", "usernames": ["bob"]},
                      headers=alice).status_code == 200
    assert item["id"] in {i["id"] for i in client.get(ROOT, params={"scope": "shared"}, headers=bob).json()}
    assert client.get(ROOT, params={"scope": "shared", "offset": 1}, headers=bob).json() == []
    bad = client.post(f"{path}/versions", json={"parentVersionId": item["latestVersion"]["id"],
                                                  "content": {"type": "number", "title": "错误范围",
                                                              "constraints": {"min": 10, "max": 1}}}, headers=alice)
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_question"
