"""【第二阶段新增】集合校验、索引、备份和旧数据迁移测试。"""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from app.repositories import question_banks, question_items, question_versions
from scripts.backup_mongo import backup_database, verify_backup
from scripts.migrate_stage2 import MigrationConflict, inspect_database, migrate_database
from tests.test_schema import make_response, make_survey


def test_new_collections_validate_and_index(db):
    owner = ObjectId()
    item = question_items.insert_item(db, owner)
    assert item["visibility"] == "private"
    content = {"type": "single", "title": "年龄段", "description": "", "required": True,
               "options": [{"optionId": "o_a", "text": "成年", "hidden": False},
                           {"optionId": "o_b", "text": "未成年", "hidden": False}],
               "constraints": {}}
    version = question_versions.insert_version(db, item["_id"], 1, None, content)
    assert question_versions.find_latest(db, item["_id"])["_id"] == version["_id"]
    with pytest.raises(DuplicateKeyError):
        question_versions.insert_version(db, item["_id"], 1, None, content)
    with pytest.raises(WriteError):
        db.question_versions.update_one({"_id": version["_id"]}, {"$set": {"unexpected": 1}})
    bank = question_banks.insert_bank(db, owner, "常用题")
    question_banks.add_item(db, bank["_id"], owner, item["_id"])
    question_banks.add_item(db, bank["_id"], owner, item["_id"])
    assert question_banks.find_owned(db, bank["_id"], owner)["itemIds"] == [item["_id"]]
    with pytest.raises(DuplicateKeyError):
        question_banks.insert_bank(db, owner, "常用题")
    assert {"question_items", "question_versions", "question_banks"} <= set(db.list_collection_names())


def test_legacy_origin_unique_and_new_access_indexes(db):
    owner, item_id, version_id = ObjectId(), ObjectId(), ObjectId()
    survey_id = ObjectId()
    question_items.insert_item(db, owner, origin_survey_id=survey_id, origin_question_id="q1")
    with pytest.raises(DuplicateKeyError):
        question_items.insert_item(db, owner, origin_survey_id=survey_id, origin_question_id="q1")
    survey = make_survey(ownerId=owner)
    survey["questions"][0].update(sourceItemId=item_id, sourceVersionId=version_id)
    sid = db.surveys.insert_one(survey).inserted_id
    response = make_response(sid)
    response["answers"][0]["questionVersionId"] = version_id
    db.responses.insert_one(response)
    usage = db.surveys.find({"questions.sourceItemId": item_id, "ownerId": owner,
                             "deletedAt": None}).explain()
    stats = db.responses.find({"answers.questionVersionId": version_id,
                               "surveyId": sid}).explain()
    assert "question_usage" in str(usage["queryPlanner"]["winningPlan"])
    assert "version_survey_answers" in str(stats["queryPlanner"]["winningPlan"])


def test_legacy_documents_accept_optional_source_fields(db):
    item_id, version_id = ObjectId(), ObjectId()
    survey = make_survey()
    survey["questions"][0]["sourceItemId"] = item_id
    survey["questions"][0]["sourceVersionId"] = version_id
    survey["schemaVersion"] = 2
    sid = db.surveys.insert_one(survey).inserted_id
    response = make_response(sid)
    response["answers"][0]["questionVersionId"] = version_id
    response["schemaVersion"] = 2
    db.responses.insert_one(response)
    assert db.responses.count_documents({"surveyId": sid}) == 1
    legacy = make_survey(slug="legacy01")
    db.surveys.insert_one(legacy)


def test_migration_is_idempotent_and_preserves_old_answers(db):
    survey = make_survey(status="published")
    sid = db.surveys.insert_one(survey).inserted_id
    stored_survey = db.surveys.find_one({"_id": sid})
    old_response = make_response(sid)
    rid = db.responses.insert_one(old_response).inserted_id
    old_response = db.responses.find_one({"_id": rid})
    before = inspect_database(db)
    assert (before["questions"], before["toLink"], before["newItems"]) == (2, 2, 2)
    first = migrate_database(db)
    assert first["updatedSurveys"] == 1
    assert first["after"]["toLink"] == 0
    migrated = db.surveys.find_one({"_id": sid})
    assert migrated["version"] == stored_survey["version"]
    assert migrated["updatedAt"] == stored_survey["updatedAt"]
    for original, linked in zip(survey["questions"], migrated["questions"]):
        assert {k: v for k, v in linked.items() if k not in ("sourceItemId", "sourceVersionId")} == original
        item = db.question_items.find_one({"_id": linked["sourceItemId"]})
        version = db.question_versions.find_one({"_id": linked["sourceVersionId"]})
        assert (item["originSurveyId"], item["originQuestionId"]) == (sid, original["questionId"])
        assert version["itemId"] == item["_id"]
    assert db.responses.find_one({"_id": rid}) == old_response
    second = migrate_database(db)
    assert second["updatedSurveys"] == 0
    assert db.question_items.count_documents({}) == 2
    assert db.question_versions.count_documents({}) == 2


def test_migration_resumes_after_item_insert(db):
    survey = make_survey(questions=[make_survey()["questions"][0]])
    sid = db.surveys.insert_one(survey).inserted_id
    question_items.insert_item(db, survey["ownerId"], origin_survey_id=sid,
                               origin_question_id="q1")
    assert inspect_database(db)["newVersions"] == 1
    result = migrate_database(db)
    assert result["after"]["toLink"] == 0
    assert db.question_items.count_documents({}) == 1
    assert db.question_versions.count_documents({}) == 1


def test_migration_detects_changed_existing_version(db):
    survey = make_survey(questions=[make_survey()["questions"][0]])
    sid = db.surveys.insert_one(survey).inserted_id
    item = question_items.insert_item(db, survey["ownerId"], origin_survey_id=sid,
                                      origin_question_id="q1")
    changed = deepcopy(question_versions.content_from_question(survey["questions"][0]))
    changed["title"] = "另一个题"
    question_versions.insert_version(db, item["_id"], 1, None, changed)
    assert inspect_database(db)["conflicts"]
    with pytest.raises(MigrationConflict):
        migrate_database(db)
    assert "sourceItemId" not in db.surveys.find_one({"_id": sid})["questions"][0]


def test_backup_preserves_bson_and_matches_manifest(db, tmp_path):
    db.users.insert_one({"username": "backup_user", "passwordHash": "$2b$12$" + "x" * 53,
                         "createdAt": datetime.now(timezone.utc), "schemaVersion": 1})
    path = tmp_path / "pre-migration.zip"
    metadata = backup_database(db, path)
    assert metadata == verify_backup(path)
    assert metadata["collections"]["users"]["count"] == 1
    with pytest.raises(FileExistsError):
        backup_database(db, path)
