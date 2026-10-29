from fastapi import APIRouter, Response

from app.deps import DB, RequiredUser
from app.models.survey import Settings, SurveyCreate, SurveyDetail, SurveyListItem
from app.services import survey_service as svc

router = APIRouter(prefix="/api/surveys", tags=["创作者：问卷管理"])


@router.post("", response_model=SurveyDetail, status_code=201, summary="新建问卷（草稿）")
def create_survey(body: SurveyCreate, user: RequiredUser, db: DB):
    return svc.to_detail(svc.create_survey(db, user.id, body), svc.now_utc())


@router.get("", response_model=list[SurveyListItem], summary="我的问卷列表（P3）")
def list_surveys(user: RequiredUser, db: DB):
    return svc.list_surveys(db, user.id)


@router.get("/{survey_id}", response_model=SurveyDetail, summary="问卷详情（P4 / P7）")
def get_survey(survey_id: str, user: RequiredUser, db: DB):
    doc = svc.get_owned(db, svc.parse_survey_id(survey_id), user.id)
    return svc.to_detail(doc, svc.now_utc())


@router.post("/{survey_id}/copy", response_model=SurveyDetail, status_code=201,
             summary="【第二阶段新增】复制问卷为新草稿（P32）")
def copy_survey(survey_id: str, user: RequiredUser, db: DB):
    return svc.to_detail(svc.copy_survey(db, svc.parse_survey_id(survey_id), user.id), svc.now_utc())


@router.delete("/{survey_id}", status_code=204, summary="删除问卷（软删除，P6）")
def delete_survey(survey_id: str, user: RequiredUser, db: DB):
    svc.delete(db, svc.parse_survey_id(survey_id), user.id)
    return Response(status_code=204)


@router.get("/{survey_id}/settings", response_model=Settings, summary="读取分享设置（P10）")
def get_settings(survey_id: str, user: RequiredUser, db: DB):
    doc = svc.get_owned(db, svc.parse_survey_id(survey_id), user.id)
    return Settings.from_doc(doc["settings"])


@router.put("/{survey_id}/settings", response_model=Settings, summary="保存分享设置（P11）")
def put_settings(survey_id: str, body: Settings, user: RequiredUser, db: DB):
    doc = svc.update_settings(db, svc.parse_survey_id(survey_id), user.id, body)
    return Settings.from_doc(doc["settings"])


@router.post("/{survey_id}/publish", response_model=SurveyDetail, summary="发布（草稿 → 已发布）")
def publish(survey_id: str, user: RequiredUser, db: DB):
    return svc.to_detail(svc.publish(db, svc.parse_survey_id(survey_id), user.id), svc.now_utc())


@router.post("/{survey_id}/close", response_model=SurveyDetail, summary="关闭（已发布 → 已关闭，P5）")
def close(survey_id: str, user: RequiredUser, db: DB):
    return svc.to_detail(svc.close(db, svc.parse_survey_id(survey_id), user.id), svc.now_utc())


@router.post("/{survey_id}/reopen", response_model=SurveyDetail, summary="重新开放（已关闭 → 已发布，P5）")
def reopen(survey_id: str, user: RequiredUser, db: DB):
    return svc.to_detail(svc.reopen(db, svc.parse_survey_id(survey_id), user.id), svc.now_utc())


@router.post("/{survey_id}/recount", response_model=SurveyDetail, summary="按实际答卷数校准计数器")
def recount(survey_id: str, user: RequiredUser, db: DB):
    return svc.to_detail(svc.recount(db, svc.parse_survey_id(survey_id), user.id), svc.now_utc())
