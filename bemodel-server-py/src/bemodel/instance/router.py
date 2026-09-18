from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.page_result import page_num, page_size
from bemodel.core.result import ok
from .services import InstanceService

router = APIRouter(prefix="/api/instance")


@router.get("/{conceptCode}")
def instances(conceptCode: str, tableName: str | None = None, pageNum: int | None = None,
              pageSize: int | None = None, session: Session = Depends(get_session)):
    return ok(InstanceService(session).instances(conceptCode, tableName, page_num(pageNum), page_size(pageSize)))
