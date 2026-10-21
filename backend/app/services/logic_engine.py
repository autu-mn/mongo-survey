"""跳转逻辑引擎（纯函数，不访问数据库）。

跳转规则全部来自问卷文档中的 questions[].logic / defaultGoto，这里只有一个通用解释器：
1. 本题已作答时，按 logic 数组顺序匹配，命中第一条即跳到其 goto；
2. 都不命中（或未作答）时，走 defaultGoto；
3. 再没有就按 order 进入下一道未隐藏的题；最后一题之后为 END。
目标题已隐藏时，顺延到它之后第一道未隐藏的题。
因为保存时已保证只能向后跳（rule_checker），路径一定会在有限步内结束。
"""

from dataclasses import dataclass, field

from app.services.answer_validator import is_empty, validate_answer

END = "END"


@dataclass
class ReplayResult:
    path: list[str] = field(default_factory=list)
    answers: list[dict] = field(default_factory=list)  # 按路径顺序，只含已作答的题
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _sorted(survey: dict) -> list[dict]:
    return sorted(survey["questions"], key=lambda q: q["order"])


def visible_questions(survey: dict) -> list[dict]:
    return [q for q in _sorted(survey) if not q["hidden"]]


def find_visible(survey: dict, qid: str) -> dict | None:
    for q in survey["questions"]:
        if q["questionId"] == qid and not q["hidden"]:
            return q
    return None


def _first_visible_after(survey: dict, order: int) -> str:
    for q in _sorted(survey):
        if q["order"] > order and not q["hidden"]:
            return q["questionId"]
    return END


def first_question_id(survey: dict) -> str:
    return _first_visible_after(survey, 0)


def _resolve(survey: dict, target: str) -> str:
    if target == END:
        return END
    for q in survey["questions"]:
        if q["questionId"] == target:
            return target if not q["hidden"] else _first_visible_after(survey, q["order"])
    return END  # 定义校验保证目标存在，这里只是兜底


def matches(q: dict, op: str, expected, value) -> bool:
    """value 为规范化后的答案（已通过 validate_answer）。"""
    if q["type"] == "single":
        return {"eq": lambda: value == expected,
                "ne": lambda: value != expected,
                "in": lambda: value in expected}.get(op, lambda: False)()
    if q["type"] == "multiple":
        chosen = set(value)
        return {"includes": lambda: expected in chosen,
                "includesAny": lambda: bool(chosen & set(expected)),
                "includesAll": lambda: set(expected) <= chosen,
                "equalsSet": lambda: chosen == set(expected)}.get(op, lambda: False)()
    if q["type"] == "number":
        return {"eq": lambda: value == expected,
                "ne": lambda: value != expected,
                "gt": lambda: value > expected,
                "gte": lambda: value >= expected,
                "lt": lambda: value < expected,
                "lte": lambda: value <= expected,
                "between": lambda: expected[0] <= value <= expected[1]}.get(op, lambda: False)()
    return False


def next_question_id(survey: dict, q: dict, value) -> str:
    """value 为规范化后的答案，未作答时为 None。"""
    if value is not None:
        for rule in q["logic"]:
            if matches(q, rule["when"]["op"], rule["when"]["value"], value):
                return _resolve(survey, rule["goto"])
    if q.get("defaultGoto"):
        return _resolve(survey, q["defaultGoto"])
    return _first_visible_after(survey, q["order"])


def check_one(q: dict, raw) -> tuple[object, str | None]:
    """校验一道题：必答 + 题型约束。返回 (规范化值或 None, 错误信息)。"""
    if is_empty(raw):
        return None, ("此题为必答题" if q["required"] else None)
    return validate_answer(q, raw)


def step(survey: dict, qid: str, raw) -> tuple[str | None, list[dict]]:
    """填写页点"下一题"：校验当前题并给出下一题。返回 (下一题 ID 或 END, 错误列表)。"""
    q = find_visible(survey, qid)
    if q is None:
        return None, [{"questionId": qid, "message": "题目不存在"}]
    value, err = check_one(q, raw)
    if err:
        return None, [{"questionId": qid, "message": err}]
    return next_question_id(survey, q, value), []


def replay(survey: dict, raw_answers: dict) -> ReplayResult:
    """提交时从第一题开始重放整条路径，不信任前端给出的路径。

    - 路径上的每道题都按约束校验，必答题不能为空；
    - 答案中出现路径之外的题（伪造或改答后残留）视为错误；
    - 某题答案不合法时停止重放，因为之后的路径无法确定。
    """
    result = ReplayResult()
    by_id = {q["questionId"]: q for q in survey["questions"]}
    qid = first_question_id(survey)
    guard = len(survey["questions"]) + 1

    while qid != END and guard > 0:
        guard -= 1
        q = by_id[qid]
        result.path.append(qid)
        value, err = check_one(q, raw_answers.get(qid))
        if err:
            result.errors.append({"questionId": qid, "message": err})
            return result
        if value is not None:
            result.answers.append({"questionId": qid, "type": q["type"], "value": value})
        qid = next_question_id(survey, q, value)

    on_path = set(result.path)
    for extra in raw_answers:
        if extra in on_path:
            continue
        if extra not in by_id or by_id[extra]["hidden"]:
            msg = "题目不存在"
        elif is_empty(raw_answers[extra]):
            continue
        else:
            msg = "该题不在作答路径上（可能修改了前面的答案），请重新确认"
        result.errors.append({"questionId": extra, "message": msg})
    return result
