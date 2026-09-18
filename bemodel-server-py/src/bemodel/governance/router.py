from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import GovService

router = APIRouter(prefix="/api/gov")
DB = Depends(get_session)


@router.get("/overview")
def overview(session: Session = DB):
    return ok(GovService(session).overview())


@router.get("/tables")
def tables(session: Session = DB):
    return ok(GovService(session).tables())


@router.get("/issues")
def issues(pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(GovService(session).issues(page_num(pageNum), page_size(pageSize)))


@router.post("/scan")
def scan(session: Session = DB):
    return ok(GovService(session).scan())


@router.post("/issues/{id}/resolve")
def resolve(id: int, session: Session = DB):
    GovService(session).resolve_issue(id)
    return ok()


@router.post("/issues/{id}/ticket")
def ticket(id: int, session: Session = DB):
    return ok(GovService(session).issue_to_ticket(id))
