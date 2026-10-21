"""统计页（P16 / P17）：聚合结果与问卷题目合并。

聚合只给出"出现过的"选项计数，这里以问卷当前的题目和选项为准补齐 0 次的选项，
并保留已隐藏的题目和选项（标注 hidden），历史数据不会因编辑问卷而消失。
"""

from bson import ObjectId
from pymongo.database import Database

from app.errors import AppError
from app.models.stats import OptionStat, QuestionStat, SurveyStats
from app.repositories import responses as responses_repo
from app.services.survey_service import get_owned


def _question_stat(q: dict, total: int, agg: dict) -> QuestionStat:
    qid = q["questionId"]
    answered = agg["answered"].get(qid, 0)
    stat = QuestionStat(
        question_id=qid, order=q["order"], type=q["type"], title=q["title"], hidden=q["hidden"],
        answered_count=answered, skipped_count=total - answered,
    )
    if q["type"] in ("single", "multiple"):
        stat.options = [
            OptionStat(
                option_id=o["optionId"], text=o["text"], hidden=o["hidden"],
                count=(c := agg["optionCounts"].get((qid, o["optionId"]), 0)),
                ratio=round(c / answered, 4) if answered else 0.0,
            )
            for o in q["options"]
        ]
    else:
        stat.values = agg["values"].get(qid, [])
    if q["type"] == "number":
        nums = agg["numbers"].get(qid)
        if nums:
            stat.average = round(nums["avg"], 4)
            stat.min, stat.max = nums["min"], nums["max"]
    return stat


def _index(raw: dict) -> dict:
    return {
        "total": raw["total"][0]["n"] if raw["total"] else 0,
        "answered": {d["_id"]: d["n"] for d in raw["answered"]},
        "optionCounts": {(d["_id"]["q"], d["_id"]["o"]): d["n"] for d in raw["optionCounts"]},
        "numbers": {d["_id"]: d for d in raw["numbers"]},
        "values": {d["_id"]: d["values"] for d in raw["values"]},
    }


def survey_stats(db: Database, survey_id: ObjectId, owner_id: ObjectId,
                 question_id: str | None = None) -> SurveyStats:
    doc = get_owned(db, survey_id, owner_id)
    questions = sorted(doc["questions"], key=lambda q: q["order"])
    if question_id is not None:
        questions = [q for q in questions if q["questionId"] == question_id]
        if not questions:
            raise AppError(404, "question_not_found", "题目不存在")

    agg = _index(responses_repo.aggregate_stats(db, survey_id, question_id))
    return SurveyStats(
        survey_id=str(doc["_id"]), title=doc["title"], total_responses=agg["total"],
        questions=[_question_stat(q, agg["total"], agg) for q in questions],
    )
