"""【第二阶段新增】命名题库 API。"""

from fastapi import APIRouter, Response

from app.deps import DB, RequiredUser
from app.models.question_bank import BankName
from app.services import question_bank_service as svc
from app.services.question_item_service import parse_id

router = APIRouter(prefix="/api/question-banks", tags=["命名题库"])


@router.get("")
def list_banks(user: RequiredUser, db: DB):
    return svc.list_banks(db, user.id)


@router.post("", status_code=201)
def create_bank(body: BankName, user: RequiredUser, db: DB):
    return svc.create_bank(db, user.id, body.name)


@router.get("/{bank_id}")
def get_bank(bank_id: str, user: RequiredUser, db: DB):
    return svc.get_bank(db, parse_id(bank_id), user.id)


@router.put("/{bank_id}")
def rename_bank(bank_id: str, body: BankName, user: RequiredUser, db: DB):
    return svc.rename_bank(db, parse_id(bank_id), user.id, body.name)


@router.delete("/{bank_id}", status_code=204)
def delete_bank(bank_id: str, user: RequiredUser, db: DB):
    svc.delete_bank(db, parse_id(bank_id), user.id)
    return Response(status_code=204)


@router.put("/{bank_id}/items/{item_id}")
def add_item(bank_id: str, item_id: str, user: RequiredUser, db: DB):
    return svc.add_item(db, parse_id(bank_id), user.id, parse_id(item_id))


@router.delete("/{bank_id}/items/{item_id}")
def remove_item(bank_id: str, item_id: str, user: RequiredUser, db: DB):
    return svc.remove_item(db, parse_id(bank_id), user.id, parse_id(item_id))
