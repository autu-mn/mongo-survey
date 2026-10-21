from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.deps import DB, RequiredUser
from app.errors import AppError
from app.models.question import LogicIn, QuestionIn, ReorderIn, SurveyPatch
from app.models.survey import SurveyDetail
from app.services import question_service as qs
from app.services import survey_service as svc

router = APIRouter(prefix="/api/surveys/{survey_id}", tags=["创作者：编辑页"])


def expected_updated_at(
    if_match: Annotated[str | None, Header(alias="If-Match",
                                           description="打开编辑页时读到的 updatedAt，用于检测并发修改")] = None,
) -> datetime | None:
    if if_match is None:
        return None
    try:
        value = datetime.fromisoformat(if_match.strip('"'))
    except ValueError:
        raise AppError(422, "validation_error", "If-Match 必须是 ISO 时间")
    if value.tzinfo is None:
        raise AppError(422, "validation_error", "If-Match 必须带时区")
    return value


Expected = Annotated[datetime | None, Depends(expected_updated_at)]


def _out(doc: dict) -> SurveyDetail:
    return svc.to_detail(doc, svc.now_utc())


@router.patch("", response_model=SurveyDetail, summary="修改标题、说明")
def patch_survey(survey_id: str, body: SurveyPatch, user: RequiredUser, db: DB, expected: Expected):
    return _out(qs.update_basic(db, svc.parse_survey_id(survey_id), user.id, body, expected))


@router.post("/questions", response_model=SurveyDetail, status_code=201, summary="添加题目（追加到末尾）")
def add_question(survey_id: str, body: QuestionIn, user: RequiredUser, db: DB, expected: Expected):
    return _out(qs.add_question(db, svc.parse_survey_id(survey_id), user.id, body, expected))


@router.put("/questions/order", response_model=SurveyDetail, summary="调整题目顺序")
def reorder(survey_id: str, body: ReorderIn, user: RequiredUser, db: DB, expected: Expected):
    return _out(qs.reorder(db, svc.parse_survey_id(survey_id), user.id, body, expected))


@router.put("/questions/{question_id}", response_model=SurveyDetail, summary="修改题目")
def update_question(survey_id: str, question_id: str, body: QuestionIn, user: RequiredUser,
                    db: DB, expected: Expected):
    return _out(qs.update_question(db, svc.parse_survey_id(survey_id), user.id, question_id, body, expected))


@router.delete("/questions/{question_id}", response_model=SurveyDetail,
               summary="删除题目（草稿直接删除，已发布改为隐藏）")
def delete_question(survey_id: str, question_id: str, user: RequiredUser, db: DB, expected: Expected):
    return _out(qs.delete_question(db, svc.parse_survey_id(survey_id), user.id, question_id, expected))


@router.post("/questions/{question_id}/restore", response_model=SurveyDetail, summary="恢复已隐藏的题目")
def restore_question(survey_id: str, question_id: str, user: RequiredUser, db: DB, expected: Expected):
    return _out(qs.restore_question(db, svc.parse_survey_id(survey_id), user.id, question_id, expected))


@router.put("/questions/{question_id}/logic", response_model=SurveyDetail, summary="保存跳转规则")
def set_logic(survey_id: str, question_id: str, body: LogicIn, user: RequiredUser,
              db: DB, expected: Expected):
    return _out(qs.set_logic(db, svc.parse_survey_id(survey_id), user.id, question_id, body, expected))
