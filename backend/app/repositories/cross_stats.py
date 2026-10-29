"""【第二阶段新增】P34：本人问卷中的版本答案与旧答案读取。"""


def owned_surveys_for_version(db, owner_id, version_id):
    return list(db.surveys.find(
        {"ownerId": owner_id, "deletedAt": None,
         "questions.sourceVersionId": version_id},
        {"questions.questionId": 1, "questions.sourceVersionId": 1},
    ))


def item_exists(db, item_id):
    return db.question_items.find_one({"_id": item_id})


def versioned_answers(db, survey_ids, version_id):
    return db.responses.aggregate([
        {"$match": {"surveyId": {"$in": survey_ids},
                    "answers.questionVersionId": version_id}},
        {"$unwind": "$answers"},
        {"$match": {"answers.questionVersionId": version_id}},
        {"$project": {"surveyId": 1, "answer": "$answers"}},
    ])


def unattributed_answers(db, survey_ids):
    return db.responses.aggregate([
        {"$match": {"surveyId": {"$in": survey_ids},
                    "answers": {"$elemMatch": {"questionVersionId": {"$exists": False}}}}},
        {"$unwind": "$answers"},
        {"$match": {"answers.questionVersionId": {"$exists": False}}},
        {"$project": {"surveyId": 1, "questionId": "$answers.questionId"}},
    ])
