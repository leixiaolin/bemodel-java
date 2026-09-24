from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.result import ok
from .services import DatasourceService, SchemaScanService, MappingService

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
def scan(dsCode: str, session: Session = DB):
    return ok({"dsCode": dsCode, "tableCount": SchemaScanService(session).scan(dsCode)})


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
