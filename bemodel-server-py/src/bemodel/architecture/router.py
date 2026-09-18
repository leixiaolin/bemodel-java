from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import ArchitectureService

router = APIRouter(prefix="/api/architecture")


@router.get("/overview")
def overview(session: Session = Depends(get_session)):
    return ok(ArchitectureService(session).overview())
