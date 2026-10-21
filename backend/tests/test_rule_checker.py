"""rule_checker 纯函数测试：保存问卷时的定义校验。"""

import pytest

from app.services.rule_checker import check_questions


def q(qid, order, type_, options=(), constraints=None, logic=(), default_goto=None, hidden_opts=()):
    return {
        "questionId": qid, "order": order, "type": type_, "title": qid, "required": False,
        "hidden": False,
        "options": [{"optionId": o, "text": o, "hidden": o in hidden_opts} for o in options],
        "constraints": constraints or {}, "logic": list(logic), "defaultGoto": default_goto,
    }


def r(op, value, goto):
    return {"when": {"op": op, "value": value}, "goto": goto}


def messages(errors):
    return " | ".join(e["message"] for e in errors)


def test_valid_survey_passes():
    qs = [
        q("q1", 1, "single", ["a", "b"], logic=[r("eq", "a", "q3"), r("in", ["a", "b"], "END")]),
        q("q2", 2, "multiple", ["x", "y", "z"], {"minSelect": 1, "maxSelect": 2},
          logic=[r("includesAll", ["x", "y"], "q4")], default_goto="END"),
        q("q3", 3, "number", constraints={"min": 0, "max": 120, "integerOnly": True},
          logic=[r("between", [0, 17], "END"), r("gte", 60, "q4")]),
        q("q4", 4, "text", constraints={"minLength": 1, "maxLength": 50}),
    ]
    assert check_questions(qs) == []


@pytest.mark.parametrize("questions,expected", [
    ([q("q1", 1, "single", ["a"])], "至少需要 2 个选项"),
    ([q("q1", 1, "single", ["a", "b"], hidden_opts=["b"])], "至少需要 2 个选项"),
    ([q("q1", 1, "text", ["a"])], "填空题不能设置选项"),
    ([q("q1", 1, "single", ["a", "b"], {"minSelect": 1})], "不支持约束"),
    ([q("q1", 1, "multiple", ["a", "b"], {"exactSelect": 1, "maxSelect": 2})], "不能与至少"),
    ([q("q1", 1, "multiple", ["a", "b", "c"], {"minSelect": 3, "maxSelect": 2})], "不能大于最多"),
    ([q("q1", 1, "multiple", ["a", "b"], {"maxSelect": 3})], "超过了选项数"),
    ([q("q1", 1, "text", constraints={"minLength": 10, "maxLength": 5})], "最少字数"),
    ([q("q1", 1, "number", constraints={"min": 10, "max": 5})], "最小值"),
    ([q("q1", 1, "text", logic=[r("eq", "x", "END")])], "不支持跳转"),
    ([q("q1", 1, "single", ["a", "b"], logic=[r("gt", 1, "END")])], "不适用于该题型"),
    ([q("q1", 1, "single", ["a", "b"], logic=[r("eq", "zzz", "END")])], "必须是本题的一个选项"),
    ([q("q1", 1, "single", ["a", "b"], logic=[r("in", [], "END")])], "非空、不重复"),
    ([q("q1", 1, "multiple", ["a", "b"], logic=[r("equalsSet", ["a", "a"], "END")])], "非空、不重复"),
    ([q("q1", 1, "number", logic=[r("between", [5, 1], "END")])], "下限不大于上限"),
    ([q("q1", 1, "number", logic=[r("gt", "18", "END")])], "必须是数字"),
    ([q("q1", 1, "number", logic=[r("gt", True, "END")])], "必须是数字"),
    ([q("q1", 1, "single", ["a", "b"], logic=[r("eq", "a", "q9")])], "不存在"),
    ([q("q1", 1, "single", ["a", "b"], default_goto="q9")], "不存在"),
])
def test_invalid_definitions(questions, expected):
    assert expected in messages(check_questions(questions))


def test_backward_and_self_jump_rejected():
    qs = [
        q("q1", 1, "single", ["a", "b"]),
        q("q2", 2, "single", ["a", "b"], logic=[r("eq", "a", "q1"), r("eq", "b", "q2")]),
    ]
    errors = check_questions(qs)
    assert len(errors) == 2
    assert all("只能跳转到后面的题目" in e["message"] and e["questionId"] == "q2" for e in errors)


def test_rule_on_hidden_option_is_allowed():
    qs = [q("q1", 1, "single", ["a", "b", "c"], hidden_opts=["c"], logic=[r("eq", "c", "END")])]
    assert check_questions(qs) == []


def test_order_and_id_integrity():
    assert "连续整数" in messages(check_questions([q("q1", 1, "text"), q("q2", 3, "text")]))
    assert "ID 重复" in messages(check_questions([q("q1", 1, "text"), q("q1", 2, "text")]))
    assert "ID 重复" in messages(check_questions([q("END", 1, "text")]))
