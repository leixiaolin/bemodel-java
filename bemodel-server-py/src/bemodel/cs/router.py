from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import CsService

router = APIRouter(prefix='/api/cs')
DB = Depends(get_session)


@router.get('/ticket/{id}/diagnosis')
def diagnosis(id: int, session: Session = DB):
    return ok(CsService(session).diagnosis(id))


@router.post('/ticket/{id}/refund')
def refund(id: int, operator: str = '客服 小周', session: Session = DB):
    return ok(CsService(session).refund_action(id, operator))


@router.post('/ask')
def ask(body: dict, session: Session = DB):
    return ok(CsService(session).ask(body.get('question'), body.get('scene')))


@router.post('/feedback')
def feedback(body: dict, session: Session = DB):
    correct = str(body.get('correct')).lower() in ('true', '1')
    def value(key):
        return None if body.get(key) is None else str(body[key])
    return ok(CsService(session).save_feedback(value('question'), value('intent'), value('router'), int(correct), value('comment')))


@router.get('/feedback/list')
def feedback_list(pageNum: int | None = None, pageSize: int | None = None, session: Session = DB):
    return ok(CsService(session).feedback_page(page_num(pageNum), page_size(pageSize)))
