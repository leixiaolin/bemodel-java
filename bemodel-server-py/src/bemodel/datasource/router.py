from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import DatasourceService, SchemaScanService, MappingService
from .governance import OntologyAnalysisService, OntologyChangeSetService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


@router.get("/datasource/list")
def list_datasources(session: Session = DB):
    return ok(DatasourceService(session).list_all())


@router.post("/datasource")
def create(body: dict, session: Session = DB):
    return ok(DatasourceService(session).create(body))


@router.patch("/datasource/{dsCode}/status")
def update_status(dsCode: str, body: dict, session: Session = DB):
    return ok(DatasourceService(session).update_status(dsCode, body.get("status")))


@router.delete("/datasource/{dsCode}")
def delete_datasource(dsCode: str, session: Session = DB):
    DatasourceService(session).soft_delete(dsCode)
    return ok()


@router.post("/datasource/test")
def test(body: dict, session: Session = DB):
    return ok(DatasourceService(session).test_connection(body))


@router.post("/datasource/scan/{dsCode}")
def scan(dsCode: str, request: Request, session: Session = DB):
    return ok({"dsCode": dsCode, **SchemaScanService(session).scan(dsCode, actor(request))})


def actor(request: Request):
    claims = getattr(request.state, "claims", None) or {}
    return claims.get("sub") or claims.get("username")


@router.post("/datasource/{dsCode}/ontology-analysis")
def start_analysis(dsCode: str, body: dict | None = None, request: Request = None, session: Session = DB):
    body = body or {}
    task = OntologyAnalysisService(session).enqueue(dsCode, actor(request),
        str(body.get("force", False)).lower() == "true", str(body.get("aiOnly", False)).lower() == "true")
    return ok(OntologyAnalysisService(session).latest(dsCode))


@router.get("/datasource/{dsCode}/ontology-analysis/latest")
def latest_analysis(dsCode: str, session: Session = DB):
    DatasourceService(session).require(dsCode)
    return ok(OntologyAnalysisService(session).latest(dsCode))


@router.get("/ontology-change-set/{id}")
def change_set(id: int, session: Session = DB):
    return ok(OntologyChangeSetService(session).detail(id))


@router.patch("/ontology-change-set/{id}/items/{itemId}")
def update_change_item(id: int, itemId: int, body: dict, request: Request, session: Session = DB):
    return ok(OntologyChangeSetService(session).update_item(id, itemId, body, actor(request)))


@router.post("/ontology-change-set/{id}/adopt")
def adopt_change_items(id: int, body: dict, request: Request, session: Session = DB):
    return ok(OntologyChangeSetService(session).adopt(id, body.get("itemIds"), actor(request)))


@router.post("/ontology-change-set/{id}/publish")
def publish_change_set(id: int, request: Request, session: Session = DB):
    return ok(OntologyChangeSetService(session).publish(id, actor(request)))


@router.get("/datasource/tables/{dsCode}")
def tables(dsCode: str, session: Session = DB):
    return ok(SchemaScanService(session).tables(dsCode))


@router.get("/datasource/columns/{dsCode}")
def columns(dsCode: str, tableName: str | None = None, session: Session = DB):
    return ok(SchemaScanService(session).columns(dsCode, tableName))


@router.get("/mapping/list")
def mappings(dsCode: str | None = None, tableName: str | None = None, session: Session = DB):
    return ok(MappingService(session).list(dsCode, tableName))


@router.post("/mapping/batch")
def batch(body: list[dict], session: Session = DB):
    MappingService(session).save_batch(body)
    return ok()


@router.delete("/mapping/{id}")
def delete(id: int, session: Session = DB):
    MappingService(session).delete_by_id(id)
    return ok()


@router.get("/mapping/ai-suggest")
def suggest(dsCode: str, tableName: str, session: Session = DB):
    return ok(MappingService(session).ai_suggest(dsCode, tableName))
