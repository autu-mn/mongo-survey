"""保存问卷时对题目、约束和跳转规则做整体检查（定义校验）。

只检查"问卷本身是否自洽"，不涉及任何答卷。输入为数据库中的题目数组。
"""

END = "END"
MAX_QUESTIONS = 200

ALLOWED_CONSTRAINTS = {
    "single": set(),
    "multiple": {"minSelect", "maxSelect", "exactSelect"},
    "text": {"minLength", "maxLength"},
    "number": {"min", "max", "integerOnly"},
}

ALLOWED_OPS = {
    "single": {"eq", "ne", "in"},
    "multiple": {"includes", "includesAny", "includesAll", "equalsSet"},
    "number": {"eq", "ne", "gt", "gte", "lt", "lte", "between"},
    "text": set(),
}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _err(qid: str, field: str, message: str) -> dict:
    return {"questionId": qid, "field": field, "message": message}


def _check_options(q: dict) -> list[dict]:
    qid, errors = q["questionId"], []
    visible = [o for o in q["options"] if not o["hidden"]]
    if q["type"] in ("single", "multiple"):
        if len(visible) < 2:
            errors.append(_err(qid, "options", "选择题至少需要 2 个选项"))
        ids = [o["optionId"] for o in q["options"]]
        if len(ids) != len(set(ids)):
            errors.append(_err(qid, "options", "选项 ID 重复"))
    elif q["options"]:
        errors.append(_err(qid, "options", "填空题不能设置选项"))
    return errors


def _check_constraints(q: dict) -> list[dict]:
    qid, c, errors = q["questionId"], q["constraints"], []
    extra = set(c) - ALLOWED_CONSTRAINTS[q["type"]]
    if extra:
        errors.append(_err(qid, "constraints", f"该题型不支持约束：{', '.join(sorted(extra))}"))
        return errors

    n_visible = sum(1 for o in q["options"] if not o["hidden"])
    if q["type"] == "multiple":
        exact, lo, hi = c.get("exactSelect"), c.get("minSelect"), c.get("maxSelect")
        if exact is not None and (lo is not None or hi is not None):
            errors.append(_err(qid, "constraints", "\"必须选择 N 项\"不能与至少 / 最多同时设置"))
        if lo is not None and hi is not None and lo > hi:
            errors.append(_err(qid, "constraints", "至少选择数不能大于最多选择数"))
        for name, v in (("exactSelect", exact), ("minSelect", lo), ("maxSelect", hi)):
            if v is not None and v > n_visible:
                errors.append(_err(qid, "constraints", f"{name}={v} 超过了选项数 {n_visible}"))
    elif q["type"] == "text":
        lo, hi = c.get("minLength"), c.get("maxLength")
        if lo is not None and hi is not None and lo > hi:
            errors.append(_err(qid, "constraints", "最少字数不能大于最多字数"))
    elif q["type"] == "number":
        lo, hi = c.get("min"), c.get("max")
        if lo is not None and hi is not None and lo > hi:
            errors.append(_err(qid, "constraints", "最小值不能大于最大值"))
    return errors


def _check_value(q: dict, op: str, value) -> str | None:
    """检查规则的比较值，返回错误信息或 None。引用已隐藏的选项是允许的（规则永远不会命中）。"""
    option_ids = {o["optionId"] for o in q["options"]}
    if (q["type"] == "single" and op in ("eq", "ne")) or (q["type"] == "multiple" and op == "includes"):
        if not isinstance(value, str) or value not in option_ids:
            return "比较值必须是本题的一个选项"
    elif op in ("in", "includesAny", "includesAll", "equalsSet"):
        if (not isinstance(value, list) or not value or len(value) != len(set(value))
                or not all(isinstance(v, str) and v in option_ids for v in value)):
            return "比较值必须是本题选项组成的非空、不重复列表"
    elif op == "between":
        if (not isinstance(value, list) or len(value) != 2
                or not all(_is_number(v) for v in value) or value[0] > value[1]):
            return "介于的比较值必须是 [下限, 上限]，且下限不大于上限"
    elif not _is_number(value):
        return "比较值必须是数字"
    return None


def _check_target(qid: str, field: str, target: str, own_order: int,
                  order_of: dict[str, int]) -> list[dict]:
    if target == END:
        return []
    if target not in order_of:
        return [_err(qid, field, f"跳转目标 {target} 不存在")]
    if order_of[target] <= own_order:
        return [_err(qid, field, f"只能跳转到后面的题目，目标 {target} 在本题之前或就是本题")]
    return []


def _check_logic(q: dict, order_of: dict[str, int]) -> list[dict]:
    qid, errors = q["questionId"], []
    allowed = ALLOWED_OPS[q["type"]]
    if q["logic"] and not allowed:
        return [_err(qid, "logic", "填空（文本）题不支持跳转规则")]
    for i, rule in enumerate(q["logic"]):
        field = f"logic[{i}]"
        op = rule["when"]["op"]
        if op not in allowed:
            errors.append(_err(qid, field, f"运算符 {op} 不适用于该题型"))
            continue
        msg = _check_value(q, op, rule["when"]["value"])
        if msg:
            errors.append(_err(qid, field, msg))
        errors += _check_target(qid, field, rule["goto"], q["order"], order_of)
    if q.get("defaultGoto") is not None:
        errors += _check_target(qid, "defaultGoto", q["defaultGoto"], q["order"], order_of)
    return errors


def check_questions(questions: list[dict]) -> list[dict]:
    """返回错误列表，为空表示通过。"""
    errors: list[dict] = []
    if len(questions) > MAX_QUESTIONS:
        errors.append(_err("", "questions", f"题目数不能超过 {MAX_QUESTIONS}"))

    ids = [q["questionId"] for q in questions]
    if len(ids) != len(set(ids)) or END in ids:
        errors.append(_err("", "questions", "题目 ID 重复或非法"))
    orders = sorted(q["order"] for q in questions)
    if orders != list(range(1, len(questions) + 1)):
        errors.append(_err("", "questions", "题目顺序必须是从 1 开始的连续整数"))
    if errors:
        return errors

    order_of = {q["questionId"]: q["order"] for q in questions}
    for q in questions:
        errors += _check_options(q)
        errors += _check_constraints(q)
        errors += _check_logic(q, order_of)
    return errors
