import pytest
from bemodel.core.exceptions import BizException
from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.entities import ConceptParent, Attribute
from bemodel.ontology.services import ConceptService, OntologyCheckService


def test_lifecycle_and_reference_guard(session):
    service = ConceptService(session)
    row = service.create(dict(code="TEST", name="测试"))
    assert row.status == "DRAFT" and row.version == 1
    with pytest.raises(BizException, match="已存在"):
        service.create(dict(code="TEST", name="重复"))
    service.transition("TEST", "REVIEW")
    published = service.transition("TEST", "PUBLISHED")
    assert published.version == 2
    with pytest.raises(BizException, match="仅草稿"):
        service.delete_draft("TEST")
    service.transition("TEST", "DEPRECATED")
    service.transition("TEST", "DRAFT")
    BaseDAO(session, Attribute).insert(dict(conceptCode="TEST", attrCode="id"))
    with pytest.raises(BizException, match="属性1个"):
        service.delete_draft("TEST")


def test_multiple_parents_and_cycles(session):
    service = ConceptService(session)
    for code in ["A", "B", "C"]:
        service.create(dict(code=code, name=code))
    service.add_parent("A", "B", 1)
    service.add_parent("A", "C", 1)
    assert sum(p.is_primary for p in service.list_parents("A")) == 1
    with pytest.raises(BizException, match="成环"):
        service.add_parent("B", "A")
    BaseDAO(session, ConceptParent).insert(dict(childCode="B", parentCode="A"))
    defects = OntologyCheckService(session).check()
    assert any(d["type"] == "SUBCLASS_CYCLE" and d["severity"] == "BLOCKER" for d in defects)
