from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.deps import DB, RequiredUser
from app.models.stats import SurveyStats
from app.services import export_service, stats_service
from app.services.survey_service import parse_survey_id

router = APIRouter(prefix="/api/surveys/{survey_id}", tags=["创作者：统计与导出"])


@router.get("/stats", response_model=SurveyStats, summary="整卷统计（P16）")
def survey_stats(survey_id: str, user: RequiredUser, db: DB):
    return stats_service.survey_stats(db, parse_survey_id(survey_id), user.id)


@router.get("/stats/{question_id}", response_model=SurveyStats, summary="单题统计（P17）")
def question_stats(survey_id: str, question_id: str, user: RequiredUser, db: DB):
    return stats_service.survey_stats(db, parse_survey_id(survey_id), user.id, question_id)


@router.get("/export.csv", summary="导出 CSV（P18）", response_class=StreamingResponse)
def export(survey_id: str, user: RequiredUser, db: DB):
    title, rows = export_service.export_csv(db, parse_survey_id(survey_id), user.id)
    filename = quote(f"{title}.csv")
    return StreamingResponse(
        rows, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
