"""编辑页 API 测试：题目增删改、排序、发布后隐藏、跳转规则、version、乐观锁。"""

import pytest

from tests.conftest import register_and_login
from tests.helpers import (add_question, build_demo_survey, create_survey, multiple, number,
                           opt, rule, set_logic, single, text)


@pytest.fixture
def alice(client):
    return register_and_login(client, "alice")


def test_add_three_question_types(client, alice):
    s = create_survey(client, alice)
    sid = s["id"]
    add_question(client, alice, sid, **single("性别", "男", "女", "其他"))
    add_question(client, alice, sid, **multiple("水果", "苹果", "香蕉", "西瓜", "葡萄", minSelect=2, maxSelect=3))
    add_question(client, alice, sid, **text("建议", minLength=2, maxLength=200))
    s = add_question(client, alice, sid, **number("年龄", min=0, max=120, integerOnly=True))

    q1, q2, q3, q4 = s["questions"]
    assert [q["order"] for q in s["questions"]] == [1, 2, 3, 4]
    assert [q["type"] for q in s["questions"]] == ["single", "multiple", "text", "number"]
    assert [o["text"] for o in q1["options"]] == ["男", "女", "其他"]
    assert all(o["optionId"].startswith("o_") and o["hidden"] is False for o in q1["options"])
    assert q2["constraints"] == {"minSelect": 2, "maxSelect": 3}
    assert q3["constraints"] == {"minLength": 2, "maxLength": 200} and q3["options"] == []
    assert q4["constraints"] == {"min": 0, "max": 120, "integerOnly": True}
    assert s["version"] == 5 and s["questionCount"] == 4


@pytest.mark.parametrize("body,expected", [
    (single("只有一个选项", "A"), "至少需要 2 个选项"),
    (multiple("数量不对", "A", "B", maxSelect=3), "超过了选项数"),
    (text("字数", minLength=10, maxLength=5), "最少字数"),
    (number("范围", min=10, max=1), "最小值"),
])
def test_add_invalid_question(client, alice, body, expected):
    s = create_survey(client, alice)
    r = client.post(f"/api/surveys/{s['id']}/questions", json=body, headers=alice)
    assert r.status_code == 422 and r.json()["code"] == "invalid_survey"
    assert expected in r.json()["details"][0]["message"]


def test_add_question_rejects_unknown_type(client, alice):
    s = create_survey(client, alice)
    r = client.post(f"/api/surveys/{s['id']}/questions", json={"type": "rating", "title": "x"}, headers=alice)
    assert r.status_code == 422


def test_logic_saved_and_validated(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    q1 = next(q for q in s["questions"] if q["order"] == 1)
    assert q1["logic"][0]["goto"] == qs["q3"]["questionId"]
    # 向前跳
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q3']['questionId']}/logic", headers=alice,
                   json={"rules": [rule("gt", 1, qs["q1"]["questionId"])]})
    assert r.status_code == 422 and "只能跳转到后面的题目" in r.json()["details"][0]["message"]
    # 文本题设置规则
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}/logic", headers=alice,
                   json={"rules": [rule("eq", "x", "END")]})
    assert r.status_code == 422
    # 不存在的运算符被请求模型拦截
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q1']['questionId']}/logic", headers=alice,
                   json={"rules": [rule("regex", "x", "END")]})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_reorder_rejected_when_rule_would_jump_backward(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    ids = [qs[k]["questionId"] for k in ("q3", "q1", "q2", "q4")]  # Q1 的规则指向 Q3，Q3 被移到最前
    r = client.put(f"/api/surveys/{s['id']}/questions/order", json={"questionIds": ids}, headers=alice)
    assert r.status_code == 422
    assert any("只能跳转到后面的题目" in e["message"] for e in r.json()["details"])


def test_reorder_success(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    ids = [qs[k]["questionId"] for k in ("q1", "q2", "q4", "q3")]
    r = client.put(f"/api/surveys/{s['id']}/questions/order", json={"questionIds": ids}, headers=alice)
    assert r.status_code == 200, r.text
    assert [q["questionId"] for q in r.json()["questions"]] == ids
    r = client.put(f"/api/surveys/{s['id']}/questions/order", json={"questionIds": ids[:3]}, headers=alice)
    assert r.status_code == 422


def test_draft_delete_removes_question_and_rules_pointing_to_it(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    r = client.delete(f"/api/surveys/{s['id']}/questions/{qs['q3']['questionId']}", headers=alice)
    assert r.status_code == 200
    questions = r.json()["questions"]
    assert [q["order"] for q in questions] == [1, 2, 3]
    assert qs["q3"]["questionId"] not in [q["questionId"] for q in questions]
    q1 = questions[0]
    assert [x["goto"] for x in q1["logic"]] == [qs["q2"]["questionId"]]


def test_draft_option_removal_drops_rules_using_it(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    q1 = qs["q1"]
    body = {"type": "single", "title": "你的性别", "required": True,
            "options": [{"optionId": opt(q1, "女"), "text": "女"}, {"optionId": opt(q1, "其他"), "text": "其他"}]}
    r = client.put(f"/api/surveys/{s['id']}/questions/{q1['questionId']}", json=body, headers=alice)
    assert r.status_code == 200, r.text
    new_q1 = r.json()["questions"][0]
    assert [o["text"] for o in new_q1["options"]] == ["女", "其他"]
    assert [x["when"]["value"] for x in new_q1["logic"]] == [opt(q1, "女")]


def test_published_delete_becomes_hidden_and_restore(client, alice):
    s, qs = build_demo_survey(client, alice)
    v = s["version"]
    r = client.delete(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}", headers=alice)
    q4 = r.json()["questions"][3]
    assert q4["hidden"] is True and r.json()["questionCount"] == 3 and r.json()["version"] == v + 1
    r = client.post(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}/restore", headers=alice)
    assert r.json()["questions"][3]["hidden"] is False


def test_published_option_removal_becomes_hidden(client, alice):
    s, qs = build_demo_survey(client, alice)
    q2 = qs["q2"]
    keep = [{"optionId": o["optionId"], "text": o["text"]} for o in q2["options"] if o["text"] != "西瓜"]
    body = {"type": "multiple", "title": "你喜欢的水果（改）", "required": True, "options": keep,
            "constraints": {"minSelect": 2, "maxSelect": 3}}
    r = client.put(f"/api/surveys/{s['id']}/questions/{q2['questionId']}", json=body, headers=alice)
    assert r.status_code == 200, r.text
    new_q2 = r.json()["questions"][1]
    watermelon = next(o for o in new_q2["options"] if o["text"] == "西瓜")
    assert watermelon["hidden"] is True and watermelon["optionId"] == opt(q2, "西瓜")
    assert r.json()["version"] == s["version"] + 1


def test_published_text_only_edit_does_not_bump_version(client, alice):
    s, qs = build_demo_survey(client, alice)
    q3 = qs["q3"]
    body = {"type": "number", "title": "您的年龄（周岁）", "required": True, "constraints": q3["constraints"]}
    r = client.put(f"/api/surveys/{s['id']}/questions/{q3['questionId']}", json=body, headers=alice)
    assert r.json()["version"] == s["version"]
    assert r.json()["questions"][2]["title"] == "您的年龄（周岁）"


def test_published_type_change_rejected(client, alice):
    s, qs = build_demo_survey(client, alice)
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q4']['questionId']}", headers=alice,
                   json=number("改成数字"))
    assert r.status_code == 409 and r.json()["code"] == "type_locked"


def test_draft_type_change_clears_logic(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q3']['questionId']}", headers=alice,
                   json=text("改成文本"))
    assert r.status_code == 200
    assert r.json()["questions"][2]["logic"] == []


def test_unknown_option_id_rejected(client, alice):
    s, qs = build_demo_survey(client, alice, publish=False)
    body = {"type": "single", "title": "x", "options": [{"optionId": "o_fake", "text": "A"}, {"text": "B"}]}
    r = client.put(f"/api/surveys/{s['id']}/questions/{qs['q1']['questionId']}", json=body, headers=alice)
    assert r.status_code == 422


def test_unknown_question_404(client, alice):
    s = create_survey(client, alice)
    r = client.delete(f"/api/surveys/{s['id']}/questions/q_nope", headers=alice)
    assert r.status_code == 404 and r.json()["code"] == "question_not_found"


def test_optimistic_lock(client, alice):
    s = create_survey(client, alice)
    stale = s["updatedAt"]
    r = client.post(f"/api/surveys/{s['id']}/questions", json=text("Q1"), headers={**alice, "If-Match": stale})
    assert r.status_code == 201
    fresh = r.json()["updatedAt"]
    # 另一个窗口仍持有旧的 updatedAt
    r = client.post(f"/api/surveys/{s['id']}/questions", json=text("Q2"), headers={**alice, "If-Match": stale})
    assert r.status_code == 409 and r.json()["code"] == "edit_conflict"
    r = client.post(f"/api/surveys/{s['id']}/questions", json=text("Q2"), headers={**alice, "If-Match": fresh})
    assert r.status_code == 201


def test_optimistic_lock_within_same_millisecond(client, alice, monkeypatch):
    """时钟停在同一毫秒：updatedAt 仍必须严格变大，否则旧窗口可以绕过冲突检测。"""
    from datetime import datetime, timezone
    from app.repositories import surveys as surveys_repo
    frozen = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(surveys_repo, "_now", lambda: frozen)
    s = create_survey(client, alice)
    stale = s["updatedAt"]
    r1 = client.post(f"/api/surveys/{s['id']}/questions", json=text("Q1"), headers={**alice, "If-Match": stale})
    assert r1.status_code == 201 and r1.json()["updatedAt"] != stale
    r2 = client.post(f"/api/surveys/{s['id']}/questions", json=text("Q2"), headers={**alice, "If-Match": stale})
    assert r2.status_code == 409


def test_title_starting_with_dollar_is_stored_literally(client, alice):
    s = create_survey(client, alice)
    r = client.patch(f"/api/surveys/{s['id']}", json={"title": "$version"}, headers=alice)
    assert r.json()["title"] == "$version"
    r = client.post(f"/api/surveys/{s['id']}/questions", json=text("$title"), headers=alice)
    assert r.json()["questions"][0]["title"] == "$title"


def test_patch_title(client, alice):
    s = create_survey(client, alice)
    r = client.patch(f"/api/surveys/{s['id']}", json={"title": "新标题", "description": "新说明"}, headers=alice)
    assert r.json()["title"] == "新标题" and r.json()["description"] == "新说明"
    assert r.json()["version"] == s["version"]


def test_other_user_cannot_edit(client, alice):
    bob = register_and_login(client, "bob")
    s = create_survey(client, alice)
    r = client.post(f"/api/surveys/{s['id']}/questions", json=text("x"), headers=bob)
    assert r.status_code == 404
