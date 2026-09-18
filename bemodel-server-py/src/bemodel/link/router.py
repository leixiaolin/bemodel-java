from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.base_dao import BaseDAO
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import LinkService
from .entities import LinkRel, LinkNode

router = APIRouter(prefix="/api/link")
DB = Depends(get_session)


@router.get("/list")
def nodes(nodeType: str | None = None, conceptCode: str | None = None, pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    service = LinkService(session)
    return ok(service.page(*service.conditions(nodeType, conceptCode), page=page_num(pageNum), size=page_size(pageSize), order=(LinkNode.occurred_at.desc(),)))


@router.get("/chain/{conceptCode}")
def chain(conceptCode: str, session: Session = DB):
    return ok(LinkService(session).chain_by_concept(conceptCode))


@router.get("/chain/{conceptCode}/rels")
def chain_rels(conceptCode: str, session: Session = DB):
    return ok(LinkService(session).rels_by_concept(conceptCode))


@router.get("/trace/{refNo}")
def trace(refNo: str, session: Session = DB):
    return ok(LinkService(session).trace(refNo))


@router.post("/rel")
def rel(body: dict, session: Session = DB):
    return ok(LinkService(session).add_rel(body.get("fromRefNo"), body.get("toRefNo"), body.get("relType"), body.get("remark")))


@router.delete("/rel/{id}")
def delete_rel(id: int, session: Session = DB):
    BaseDAO(session, LinkRel).delete_by_id(id)
    return ok()


@router.post("/auto-ticket")
def auto_ticket(session: Session = DB):
    return ok(LinkService(session).auto_ticket())


@router.post("")
def create(body: dict, session: Session = DB):
    return ok(LinkService(session).insert(body))


@router.put("")
def update(body: dict, session: Session = DB):
    return ok(LinkService(session).update_by_id(body))
