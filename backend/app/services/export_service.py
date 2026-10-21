"""导出 CSV（P18）：游标分批读取答卷，边读边输出，不把全部数据装入内存。"""

import csv
import io
from datetime import timedelta, timezone
from typing import Iterator

from bson import ObjectId
from pymongo.database import Database

from app.repositories import responses as responses_repo
from app.repositories import users as users_repo
from app.services.survey_service import get_owned

DISPLAY_TZ = timezone(timedelta(hours=8))
CHUNK = 200
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(text: str) -> str:
    """防止 CSV 公式注入：以 = + - @ 开头的文本在 Excel 中会被当作公式执行。"""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _row(values: list) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow(values)
    return buf.getvalue()


def _cell(q: dict, value, option_text: dict[str, str]) -> str:
    if value is None:
        return ""
    if q["type"] == "single":
        return option_text.get(value, value)
    if q["type"] == "multiple":
        return "；".join(option_text.get(v, v) for v in value)
    if q["type"] == "text":
        return _safe(value)
    return str(value)


def _filler(doc: dict, names: dict) -> str:
    if doc.get("respondentId") is not None:
        return names.get(doc["respondentId"], "（已注销）")
    return "匿名" if doc["submitterKey"].startswith("a:") else "访客"


def export_csv(db: Database, survey_id: ObjectId, owner_id: ObjectId) -> tuple[str, Iterator[str]]:
    survey = get_owned(db, survey_id, owner_id)
    questions = sorted(survey["questions"], key=lambda q: q["order"])
    option_text = {o["optionId"]: o["text"] for q in questions for o in q["options"]}
    header = ["序号", "提交时间", "填写者"] + [
        _safe(q["title"]) + ("（已删除）" if q["hidden"] else "") for q in questions
    ]

    def rows() -> Iterator[str]:
        yield "\ufeff"  # UTF-8 BOM，Excel 才能正确识别中文
        yield _row(header)
        seq = 0
        chunk: list[dict] = []
        cursor = responses_repo.iter_for_export(db, survey_id)
        for doc in cursor:
            chunk.append(doc)
            if len(chunk) >= CHUNK:
                seq = yield from _flush(chunk, seq)
                chunk = []
        if chunk:
            yield from _flush(chunk, seq)

    def _flush(chunk: list[dict], seq: int):
        ids = list({d["respondentId"] for d in chunk if d.get("respondentId") is not None})
        names = users_repo.usernames(db, ids)
        for doc in chunk:
            seq += 1
            by_q = {a["questionId"]: a["value"] for a in doc["answers"]}
            yield _row([
                seq,
                doc["submittedAt"].astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                _filler(doc, names),
                *[_cell(q, by_q.get(q["questionId"]), option_text) for q in questions],
            ])
        return seq

    return survey["title"], rows()
