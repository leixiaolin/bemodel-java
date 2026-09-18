from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import RdfService, ShaclService

router = APIRouter(prefix="/api/rdf")


@router.get("/patient/{inhosNo}")
def export(inhosNo: str, mask: bool = True, session: Session = Depends(get_session)):
    safe_name = inhosNo.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(RdfService(session).export_patient(inhosNo, mask), media_type="text/turtle; charset=utf-8",
                    headers={"Content-Type": "text/turtle;charset=UTF-8", "Content-Disposition": f'form-data; name="attachment"; filename="{safe_name}.ttl"'})


@router.post("/validate/{inhosNo}")
def validate(inhosNo: str, session: Session = Depends(get_session)):
    return ok(ShaclService(session).validate_patient(inhosNo))
