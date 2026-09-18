from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .entities import AlertNotice
from .services import NoticeService, InspectService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


@router.post("/inspect/run")
def inspect(session: Session = DB):
    return ok(InspectService(session).run_all())


@router.get("/notice/unread-count")
def unread(session: Session = DB):
    return ok({"count": NoticeService(session).unread_count()})


@router.get("/notice/list")
def notices(pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(NoticeService(session).page(page=page_num(pageNum), size=page_size(pageSize), order=(AlertNotice.status, AlertNotice.id.desc())))


@router.post("/notice/{id}/read")
def read(id: int, session: Session = DB):
    NoticeService(session).mark_read(id)
    return ok()


@router.post("/notice/read-all")
def read_all(session: Session = DB):
    return ok({"marked": NoticeService(session).mark_all_read()})
