"""单道题的答案校验（纯函数，不访问数据库）。

validate_answer 返回 (规范化后的值, 错误信息)。错误信息为 None 表示通过。
未作答（None、空字符串、空列表）由调用方结合"是否必答"处理。
"""

import math

INT64_MAX = 2**63 - 1
TEXT_HARD_LIMIT = 5000


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "") or value == []


def _visible_option_ids(q: dict) -> set[str]:
    return {o["optionId"] for o in q["options"] if not o["hidden"]}


def _single(q: dict, value):
    if not isinstance(value, str) or value not in _visible_option_ids(q):
        return None, "请选择一个有效的选项"
    return value, None


def _multiple(q: dict, value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None, "多选题的答案必须是选项列表"
    if len(value) != len(set(value)):
        return None, "选项不能重复"
    if not set(value) <= _visible_option_ids(q):
        return None, "包含无效的选项"
    c, n = q["constraints"], len(value)
    if c.get("exactSelect") is not None and n != c["exactSelect"]:
        return None, f"必须选择 {c['exactSelect']} 项"
    if c.get("minSelect") is not None and n < c["minSelect"]:
        return None, f"至少选择 {c['minSelect']} 项"
    if c.get("maxSelect") is not None and n > c["maxSelect"]:
        return None, f"最多选择 {c['maxSelect']} 项"
    return value, None


def _text(q: dict, value):
    if not isinstance(value, str):
        return None, "请输入文本"
    value = value.strip()
    c, n = q["constraints"], len(value)
    if c.get("minLength") is not None and n < c["minLength"]:
        return None, f"至少输入 {c['minLength']} 个字（当前 {n} 个）"
    limit = min(c.get("maxLength") or TEXT_HARD_LIMIT, TEXT_HARD_LIMIT)
    if n > limit:
        return None, f"最多输入 {limit} 个字（当前 {n} 个）"
    return value, None


def _to_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _number(q: dict, value):
    num = _to_number(value)
    if num is None or (isinstance(num, float) and not math.isfinite(num)):
        return None, "请输入有效的数字"
    c = q["constraints"]
    if isinstance(num, float) and num.is_integer():
        num = int(num)
    if c.get("integerOnly") and not isinstance(num, int):
        return None, "必须为整数"
    if isinstance(num, int) and abs(num) > INT64_MAX:
        return None, "数值过大"
    if c.get("min") is not None and num < c["min"]:
        return None, f"不能小于 {c['min']}"
    if c.get("max") is not None and num > c["max"]:
        return None, f"不能大于 {c['max']}"
    return num, None


_VALIDATORS = {"single": _single, "multiple": _multiple, "text": _text, "number": _number}


def validate_answer(q: dict, value):
    return _VALIDATORS[q["type"]](q, value)
