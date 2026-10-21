from bson import ObjectId
from pymongo.database import Database


def has_single_submission(db: Database, survey_id: ObjectId, key: str) -> bool:
    """P13 是否已填过。条件中必须带 singleSubmission: true，
    查询才能命中部分索引 uniq_single_submission（部分索引只对满足其过滤条件的查询生效）。"""
    return db.responses.find_one(
        {"surveyId": survey_id, "submitterKey": key, "singleSubmission": True},
        {"_id": 1},
    ) is not None


def insert_response(db: Database, doc: dict) -> ObjectId:
    """P15 第二步：插入答卷。限制每人一次时，重复提交由唯一部分索引抛出 DuplicateKeyError。"""
    return db.responses.insert_one(doc).inserted_id


def stats_pipeline(survey_id: ObjectId, question_id: str | None = None) -> list[dict]:
    """P16 整卷统计 / P17 单题统计：一次聚合得出全部统计量。

    $match + $sort 走 {surveyId, submittedAt} 索引；$facet 内各分支各自 $unwind answers，
    单题统计只是在 $unwind 之后多一个 $match。
    """
    per_answer = [{"$unwind": "$answers"}]
    if question_id is not None:
        per_answer.append({"$match": {"answers.questionId": question_id}})

    return [
        {"$match": {"surveyId": survey_id}},
        {"$sort": {"submittedAt": 1, "_id": 1}},
        {"$facet": {
            # 答卷总数
            "total": [{"$count": "n"}],
            # 每道题有多少人回答（被跳过或选填未答的不计）
            "answered": per_answer + [
                {"$group": {"_id": "$answers.questionId", "n": {"$sum": 1}}},
            ],
            # 单选 / 多选每个选项被选次数：单选的 value 是字符串，$unwind 会把它当作单元素数组
            "optionCounts": per_answer + [
                {"$match": {"answers.type": {"$in": ["single", "multiple"]}}},
                {"$unwind": "$answers.value"},
                {"$group": {"_id": {"q": "$answers.questionId", "o": "$answers.value"}, "n": {"$sum": 1}}},
            ],
            # 数字题平均值、最小值、最大值
            "numbers": per_answer + [
                {"$match": {"answers.type": "number"}},
                {"$group": {"_id": "$answers.questionId",
                            "avg": {"$avg": "$answers.value"},
                            "min": {"$min": "$answers.value"},
                            "max": {"$max": "$answers.value"}}},
            ],
            # 填空题全部内容（按提交时间顺序）
            "values": per_answer + [
                {"$match": {"answers.type": {"$in": ["text", "number"]}}},
                {"$group": {"_id": "$answers.questionId", "values": {"$push": "$answers.value"}}},
            ],
        }},
    ]


def aggregate_stats(db: Database, survey_id: ObjectId, question_id: str | None = None) -> dict:
    return next(db.responses.aggregate(stats_pipeline(survey_id, question_id)))


def iter_for_export(db: Database, survey_id: ObjectId, batch_size: int = 500):
    """P18 导出：游标按提交时间顺序分批读取，不把全部答卷一次装入内存。
    同一毫秒提交的答卷 submittedAt 相同，用 _id 作为第二排序键保证顺序稳定。"""
    return (db.responses
            .find({"surveyId": survey_id},
                  {"respondentId": 1, "submitterKey": 1, "submittedAt": 1, "answers": 1})
            .sort([("submittedAt", 1), ("_id", 1)])
            .batch_size(batch_size))
