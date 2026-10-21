"""logic_engine 纯函数测试：下一题计算与路径重放。"""

import pytest

from app.services.logic_engine import END, next_question_id, replay, step


def q(qid, order, type_, options=(), logic=(), default=None, required=False, hidden=False,
      constraints=None):
    return {"questionId": qid, "order": order, "type": type_, "title": qid, "required": required,
            "hidden": hidden, "options": [{"optionId": o, "text": o, "hidden": False} for o in options],
            "constraints": constraints or {}, "logic": list(logic), "defaultGoto": default}


def r(op, value, goto):
    return {"when": {"op": op, "value": value}, "goto": goto}


def survey(*questions):
    return {"questions": list(questions)}


# Q1 单选：A→Q5，B→Q3，C 无规则（按顺序到 Q2）
# Q2 多选：包含 x→END；包含 y 和 z→Q4；否则→Q5（defaultGoto）
# Q3 数字：<18→END；18..60→Q4；否则按顺序
# Q4 文本
# Q5 文本（必答）
S = survey(
    q("q1", 1, "single", ["A", "B", "C"], [r("eq", "A", "q5"), r("eq", "B", "q3")], required=True),
    q("q2", 2, "multiple", ["x", "y", "z"], [r("includes", "x", END), r("includesAll", ["y", "z"], "q4")],
      default="q5"),
    q("q3", 3, "number", logic=[r("lt", 18, END), r("between", [18, 60], "q4")]),
    q("q4", 4, "text"),
    q("q5", 5, "text", required=True),
)
Q = {x["questionId"]: x for x in S["questions"]}


@pytest.mark.parametrize("qid,value,expected", [
    ("q1", "A", "q5"),
    ("q1", "B", "q3"),
    ("q1", "C", "q2"),              # 无规则命中，按顺序
    ("q2", ["x", "y"], END),         # 规则按顺序匹配，第一条先命中
    ("q2", ["y", "z"], "q4"),
    ("q2", ["y"], "q5"),             # 走 defaultGoto
    ("q3", 17, END),
    ("q3", 18, "q4"),
    ("q3", 60, "q4"),
    ("q3", 61, "q4"),                # 按顺序，恰好也是 q4
    ("q3", None, "q4"),              # 未作答不匹配规则
    ("q4", "hi", "q5"),
    ("q5", "hi", END),               # 最后一题之后结束
])
def test_next_question(qid, value, expected):
    assert next_question_id(S, Q[qid], value) == expected


def test_single_ne_and_in():
    s = survey(q("q1", 1, "single", ["A", "B", "C"], [r("ne", "A", "q3")]),
               q("q2", 2, "text"), q("q3", 3, "text"))
    assert next_question_id(s, s["questions"][0], "B") == "q3"
    assert next_question_id(s, s["questions"][0], "A") == "q2"
    s["questions"][0]["logic"] = [r("in", ["B", "C"], END)]
    assert next_question_id(s, s["questions"][0], "C") == END


def test_multiple_any_and_equals_set():
    s = survey(q("q1", 1, "multiple", ["x", "y", "z"],
                 [r("equalsSet", ["z", "x"], "q3"), r("includesAny", ["y", "z"], END)]),
               q("q2", 2, "text"), q("q3", 3, "text"))
    assert next_question_id(s, s["questions"][0], ["x", "z"]) == "q3"
    assert next_question_id(s, s["questions"][0], ["x", "y", "z"]) == END
    assert next_question_id(s, s["questions"][0], ["x"]) == "q2"


def test_hidden_target_falls_through():
    s = survey(q("q1", 1, "single", ["A", "B"], [r("eq", "A", "q2")]),
               q("q2", 2, "text", hidden=True), q("q3", 3, "text", hidden=True), q("q4", 4, "text"))
    assert next_question_id(s, s["questions"][0], "A") == "q4"
    assert next_question_id(s, s["questions"][0], "B") == "q4"


def test_step_validates_current_question():
    nxt, errors = step(S, "q1", None)
    assert nxt is None and errors == [{"questionId": "q1", "message": "此题为必答题"}]
    nxt, errors = step(S, "q1", "Z")
    assert errors[0]["message"] == "请选择一个有效的选项"
    assert step(S, "q1", "B") == ("q3", [])
    assert step(S, "nope", "B")[1][0]["message"] == "题目不存在"


def test_replay_full_path():
    res = replay(S, {"q1": "B", "q3": 30, "q4": "ok", "q5": "done"})
    assert res.ok and res.path == ["q1", "q3", "q4", "q5"]
    assert res.answers == [
        {"questionId": "q1", "type": "single", "value": "B"},
        {"questionId": "q3", "type": "number", "value": 30},
        {"questionId": "q4", "type": "text", "value": "ok"},
        {"questionId": "q5", "type": "text", "value": "done"},
    ]


def test_replay_jump_to_end():
    res = replay(S, {"q1": "B", "q3": 10})
    assert res.ok and res.path == ["q1", "q3"]


def test_replay_optional_question_skipped():
    res = replay(S, {"q1": "C", "q2": ["y"], "q5": "x"})
    assert res.ok and res.path == ["q1", "q2", "q5"]


def test_replay_missing_required():
    res = replay(S, {"q1": "A"})
    assert res.errors == [{"questionId": "q5", "message": "此题为必答题"}]


def test_replay_stops_at_invalid_answer():
    res = replay(S, {"q1": "B", "q3": "abc", "q5": "x"})
    assert res.path == ["q1", "q3"]
    assert res.errors == [{"questionId": "q3", "message": "请输入有效的数字"}]


def test_replay_rejects_forged_path():
    """选 A 应直接跳到 Q5，却提交了 Q2、Q3 的答案（例如绕过前端伪造请求）。"""
    res = replay(S, {"q1": "A", "q2": ["x"], "q3": 30, "q5": "x"})
    assert res.path == ["q1", "q5"]
    assert {e["questionId"] for e in res.errors} == {"q2", "q3"}
    assert all("不在作答路径上" in e["message"] for e in res.errors)


def test_replay_ignores_empty_off_path_and_rejects_unknown():
    res = replay(S, {"q1": "A", "q2": [], "q3": None, "q5": "x"})
    assert res.ok
    res = replay(S, {"q1": "A", "q5": "x", "q_fake": "1"})
    assert res.errors == [{"questionId": "q_fake", "message": "题目不存在"}]


def test_replay_skips_hidden_questions():
    s = survey(q("q1", 1, "text", required=True, hidden=True), q("q2", 2, "text", required=True))
    res = replay(s, {"q2": "x"})
    assert res.ok and res.path == ["q2"]
    assert replay(s, {"q1": "x", "q2": "x"}).errors[0]["message"] == "题目不存在"
