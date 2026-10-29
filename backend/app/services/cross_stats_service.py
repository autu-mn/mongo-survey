"""【第二阶段新增】本人问卷中的同一具体题目版本统计（P34）。"""

from bson import ObjectId

from app.errors import AppError
from app.repositories import cross_stats, question_versions
from app.services import question_item_service


def version_stats(db, item_id: ObjectId, version_id: ObjectId, user_id: ObjectId) -> dict:
    version = question_versions.find_by_id(db, version_id)
    if version is None or version["itemId"] != item_id:
        raise AppError(404, "question_version_not_found", "题目版本不存在")
    # 分享撤销后，用户依然可以统计自己已发布问卷中的旧引用。
    surveys = cross_stats.owned_surveys_for_version(db, user_id, version_id)
    item = cross_stats.item_exists(db, item_id)
    if item is None or (not question_item_service.can_read(item, user_id) and not surveys):
        raise AppError(404, "question_item_not_found", "题目不存在或无权访问")
    ids = [s["_id"] for s in surveys]
    qids = {s["_id"]: {q["questionId"] for q in s["questions"]
                       if q.get("sourceVersionId") == version_id} for s in surveys}
    answers = cross_stats.versioned_answers(db, ids, version_id)
    chosen = []
    for row in answers:
        if row["answer"]["questionId"] in qids.get(row["surveyId"], set()):
            chosen.append(row["answer"]["value"])
    # 旧答卷没有当时的题目快照；只数无法归版的答案，不把它们混入分布。
    unassigned = 0
    legacy = cross_stats.unattributed_answers(db, ids)
    for row in legacy:
        if row["questionId"] in qids.get(row["surveyId"], set()):
            unassigned += 1
    result = {"itemId": str(item_id), "versionId": str(version_id),
              "versionNo": version["versionNo"], "type": version["type"],
              "title": version["title"], "ownerSurveyCount": len(ids),
              "answeredCount": len(chosen), "unattributedCount": unassigned,
              "options": [], "values": [], "average": None, "min": None, "max": None}
    if version["type"] in ("single", "multiple"):
        counts = {}
        for value in chosen:
            for option_id in value if isinstance(value, list) else [value]:
                counts[option_id] = counts.get(option_id, 0) + 1
        result["options"] = [
            {"optionId": o["optionId"], "text": o["text"], "hidden": o["hidden"],
             "count": counts.get(o["optionId"], 0),
             "ratio": round(counts.get(o["optionId"], 0) / len(chosen), 4) if chosen else 0.0}
            for o in version["options"]
        ]
    else:
        result["values"] = chosen
        if version["type"] == "number" and chosen:
            result.update(average=round(sum(chosen) / len(chosen), 4),
                          min=min(chosen), max=max(chosen))
    return result
