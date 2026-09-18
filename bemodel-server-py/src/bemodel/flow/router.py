from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import FlowService

router = APIRouter(prefix='/api/flow')
DB = Depends(get_session)


@router.get('/patients')
def patients(keyword: str | None = None, pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(FlowService(session).patients(keyword, page_num(pageNum), page_size(pageSize)))


@router.get('/loop/{inhosNo}')
def loop(inhosNo: str, session: Session = DB):
    return ok(FlowService(session).loop(inhosNo))


@router.get('/opd/patients')
def opd_patients(keyword: str | None = None, pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(FlowService(session).opd_patients(keyword, page_num(pageNum), page_size(pageSize)))


@router.get('/opd/loop/{cardNo}')
def opd_loop(cardNo: str, session: Session = DB):
    return ok(FlowService(session).opd_loop(cardNo))


@router.get('/staff')
def staff(name: str, session: Session = DB):
    return ok(FlowService(session).staff_detail(name))
