"""编辑页（P7 / P8）：题目增删改、排序、跳转规则。

所有修改都按"读取问卷 → 在内存中修改题目数组 → 整体检查 → 以 updatedAt 为条件写回"进行：
- 整体检查保证任何一次保存后问卷都是自洽的（例如删题后不会留下指向它的规则）；
- 以 updatedAt 为条件写回，两个窗口同时编辑时后保存的一方会收到冲突提示，而不是悄悄覆盖。
"""

import copy
import secrets
from datetime import datetime

from bson import ObjectId
from pymongo.database import Database

from app.errors import AppError
from app.models.question import LogicIn, QuestionIn, ReorderIn, SurveyPatch
from app.repositories import surveys as repo
from app.services import rule_checker
from app.services.survey_service import get_owned

END = rule_checker.END


def _new_id(prefix: str, taken: set[str]) -> str:
    while True:
        candidate = f"{prefix}_{secrets.token_hex(4)}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate


def _is_locked(doc: dict) -> bool:
    """发布过的问卷（已发布或已关闭）可能已有答卷，删除改为隐藏、不允许改题型。"""
    return doc["status"] != "draft"


def _find_question(questions: list[dict], qid: str) -> dict:
    for q in questions:
        if q["questionId"] == qid:
            return q
    raise AppError(404, "question_not_found", "题目不存在")


def _load(db: Database, survey_id: ObjectId, owner_id: ObjectId,
          expected_updated_at: datetime | None) -> dict:
    doc = get_owned(db, survey_id, owner_id)
    if expected_updated_at is not None and doc["updatedAt"] != expected_updated_at:
        raise _conflict()
    return doc


def _conflict() -> AppError:
    return AppError(409, "edit_conflict", "问卷已在其他地方被修改，请刷新后再编辑")


def _save(db: Database, doc: dict, questions: list[dict], bump_version: bool,
          extra_set: dict | None = None) -> dict:
    errors = rule_checker.check_questions(questions)
    if errors:
        raise AppError(422, "invalid_survey", "问卷设置不合法", errors)
    saved = repo.save_editor_changes(
        db, doc["_id"], doc["ownerId"], doc["updatedAt"],
        {"questions": questions, **(extra_set or {})}, bump_version,
    )
    if saved is None:
        raise _conflict()
    return saved


def _build_options(body: QuestionIn, old: dict | None, locked: bool, taken: set[str]) -> list[dict]:
    if body.type not in ("single", "multiple"):
        return []
    old_by_id = {o["optionId"]: o for o in (old["options"] if old else [])}
    result, kept = [], set()
    for opt in body.options:
        if opt.option_id is not None:
            if opt.option_id not in old_by_id:
                raise AppError(422, "invalid_survey", "问卷设置不合法",
                               [{"questionId": old["questionId"] if old else "", "field": "options",
                                 "message": f"选项 {opt.option_id} 不存在"}])
            kept.add(opt.option_id)
            result.append({"optionId": opt.option_id, "text": opt.text, "hidden": False})
        else:
            result.append({"optionId": _new_id("o", taken), "text": opt.text, "hidden": False})
    if locked:
        # 已发布：请求中没有出现的旧选项不删除，改为隐藏并保留在末尾，统计仍可显示
        for oid, o in old_by_id.items():
            if oid not in kept:
                result.append({**o, "hidden": True})
    return result


def update_basic(db: Database, survey_id: ObjectId, owner_id: ObjectId, body: SurveyPatch,
                 expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return doc
    return _save(db, doc, doc["questions"], bump_version=False, extra_set=changes)


def add_question(db: Database, survey_id: ObjectId, owner_id: ObjectId, body: QuestionIn,
                 expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    taken = {q["questionId"] for q in questions} | {o["optionId"] for q in questions for o in q["options"]}
    questions.append({
        "questionId": _new_id("q", taken),
        "order": len(questions) + 1,
        "type": body.type,
        "title": body.title,
        "description": body.description,
        "required": body.required,
        "hidden": False,
        "options": _build_options(body, None, False, taken),
        "constraints": body.constraints.to_doc(),
        "logic": [],
        "defaultGoto": None,
    })
    return _save(db, doc, questions, bump_version=True)


def update_question(db: Database, survey_id: ObjectId, owner_id: ObjectId, qid: str,
                    body: QuestionIn, expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    q = _find_question(questions, qid)
    locked = _is_locked(doc)
    if body.type != q["type"]:
        if locked:
            raise AppError(409, "type_locked", "问卷发布后不能修改题型（已有答案的类型会对不上），可以隐藏此题后新建一题")
        q["logic"], q["defaultGoto"] = [], None  # 旧规则的运算符不适用于新题型

    taken = {x["questionId"] for x in questions} | {o["optionId"] for x in questions for o in x["options"]}
    new_options = _build_options(body, q, locked, taken)
    new_constraints = body.constraints.to_doc()
    structural = (
        body.type != q["type"]
        or body.required != q["required"]
        or new_constraints != q["constraints"]
        or [(o["optionId"], o["hidden"]) for o in new_options]
        != [(o["optionId"], o["hidden"]) for o in q["options"]]
    )
    q.update(type=body.type, title=body.title, description=body.description,
             required=body.required, options=new_options, constraints=new_constraints)
    if not locked:
        # 草稿中删除了选项：去掉引用这些选项的规则
        live = {o["optionId"] for o in new_options}
        q["logic"] = [r for r in q["logic"] if _rule_refs(r) <= live]
    return _save(db, doc, questions, bump_version=structural)


def _rule_refs(rule: dict) -> set[str]:
    v = rule["when"]["value"]
    if isinstance(v, str):
        return {v}
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return set(v)
    return set()


def delete_question(db: Database, survey_id: ObjectId, owner_id: ObjectId, qid: str,
                    expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    q = _find_question(questions, qid)
    if _is_locked(doc):
        # 已发布：只隐藏。指向它的规则保留，填写时会顺延到其后第一道未隐藏的题
        q["hidden"] = True
    else:
        questions = [x for x in questions if x["questionId"] != qid]
        for x in questions:
            if x["order"] > q["order"]:
                x["order"] -= 1
            x["logic"] = [r for r in x["logic"] if r["goto"] != qid]
            if x.get("defaultGoto") == qid:
                x["defaultGoto"] = None
    return _save(db, doc, questions, bump_version=True)


def restore_question(db: Database, survey_id: ObjectId, owner_id: ObjectId, qid: str,
                     expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    _find_question(questions, qid)["hidden"] = False
    return _save(db, doc, questions, bump_version=True)


def reorder(db: Database, survey_id: ObjectId, owner_id: ObjectId, body: ReorderIn,
            expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    current = [q["questionId"] for q in questions]
    if sorted(body.question_ids) != sorted(current):
        raise AppError(422, "invalid_survey", "问卷设置不合法",
                       [{"questionId": "", "field": "questionIds", "message": "必须包含全部题目且不能重复"}])
    position = {qid: i + 1 for i, qid in enumerate(body.question_ids)}
    for q in questions:
        q["order"] = position[q["questionId"]]
    questions.sort(key=lambda q: q["order"])
    # 若调整顺序后出现向前跳的规则，整体检查会拒绝并指出是哪条
    return _save(db, doc, questions, bump_version=True)


def set_logic(db: Database, survey_id: ObjectId, owner_id: ObjectId, qid: str, body: LogicIn,
              expected: datetime | None) -> dict:
    doc = _load(db, survey_id, owner_id, expected)
    questions = copy.deepcopy(doc["questions"])
    q = _find_question(questions, qid)
    q["logic"] = [{"when": {"op": r.when.op, "value": r.when.value}, "goto": r.goto} for r in body.rules]
    q["defaultGoto"] = body.default_goto
    return _save(db, doc, questions, bump_version=True)
