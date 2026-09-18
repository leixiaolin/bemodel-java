from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.base_dao import BaseDAO
from bemodel.core.result import ok, to_camel_dict
from .entities import Axiom, Release
from .services import RuleService, ActionService, ReleaseService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


def element_router(path, service, parameter):
    child = APIRouter(prefix=path)
    @child.get("/list")
    def list_elements(conceptCode: str | None = None, session: Session = DB):
        return ok(service(session).list(conceptCode))
    @child.post("")
    def create(body: dict, session: Session = DB):
        return ok(service(session).create(body))
    @child.put("")
    def update(body: dict, session: Session = DB):
        return ok(service(session).update_by_id(body))
    @child.post("/transition/{code}")
    def transition(code: str, target: str, session: Session = DB):
        return ok(service(session).transition(code, target))
    @child.delete("/{id}")
    def delete(id: int, session: Session = DB):
        service(session).delete_by_id(id)
        return ok()
    return child


router.include_router(element_router("/rule", RuleService, "ruleCode"))
router.include_router(element_router("/action", ActionService, "actionCode"))


@router.get("/axiom/list")
def axioms(session: Session = DB):
    return ok(BaseDAO(session, Axiom).select_list(order=(Axiom.axiom_code,)))


@router.post("/axiom")
def create_axiom(body: dict, session: Session = DB):
    return ok(BaseDAO(session, Axiom).insert(body))


@router.delete("/axiom/{id}")
def delete_axiom(id: int, session: Session = DB):
    BaseDAO(session, Axiom).delete_by_id(id)
    return ok()


@router.get("/release/list")
def releases(session: Session = DB):
    rows = to_camel_dict(ReleaseService(session).select_list(order=(Release.id.desc(),)))
    for row in rows:
        row["snapshotJson"] = None
    return ok(rows)


@router.get("/release/current")
def current(session: Session = DB):
    return ok({"version": ReleaseService(session).current_tag() or "未发布"})


@router.post("/release/publish")
def publish(body: dict, session: Session = DB):
    return ok(ReleaseService(session).publish(body.get("changeSummary"), body.get("releasedBy"), str(body.get("force")).lower() == "true"))


@router.get("/release/{id}")
def detail(id: int, session: Session = DB):
    return ok(ReleaseService(session).select_by_id(id))
