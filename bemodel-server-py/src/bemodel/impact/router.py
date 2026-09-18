from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import ImpactService

router = APIRouter(prefix="/api/impact")


@router.post("/analyze")
def analyze(body: dict, session: Session = Depends(get_session)):
    depth = body.get("depth")
    return ok(ImpactService(session).analyze(body.get("conceptCode"), body.get("changeDesc"),
                int(depth) if depth is not None and str(depth).strip() else None))
