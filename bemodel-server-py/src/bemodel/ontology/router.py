from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from bemodel.core.database import get_session
from bemodel.core.base_dao import BaseDAO
from bemodel.core.result import ok
from .entities import Attribute, Relation, Domain, Term, Metric, Disjoint
from .services import ConceptService, RelationService, DisjointService, OntologyCheckService, MetricService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


@router.get("/drift/scan")
def drift(session: Session = DB):
    from .drift_service import DriftService
    return ok(DriftService(session).scan())


@router.post("/ontology/import/preview")
def preview_owl(file: UploadFile = File(...), session: Session = DB):
    from .owl_import import OwlImportService
    return ok(OwlImportService(session).preview(file.file.read(10 * 1024 * 1024 + 1), file.filename))


@router.post("/ontology/import/execute")
def execute_owl(file: UploadFile = File(...), session: Session = DB):
    from .owl_import import OwlImportService
    return ok(OwlImportService(session).execute(file.file.read(10 * 1024 * 1024 + 1), file.filename))


@router.get("/domain/list")
def domains(session: Session = DB):
    return ok(BaseDAO(session, Domain).select_list(order=(Domain.sort,)))


@router.post("/domain")
def create_domain(body: dict, session: Session = DB):
    return ok(BaseDAO(session, Domain).insert(body))


@router.get("/concept/list")
def concepts(domainCode: str | None = None, session: Session = DB):
    return ok(ConceptService(session).list_by_domain(domainCode))


@router.get("/concept/detail/{code}")
def detail(code: str, session: Session = DB):
    return ok(ConceptService(session).detail(code))


@router.post("/concept")
def create_concept(body: dict, session: Session = DB):
    return ok(ConceptService(session).create(body))


@router.put("/concept")
def update_concept(body: dict, session: Session = DB):
    return ok(ConceptService(session).update_by_id(body))


@router.post("/concept/transition/{code}")
def transition(code: str, target: str, session: Session = DB):
    return ok(ConceptService(session).transition(code, target))


@router.post("/concept/attribute")
def add_attribute(body: dict, session: Session = DB):
    return ok(BaseDAO(session, Attribute).insert(body))


@router.delete("/concept/attribute/{id}")
def delete_attribute(id: int, session: Session = DB):
    BaseDAO(session, Attribute).delete_by_id(id)
    return ok()


@router.post("/concept/relation")
def add_relation(body: dict, session: Session = DB):
    return ok(RelationService(session).create(body))


@router.put("/concept/relation")
def update_relation(body: dict, session: Session = DB):
    return ok(RelationService(session).update(body))


@router.delete("/concept/relation/{id}")
def delete_relation(id: int, session: Session = DB):
    BaseDAO(session, Relation).delete_by_id(id)
    return ok()


@router.get("/concept/{code}/parents")
def parents(code: str, session: Session = DB):
    return ok(ConceptService(session).list_parents(code))


@router.post("/concept/{code}/parents")
def add_parent(code: str, body: dict, session: Session = DB):
    return ok(ConceptService(session).add_parent(code, body.get("parentCode"),
                int(str(body.get("isPrimary", 0)).lower() in {"true", "1"})))


@router.delete("/concept/{code}/parents/{parentCode}")
def remove_parent(code: str, parentCode: str, session: Session = DB):
    ConceptService(session).remove_parent(code, parentCode)
    return ok()


@router.put("/concept/{code}/parents/{parentCode}/primary")
def set_primary(code: str, parentCode: str, session: Session = DB):
    return ok(ConceptService(session).set_primary_parent(code, parentCode))


@router.delete("/concept/{code}")
def delete_concept(code: str, session: Session = DB):
    ConceptService(session).delete_draft(code)
    return ok()


@router.get("/term/list")
def terms(conceptCode: str | None = None, session: Session = DB):
    return ok(BaseDAO(session, Term).select_list(*([Term.concept_code == conceptCode] if conceptCode and conceptCode.strip() else [])))


@router.post("/term")
def create_term(body: dict, session: Session = DB):
    return ok(BaseDAO(session, Term).insert(body))


@router.delete("/term/{id}")
def delete_term(id: int, session: Session = DB):
    BaseDAO(session, Term).delete_by_id(id)
    return ok()


@router.get("/metric/list")
def metrics(session: Session = DB):
    return ok(MetricService(session).select_list())


@router.post("/metric")
def create_metric(body: dict, session: Session = DB):
    return ok(MetricService(session).insert(body))


@router.put("/metric")
def update_metric(body: dict, session: Session = DB):
    return ok(MetricService(session).update_by_id(body))


@router.post("/metric/evaluate/{metricCode}")
def evaluate(metricCode: str, session: Session = DB):
    return ok(MetricService(session).evaluate(metricCode))


@router.post("/metric/evaluate-all")
def evaluate_all(session: Session = DB):
    return ok(MetricService(session).evaluate_all())


@router.get("/ontology/disjoint")
def disjoints(session: Session = DB):
    return ok(DisjointService(session).select_list(order=(Disjoint.concept_a_code, Disjoint.concept_b_code)))


@router.post("/ontology/disjoint")
def create_disjoint(body: dict, session: Session = DB):
    return ok(DisjointService(session).create(body.get("conceptACode"), body.get("conceptBCode"), body.get("definition")))


@router.delete("/ontology/disjoint/{id}")
def delete_disjoint(id: int, session: Session = DB):
    DisjointService(session).delete_by_id(id)
    return ok()


@router.post("/ontology/check")
def check_ontology(session: Session = DB):
    defects = OntologyCheckService(session).check()
    return ok({"defects": defects, "blockerCount": sum(d["severity"] == "BLOCKER" for d in defects),
               "warnCount": sum(d["severity"] == "WARN" for d in defects)})


@router.get("/ontology/relation/closure")
def closure(relation: str, concept: str, session: Session = DB):
    from bemodel.modeling.services import ReleaseService
    return ok(ReleaseService(session).closure_of(relation, concept))


@router.get("/ontology/misses")
def misses(session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).board())


@router.post("/ontology/misses/{id}/dismiss")
def dismiss(id: int, body: dict | None = None, session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).dismiss(id, (body or {}).get("reason")))


@router.post("/ontology/misses/{id}/undismiss")
def undismiss(id: int, session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).undismiss(id))


@router.post("/ontology/misses/{id}/adopt")
def adopt(id: int, body: dict, session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).adopt(id, body.get("code"), body.get("name"), body.get("domainCode"), body.get("definition")))


@router.post("/ontology/misses/{id}/adopt-as-term")
def adopt_term(id: int, body: dict, session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).adopt_as_term(id, body.get("conceptCode")))


@router.post("/ontology/misses/{id}/revoke")
def revoke(id: int, session: Session = DB):
    from .miss_service import MissService
    return ok(MissService(session).revoke(id))


@router.post("/ontology/misses/{id}/classify")
def classify(id: int, session: Session = DB):
    from .miss_service import MissService
    return ok({"suggestion": MissService(session).classify(id)})
