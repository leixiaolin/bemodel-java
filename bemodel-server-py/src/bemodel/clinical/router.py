from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import QcService, AlertService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


@router.get("/qc/records")
def records(keyword: str | None = None, pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(QcService(session).records_page(keyword, page_num(pageNum), page_size(pageSize)))


@router.post("/qc/check/{recordId}")
def check(recordId: str, session: Session = DB):
    return ok(QcService(session).check(recordId))


@router.post("/qc/check-all")
def check_all(session: Session = DB):
    return ok(QcService(session).check_all())


@router.get("/qc/result/{recordId}")
def result(recordId: str, session: Session = DB):
    return ok(QcService(session).latest_result(recordId))


@router.post("/alert/detect")
def detect(session: Session = DB):
    return ok(AlertService(session).detect())
