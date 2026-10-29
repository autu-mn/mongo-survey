"""【第二阶段新增】旧问卷题目到题目身份/版本的幂等迁移。

先检查、备份，再写入：
  .venv/Scripts/python -m scripts.migrate_stage2 --check
  .venv/Scripts/python -m scripts.backup_mongo --output ../backups/stage2-before.zip
  .venv/Scripts/python -m scripts.migrate_stage2 --apply --backup ../backups/stage2-before.zip

旧 responses/drafts 不改写；旧答案不伪造版本来源。
"""

import argparse
import copy
import hashlib
import json
import struct
from pathlib import Path

from bson import BSON, ObjectId
from pymongo.errors import DuplicateKeyError
from zipfile import ZipFile

from app.db import SCHEMA_VERSION, get_db, init_db
from app.repositories import question_items, question_versions
from scripts.backup_mongo import verify_backup


class MigrationConflict(RuntimeError):
    pass


def _same_content(question: dict, version: dict) -> bool:
    return question_versions.content_from_question(question) == {
        key: version[key] for key in question_versions.CONTENT_FIELDS
    }


def _linked_version(db, question: dict):
    item_id = question.get("sourceItemId")
    version_id = question.get("sourceVersionId")
    if (item_id is None) != (version_id is None):
        raise MigrationConflict(f"题目 {question['questionId']} 的来源字段只有一个")
    if item_id is None:
        return None
    if not isinstance(item_id, ObjectId) or not isinstance(version_id, ObjectId):
        raise MigrationConflict(f"题目 {question['questionId']} 的来源 ID 类型不正确")
    item = question_items.find_by_id(db, item_id)
    version = question_versions.find_by_id(db, version_id)
    if item is None or version is None or version["itemId"] != item_id:
        raise MigrationConflict(f"题目 {question['questionId']} 的来源引用不存在或不匹配")
    if not _same_content(question, version):
        raise MigrationConflict(f"题目 {question['questionId']} 的快照与来源版本内容不一致")
    return version


def inspect_database(db) -> dict:
    """只读检查；输出预期新建数量和现存冲突。"""
    counts = {name: db[name].count_documents({}) for name in
              ("users", "surveys", "responses", "drafts")}
    summary = {"database": db.name, "legacyCounts": counts, "questions": 0,
               "alreadyLinked": 0, "toLink": 0, "newItems": 0,
               "newVersions": 0, "conflicts": []}
    for survey in db.surveys.find({}).sort("_id", 1):
        for q in survey["questions"]:
            summary["questions"] += 1
            try:
                if _linked_version(db, q) is not None:
                    summary["alreadyLinked"] += 1
                    continue
                summary["toLink"] += 1
                item = question_items.find_by_origin(db, survey["_id"], q["questionId"])
                if item is None:
                    summary["newItems"] += 1
                    summary["newVersions"] += 1
                    continue
                if item["ownerId"] != survey["ownerId"]:
                    raise MigrationConflict("迁移来源题目的所有者与问卷所有者不同")
                version = question_versions.find_number(db, item["_id"], 1)
                if version is None:
                    summary["newVersions"] += 1
                elif not _same_content(q, version):
                    raise MigrationConflict("迁移来源第 1 版与当前问卷题目不一致")
            except MigrationConflict as exc:
                summary["conflicts"].append({"surveyId": str(survey["_id"]),
                                             "questionId": q["questionId"], "reason": str(exc)})
    return summary


def _ensure_origin(db, survey: dict, question: dict) -> tuple[ObjectId, ObjectId]:
    item = question_items.find_by_origin(db, survey["_id"], question["questionId"])
    if item is None:
        try:
            item = question_items.insert_item(
                db, survey["ownerId"], origin_survey_id=survey["_id"],
                origin_question_id=question["questionId"])
        except DuplicateKeyError:
            item = question_items.find_by_origin(db, survey["_id"], question["questionId"])
    if item is None or item["ownerId"] != survey["ownerId"]:
        raise MigrationConflict(f"题目 {question['questionId']} 的迁移身份冲突")

    version = question_versions.find_number(db, item["_id"], 1)
    if version is None:
        try:
            version = question_versions.insert_version(
                db, item["_id"], 1, None,
                question_versions.content_from_question(question))
        except DuplicateKeyError:
            version = question_versions.find_number(db, item["_id"], 1)
    if version is None or not _same_content(question, version):
        raise MigrationConflict(f"题目 {question['questionId']} 的迁移版本冲突")
    return item["_id"], version["_id"]


def migrate_database(db) -> dict:
    """只添加来源元数据和 schemaVersion；重复运行不新建重复身份/版本。"""
    before = inspect_database(db)
    if before["conflicts"]:
        raise MigrationConflict(json.dumps(before["conflicts"], ensure_ascii=False))
    init_db(db)
    updated = 0
    for survey in db.surveys.find({}).sort("_id", 1):
        questions = copy.deepcopy(survey["questions"])
        for question in questions:
            if _linked_version(db, question) is not None:
                continue
            item_id, version_id = _ensure_origin(db, survey, question)
            question["sourceItemId"] = item_id
            question["sourceVersionId"] = version_id
        if questions == survey["questions"] and survey.get("schemaVersion") == SCHEMA_VERSION:
            continue
        result = db.surveys.update_one(
            {"_id": survey["_id"], "updatedAt": survey["updatedAt"],
             "version": survey["version"]},
            {"$set": {"questions": questions, "schemaVersion": SCHEMA_VERSION}},
        )
        if result.modified_count != 1:
            raise MigrationConflict(f"问卷 {survey['_id']} 在迁移期间被修改；请检查并重跑")
        updated += 1
    after = inspect_database(db)
    if after["conflicts"] or after["toLink"] != 0:
        raise MigrationConflict(f"迁移后仍有未关联题目或冲突：{after}")
    if before["legacyCounts"] != after["legacyCounts"]:
        raise MigrationConflict("迁移期间旧集合文档数量发生变化；请核对")
    return {"updatedSurveys": updated, "before": before, "after": after}


def verify_pre_migration_backup(db, path: Path) -> dict:
    metadata = verify_backup(path)
    if metadata["database"] != db.name:
        raise MigrationConflict("备份所属数据库与当前数据库不同")
    for name in ("users", "surveys", "responses", "drafts"):
        expected = metadata["collections"].get(name, {}).get("count")
        if expected != db[name].count_documents({}):
            raise MigrationConflict(f"备份与当前 {name} 文档数不同；请重新备份")
    return metadata


def audit_against_backup(db, path: Path) -> dict:
    """只读审计：旧集合内容与备份一致；问卷仅允许新增来源字段/schemaVersion。"""
    metadata = verify_pre_migration_backup(db, path)
    unchanged = {}
    for name in ("users", "responses", "drafts"):
        digest = hashlib.sha256()
        for doc in db[name].find({}).sort("_id", 1):
            digest.update(BSON.encode(doc))
        matches = digest.hexdigest() == metadata["collections"][name]["sha256"]
        unchanged[name] = matches
        if not matches:
            raise MigrationConflict(f"{name} 内容与迁移前备份不同")

    with ZipFile(path, "r") as archive:
        with archive.open("surveys.bson") as stream:
            while length_bytes := stream.read(4):
                length = struct.unpack("<i", length_bytes)[0]
                original = BSON(length_bytes + stream.read(length - 4)).decode(
                    codec_options=db.codec_options)
                current = db.surveys.find_one({"_id": original["_id"]})
                if current is None:
                    raise MigrationConflict(f"旧问卷 {original['_id']} 不存在")
                current = copy.deepcopy(current)
                for question in current["questions"]:
                    question.pop("sourceItemId", None)
                    question.pop("sourceVersionId", None)
                current["schemaVersion"] = original["schemaVersion"]
                if current != original:
                    raise MigrationConflict(f"问卷 {original['_id']} 除来源字段外发生变化")
    return {"unchangedCollections": unchanged,
            "surveyContentUnchanged": True,
            "oldSurveyCount": metadata["collections"]["surveys"]["count"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="第二阶段题目来源迁移")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true", help="只读预检")
    actions.add_argument("--apply", action="store_true", help="写入迁移结果")
    actions.add_argument("--audit", action="store_true", help="只读核对迁移后内容")
    parser.add_argument("--backup", type=Path, help="--apply / --audit 必需：已验证的实施前 BSON 备份")
    args = parser.parse_args()
    db = get_db()
    if args.check:
        print(json.dumps(inspect_database(db), ensure_ascii=False, indent=2))
        return
    if args.backup is None:
        parser.error("--apply / --audit 必须指定 --backup")
    if args.audit:
        print(json.dumps(audit_against_backup(db, args.backup), ensure_ascii=False, indent=2))
        return
    verify_pre_migration_backup(db, args.backup)
    print(json.dumps(migrate_database(db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
