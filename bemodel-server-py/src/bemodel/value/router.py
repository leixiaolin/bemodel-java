from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import ValueService

router = APIRouter(prefix='/api/value')


@router.get('/compare')
def compare(session: Session = Depends(get_session)):
    return ok(ValueService(session).compare())
