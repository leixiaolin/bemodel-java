import json
import pytest
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.modeling.entities import Release
from bemodel.modeling.services import ReleaseService, RuleService, ActionService
from bemodel.ontology.entities import Relation


@pytest.mark.parametrize("service,field", [(RuleService, "ruleCode"), (ActionService, "actionCode")])
def test_state_machine(session, service, field):
    service = service(session)
    row = service.create({field: "TEST", "name": "test"})
    assert row.status == "DRAFT" and row.version == 1
    service.transition("TEST", "REVIEW")
    assert service.transition("TEST", "PUBLISHED").version == 2
    with pytest.raises(BizException):
        service.transition("TEST", "DRAFT")


def test_publish_blockers_and_force(session):
    dao = BaseDAO(session, Relation)
    row = dao.insert(dict(fromConcept="A", toConcept="B", relationName="test", isSymmetric=1, isAsymmetric=1))
    for force in (True, False):
        with pytest.raises(BizException, match="阻断"):
            ReleaseService(session).publish(force=force)
    dao.update_by_id(dict(id=row.id, isSymmetric=0, isTransitive=1, isFunctional=1))
    with pytest.raises(BizException, match="警告"):
        ReleaseService(session).publish()
    release = ReleaseService(session).publish(force=True)
    assert release.version_tag == "v1.0"


def test_closure_shortest_paths_capped(session):
    dao = BaseDAO(session, Relation)
    for i in range(14):
        dao.insert(dict(fromConcept=f"N{i}", toConcept=f"N{i+1}", relationName="partOf", isTransitive=1))
    release = ReleaseService(session).publish(force=True)
    stats = json.loads(release.snapshot_json)["relationClosures"]["partOf"]
    assert stats["capped"] is True
    reachable = ReleaseService(session).closure_of("partOf", "N0")["reachable"]
    assert max(r["depth"] for r in reachable) == 12
    assert {r["concept"] for r in reachable} == {f"N{i}" for i in range(1, 13)}


def test_publish_rolls_back_closure_on_insert_failure(session, monkeypatch):
    dao = BaseDAO(session, Relation)
    dao.insert(dict(fromConcept="A", toConcept="B", relationName="partOf", isTransitive=1))
    service = ReleaseService(session)
    def fail(_):
        raise RuntimeError("injected database write failure")
    monkeypatch.setattr(service, "insert", fail)
    with pytest.raises(RuntimeError):
        service.publish(force=True)
    assert service.closure_of("partOf", "A")["count"] == 0
    assert BaseDAO(session, Release).select_count() == 0
