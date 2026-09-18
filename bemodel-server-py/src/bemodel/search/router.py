from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import SearchService

router = APIRouter(prefix="/api/search")


@router.get("")
def search(q: str, session: Session = Depends(get_session)):
    return ok(SearchService(session).search(q))
