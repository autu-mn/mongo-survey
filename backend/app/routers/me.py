from fastapi import APIRouter

from app.deps import DB, RequiredUser
from app.models.me import MyResponse, Participations
from app.services import me_service

router = APIRouter(prefix="/api/me", tags=["个人主页"])


@router.get("/participations", response_model=Participations, summary="我参与的问卷（P22 / P23）")
def participations(user: RequiredUser, db: DB):
    return me_service.participations(db, user.id)


@router.get("/responses/{response_id}", response_model=MyResponse, summary="查看我的一份实名答卷")
def my_response(response_id: str, user: RequiredUser, db: DB):
    return me_service.my_response(db, user.id, response_id)
