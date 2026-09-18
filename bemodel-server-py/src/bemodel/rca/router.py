from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import RcaEngine

router = APIRouter(prefix='/api/rca')
DB = Depends(get_session)


@router.post('/start')
def start(ticketRef: str, session: Session = DB):
    return ok(RcaEngine(session).start(ticketRef))


@router.get('/list')
def cases(session: Session = DB):
    return ok(RcaEngine(session).list_cases())


@router.get('/{caseId}')
def detail(caseId: int, session: Session = DB):
    return ok(RcaEngine(session).case_detail(caseId))
