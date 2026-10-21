from fastapi import APIRouter

from app.deps import DB, OptionalUser, RequiredUser
from app.models.public import EntryOut, NextIn, NextOut, PublicSurvey, SubmitIn, SubmitOut
from app.services import fill_service
from app.services.survey_service import parse_survey_id

router = APIRouter(prefix="/api/public/surveys/{slug}", tags=["填写者"])
preview_router = APIRouter(prefix="/api/surveys/{survey_id}/preview", tags=["创作者：预览"])


@router.get("", response_model=EntryOut, summary="填写入口：返回状态与问卷（P12 / P13）")
def entry(slug: str, user: OptionalUser, db: DB):
    return fill_service.entry(db, slug, user)


@router.post("/next", response_model=NextOut, summary="校验当前题并计算下一题（P14）")
def next_question(slug: str, body: NextIn, user: OptionalUser, db: DB):
    return fill_service.next_question(db, slug, user, body)


@router.post("/responses", response_model=SubmitOut, status_code=201, summary="提交答卷（P15）")
def submit(slug: str, body: SubmitIn, user: OptionalUser, db: DB):
    return fill_service.submit(db, slug, user, body)


@preview_router.get("", response_model=PublicSurvey, summary="预览（P9，草稿也可以）")
def preview(survey_id: str, user: RequiredUser, db: DB):
    return fill_service.preview(db, parse_survey_id(survey_id), user.id)


@preview_router.post("/next", response_model=NextOut, summary="预览时计算下一题（不写库）")
def preview_next(survey_id: str, body: NextIn, user: RequiredUser, db: DB):
    return fill_service.preview_next(db, parse_survey_id(survey_id), user.id, body)
