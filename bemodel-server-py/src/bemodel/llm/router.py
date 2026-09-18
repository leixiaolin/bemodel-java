from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .entities import LlmLog
from .services import LlmLogService

router = APIRouter(prefix="/api/llm")


@router.get("/log/list")
def logs(pageNum: int | None = None, pageSize: int | None = None, session: Session = Depends(get_session)):
    return ok(LlmLogService(session).page(page=page_num(pageNum), size=page_size(pageSize), order=(LlmLog.id.desc(),)))


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    return ok(LlmLogService(session).stats())
