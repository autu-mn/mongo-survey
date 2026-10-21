"""answer_validator 纯函数测试：四种题型的约束校验。"""

import pytest

from app.services.answer_validator import validate_answer


def q(type_, constraints=None, options=("a", "b", "c", "d"), hidden=()):
    return {"questionId": "q", "type": type_, "constraints": constraints or {},
            "options": [{"optionId": o, "text": o, "hidden": o in hidden} for o in options]}


@pytest.mark.parametrize("value,ok", [
    ("a", True), ("z", False), (["a"], False), (1, False), ("d", False),
])
def test_single(value, ok):
    _, err = validate_answer(q("single", hidden=("d",)), value)
    assert (err is None) == ok


@pytest.mark.parametrize("constraints,value,expected", [
    ({"minSelect": 2, "maxSelect": 3}, ["a"], "至少选择 2 项"),
    ({"minSelect": 2, "maxSelect": 3}, ["a", "b"], None),
    ({"minSelect": 2, "maxSelect": 3}, ["a", "b", "c"], None),
    ({"minSelect": 2, "maxSelect": 3}, ["a", "b", "c", "d"], "最多选择 3 项"),
    ({"exactSelect": 2}, ["a"], "必须选择 2 项"),
    ({"exactSelect": 2}, ["a", "b", "c"], "必须选择 2 项"),
    ({"exactSelect": 2}, ["a", "c"], None),
    ({}, ["a", "a"], "选项不能重复"),
    ({}, ["a", "zz"], "包含无效的选项"),
    ({}, "a", "多选题的答案必须是选项列表"),
])
def test_multiple(constraints, value, expected):
    _, err = validate_answer(q("multiple", constraints), value)
    assert err == expected


@pytest.mark.parametrize("constraints,value,expected", [
    ({"minLength": 2, "maxLength": 5}, "你好", None),
    ({"minLength": 2, "maxLength": 5}, "  你  ", "至少输入 2 个字（当前 1 个）"),
    ({"minLength": 2, "maxLength": 5}, "一二三四五六", "最多输入 5 个字（当前 6 个）"),
    ({}, 123, "请输入文本"),
    ({}, "x" * 5001, "最多输入 5000 个字（当前 5001 个）"),
])
def test_text(constraints, value, expected):
    _, err = validate_answer(q("text", constraints, options=()), value)
    assert err == expected


def test_text_is_trimmed():
    value, err = validate_answer(q("text", options=()), "  hello  ")
    assert err is None and value == "hello"


AGE = {"min": 0, "max": 120, "integerOnly": True}


@pytest.mark.parametrize("constraints,value,expected_value,expected_err", [
    (AGE, 25, 25, None),
    (AGE, "25", 25, None),
    (AGE, 25.0, 25, None),
    (AGE, 25.5, None, "必须为整数"),
    (AGE, -1, None, "不能小于 0"),
    (AGE, 121, None, "不能大于 120"),
    (AGE, "abc", None, "请输入有效的数字"),
    (AGE, True, None, "请输入有效的数字"),
    (AGE, float("nan"), None, "请输入有效的数字"),
    ({"integerOnly": True}, 13800138000, 13800138000, None),
    ({"integerOnly": True}, "138-0013", None, "请输入有效的数字"),
    ({"integerOnly": True}, 2**70, None, "数值过大"),
    ({}, "3.14", 3.14, None),
])
def test_number(constraints, value, expected_value, expected_err):
    v, err = validate_answer(q("number", constraints, options=()), value)
    assert err == expected_err
    if expected_err is None:
        assert v == expected_value and type(v) is type(expected_value)
