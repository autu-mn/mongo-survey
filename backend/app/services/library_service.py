"""【第二阶段新增】问卷选题、已有题保存、引用查询（P30/P31/P33）。"""

import copy

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.errors import AppError
from app.models.library import SaveToLibrary
from app.repositories import question_banks, question_items, question_versions, surveys
from app.services import question_item_service, question_service, rule_checker, survey_service


def _version_for_use(db, version_id: ObjectId, user_id: ObjectId) -> tuple[dict, dict]:
    version = question_versions.find_by_id(db, version_id)
    if version is None:
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    item = question_item_service.get_readable(db, version["itemId"], user_id)
    return item, version


def _snapshot(version: dict, question_id: str, order: int) -> dict:
    return {"questionId": question_id, "order": order,
            **{key: copy.deepcopy(version[key]) for key in question_versions.CONTENT_FIELDS},
            "hidden": False, "logic": [], "defaultGoto": None,
            "sourceItemId": version["itemId"], "sourceVersionId": version["_id"]}


def select_version(db, survey_id: ObjectId, owner_id: ObjectId, version_id: ObjectId,
                   expected, replace_question_id: str | None = None) -> dict:
    doc = question_service._load(db, survey_id, owner_id, expected)
    question_service._require_draft(doc)
    _, version = _version_for_use(db, version_id, owner_id)
    questions = copy.deepcopy(doc["questions"])
    if replace_question_id is None:
        taken = {q["questionId"] for q in questions}
        qid = question_service._new_id("q", taken)
        questions.append(_snapshot(version, qid, len(questions) + 1))
    else:
        old = question_service._find_question(questions, replace_question_id)
        replacement = _snapshot(version, old["questionId"], old["order"])
        replacement["hidden"] = old["hidden"]
        # 旧规则的比较值可能属于旧版本的选项，替换时清空本题规则。
        questions[questions.index(old)] = replacement
    errors = rule_checker.check_questions(questions)
    if errors:
        raise AppError(422, "invalid_survey", "问卷设置不合法", errors)
    saved = surveys.save_editor_changes(db, survey_id, owner_id, doc["updatedAt"],
                                        {"questions": questions}, True, require_draft=True)
    if saved is None:
        raise question_service._conflict()
    return saved


def ensure_source(db, survey_id: ObjectId, owner_id: ObjectId, question: dict) -> tuple[ObjectId, ObjectId]:
    """创建/复用按问卷题目 ID 唯一的来源；允许发布或保存操作失败后重试。"""
    existing_item = question.get("sourceItemId")
    existing_version = question.get("sourceVersionId")
    if existing_item is not None or existing_version is not None:
        if existing_item is None or existing_version is None:
            raise AppError(409, "invalid_question_source", "题目来源不完整")
        item = question_items.find_by_id(db, existing_item)
        version = question_versions.find_by_id(db, existing_version)
        if (item is None or version is None or version["itemId"] != item["_id"]
                or question_versions.content_from_question(question)
                != {key: version[key] for key in question_versions.CONTENT_FIELDS}):
            raise AppError(409, "invalid_question_source", "题目快照与来源版本不一致")
        return existing_item, existing_version
    item = question_items.find_by_origin(db, survey_id, question["questionId"])
    if item is None:
        try:
            item = question_items.insert_item(db, owner_id, origin_survey_id=survey_id,
                                              origin_question_id=question["questionId"])
        except DuplicateKeyError:
            item = question_items.find_by_origin(db, survey_id, question["questionId"])
    if item is None or item["ownerId"] != owner_id:
        raise AppError(409, "invalid_question_source", "题目来源身份冲突")
    version = question_versions.find_number(db, item["_id"], 1)
    content = question_versions.content_from_question(question)
    if version is None:
        try:
            version = question_versions.insert_version(db, item["_id"], 1, None, content)
        except DuplicateKeyError:
            version = question_versions.find_number(db, item["_id"], 1)
    if version is None:
        raise AppError(409, "invalid_question_source", "无法建立题目来源，请重试")
    if content != {key: version[key] for key in question_versions.CONTENT_FIELDS}:
        # 上次尝试可能在关联问卷前中断，且草稿随后被编辑；保留旧版并新增匹配当前快照的版本。
        for prior in question_versions.list_by_item(db, item["_id"]):
            if content == {key: prior[key] for key in question_versions.CONTENT_FIELDS}:
                version = prior
                break
        else:
            for _ in range(8):
                latest = question_versions.find_latest(db, item["_id"])
                try:
                    version = question_versions.insert_version(db, item["_id"],
                        latest["versionNo"] + 1, latest["_id"], content)
                    break
                except DuplicateKeyError:
                    continue
            else:
                raise AppError(409, "version_conflict", "创建题目来源版本冲突，请重试")
    return item["_id"], version["_id"]


def save_question(db, survey_id: ObjectId, owner_id: ObjectId, question_id: str,
                  body: SaveToLibrary, expected) -> dict:
    doc = question_service._load(db, survey_id, owner_id, expected)
    bank_id = question_item_service.parse_id(body.bank_id) if body.bank_id else None
    if bank_id and question_banks.find_owned(db, bank_id, owner_id) is None:
        raise AppError(404, "question_bank_not_found", "题库不存在")
    questions = copy.deepcopy(doc["questions"])
    q = question_service._find_question(questions, question_id)
    item_id, version_id = ensure_source(db, survey_id, owner_id, q)
    changed = q.get("sourceVersionId") is None
    if changed:
        q["sourceItemId"] = item_id
        q["sourceVersionId"] = version_id
        saved = surveys.save_editor_changes(db, survey_id, owner_id, doc["updatedAt"],
                                            {"questions": questions}, False)
        if saved is None:
            raise question_service._conflict()
    else:
        saved = doc
    if bank_id:
        # 收录有权访问的版本；撤销共享后，旧题仍在问卷中但不能新收录。
        question_item_service.get_readable(db, item_id, owner_id)
        question_banks.add_item(db, bank_id, owner_id, item_id)
    return {"itemId": str(item_id), "versionId": str(version_id),
            "survey": survey_service.to_detail(saved, survey_service.now_utc())}


def usage(db, item_id: ObjectId, user_id: ObjectId) -> dict:
    question_item_service.get_readable_history(db, item_id, user_id)
    flt = {"questions.sourceItemId": item_id, "deletedAt": None}
    own = []
    for survey in db.surveys.find({**flt, "ownerId": user_id},
                                  {"title": 1, "status": 1, "questions": 1}):
        versions = sorted({str(q["sourceVersionId"]) for q in survey["questions"]
                           if q.get("sourceItemId") == item_id and q.get("sourceVersionId")})
        own.append({"surveyId": str(survey["_id"]), "title": survey["title"],
                    "status": survey["status"], "versionIds": versions})
    other_count = db.surveys.count_documents({**flt, "ownerId": {"$ne": user_id}})
    return {"itemId": str(item_id), "ownSurveys": own, "otherSurveyCount": other_count}
