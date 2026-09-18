from bemodel.ontology.owl_import import OwlImportService, snake
from bemodel.ontology.entities import Concept, Attribute, ConceptParent
from bemodel.core.base_dao import BaseDAO

TTL = b'''@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/> .
ex:Parent a owl:Class . ex:Child a owl:Class; rdfs:subClassOf ex:Parent .
ex:age a owl:DatatypeProperty; rdfs:domain ex:Child .
ex:partOf a owl:ObjectProperty, owl:TransitiveProperty; rdfs:domain ex:Child; rdfs:range ex:Parent .'''


def test_preview_execute_idempotent(session):
    service = OwlImportService(session)
    preview = service.preview(TTL, "example.ttl")
    assert preview["summary"] == dict(create=3, update=0, keyTaken=0, degraded=1)
    assert BaseDAO(session, Concept).select_count() == 0
    result = service.execute(TTL, "example.ttl")
    assert result == dict(created=3, updated=0, skipped=0, degraded=1, unprojected=0)
    assert BaseDAO(session, Attribute).select_one().data_type == "STRING"
    assert BaseDAO(session, ConceptParent).select_one().is_primary == 1
    service.execute(TTL, "example.ttl")
    assert BaseDAO(session, Concept).select_count() == 2
    assert BaseDAO(session, ConceptParent).select_count() == 1


def test_key_taken_does_not_overwrite(session):
    BaseDAO(session, Concept).insert(dict(code="CHILD", name="original", iri="http://different.org/Child"))
    result = OwlImportService(session).execute(TTL, "example.ttl")
    assert result["skipped"] == 1
    assert BaseDAO(session, Concept).select_one(Concept.code == "CHILD").name == "original"


def test_codes():
    assert snake("InpEncounter") == "INP_ENCOUNTER"
    assert snake("XMLReader") == "XML_READER"
    assert snake("12Age", False) == "c_12_age"
