import json
from datetime import datetime, timedelta

import pytest
from types import SimpleNamespace

from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.datasource.entities import Datasource, Mapping, PhysicalColumn, PhysicalTable
from bemodel.datasource.services import DatasourceService, SchemaScanService
from bemodel.datasource.governance import (
    OntologyAnalysisService,
    OntologyChangeSetService,
    SENSITIVE,
    schema_fingerprint,
)
from bemodel.datasource.governance_entities import OntologyAnalysisTask, OntologyChangeItem, OntologyChangeSet
from bemodel.ontology.entities import Attribute, Concept, Domain
from bemodel.auth.jwt_service import JwtService


def baseline(session):
    session.add_all([
        Datasource(ds_code="DS_NEW", ds_name="新库", db_type="MYSQL", host="127.0.0.1", port=3306,
                   db_name="demo", username="ro", password="ENC:test", status="ACTIVE", deleted=0),
        Domain(code="IMPORT", name="导入域", sort=99),
        PhysicalTable(ds_code="DS_NEW", table_name="exam", table_comment="体检记录", scanned_at=datetime.now()),
        PhysicalColumn(ds_code="DS_NEW", table_name="exam", column_name="exam_id", data_type="bigint",
                       column_comment="体检编号", is_pk=1, ordinal_position=1),
        PhysicalColumn(ds_code="DS_NEW", table_name="exam", column_name="person_name", data_type="varchar",
                       column_comment="姓名", is_pk=0, ordinal_position=2),
        PhysicalColumn(ds_code="DS_NEW", table_name="exam", column_name="exam_status", data_type="varchar",
                       column_comment="状态", is_pk=0, ordinal_position=3),
    ])
    session.commit()


def headers(role="ADMIN"):
    token = JwtService().issue(SimpleNamespace(username="governance", display_name=None, role=role))
    return {"Authorization": "Bearer " + token}


def test_fingerprint_is_stable_and_tracks_foreign_keys(session):
    table = PhysicalTable(table_name="a", table_comment="A")
    first = PhysicalColumn(table_name="a", column_name="id", data_type="BIGINT", ordinal_position=1)
    second = PhysicalColumn(table_name="a", column_name="b_id", data_type="BIGINT", ordinal_position=2,
                            referenced_table="b", referenced_column="id")
    original = schema_fingerprint([table], [first, second])
    assert original == schema_fingerprint([table], [second, first])
    second.referenced_column = "code"
    assert original != schema_fingerprint([table], [second, first])


def test_sensitive_field_detection():
    assert SENSITIVE.search("person_name 姓名")
    assert SENSITIVE.search("id_card 身份证号")
    assert not SENSITIVE.search("exam_status 状态")


def test_sensitive_statistics_never_query_grouped_values(session, monkeypatch):
    baseline(session)
    calls = []
    def query(_self, _code, sql, params=None):
        calls.append(sql)
        return [{"totalCount": 3, "nonNullCount": 3, "distinctCount": 3}]
    monkeypatch.setattr(DatasourceService, "query", query)
    column = BaseDAO(session, PhysicalColumn).select_one(PhysicalColumn.column_name == "person_name")
    result, warnings = OntologyAnalysisService(session).collect_statistics("DS_NEW", {"exam": [column]})
    assert not warnings and result[("exam", "person_name")]["sensitive"] is True
    assert len(calls) == 1 and " GROUP BY " not in calls[0]


def test_enqueue_is_idempotent_and_force_creates_new_task(session):
    baseline(session)
    service = OntologyAnalysisService(session)
    first = service.enqueue("DS_NEW", "editor")
    assert first.status == "PENDING"
    assert service.enqueue("DS_NEW", "editor").id == first.id
    assert service.enqueue("DS_NEW", "editor", force=True).id != first.id


def test_scan_records_drift_and_creator(session, monkeypatch):
    baseline(session)
    def query(_self, _code, sql, params=None):
        if "information_schema.TABLES" in sql:
            return [{"TABLE_NAME": "exam_v2", "TABLE_COMMENT": "新版体检"}]
        return [{"TABLE_NAME": "exam_v2", "COLUMN_NAME": "exam_no", "DATA_TYPE": "varchar",
                 "COLUMN_COMMENT": "体检号", "COLUMN_KEY": "PRI", "ORDINAL_POSITION": 1,
                 "REFERENCED_TABLE_NAME": None, "REFERENCED_COLUMN_NAME": None}]
    monkeypatch.setattr(DatasourceService, "query", query)
    result = SchemaScanService(session).scan("DS_NEW", "editor")
    task = BaseDAO(session, OntologyAnalysisTask).select_by_id(result["analysisTaskId"])
    drift = json.loads(task.scan_diff_json)
    assert task.created_by == "editor"
    assert drift["addedTables"] == ["exam_v2"] and drift["removedTables"] == ["exam"]
    assert "exam.exam_id" in drift["removedColumns"] and "exam_v2.exam_no" in drift["addedColumns"]


def test_analysis_without_key_keeps_deterministic_result(session, monkeypatch):
    baseline(session)
    service = OntologyAnalysisService(session)
    monkeypatch.setattr(service, "collect_statistics", lambda *_: ({}, []))
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    task = service.enqueue("DS_NEW", "editor")
    service.run_task(task.id)
    latest = service.latest("DS_NEW")
    assert latest["status"] == "PARTIAL"
    assert latest["changeSet"]["suggestionCount"] >= 3
    detail = service.detail(latest["changeSetId"])
    assert any(item["itemType"] == "CONCEPT" for item in detail["items"])
    assert all("payloadJson" not in item for item in detail["items"])


def test_ai_only_retry_reuses_previous_deterministic_result(session, monkeypatch):
    baseline(session)
    first_service = OntologyAnalysisService(session)
    monkeypatch.setattr(first_service, "collect_statistics", lambda *_: ({}, []))
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    first = first_service.enqueue("DS_NEW", "editor")
    first_service.run_task(first.id)
    retry = first_service.enqueue("DS_NEW", "editor", force=True, ai_only=True)
    retry_service = OntologyAnalysisService(session)
    monkeypatch.setattr(retry_service, "deterministic_analysis",
                        lambda *_: (_ for _ in ()).throw(AssertionError("不应重跑确定性分析")))
    monkeypatch.setattr(retry_service, "ai_analysis", lambda *_: ([], None))
    retry_service.run_task(retry.id)
    result = retry_service.latest("DS_NEW")
    assert result["id"] == retry.id and result["status"] == "SUCCEEDED"
    assert result["changeSet"]["suggestionCount"] > 0


def test_ai_parser_rejects_unknown_columns_and_sql(session):
    service = OntologyAnalysisService(session)
    raw = json.dumps([
        {"itemType": "CONCEPT", "operation": "CREATE", "targetKey": "GOOD", "sourceTable": "exam",
         "sourceColumn": "exam_id", "payload": {"code": "GOOD", "name": "好", "domainCode": "IMPORT"}},
        {"itemType": "RULE", "operation": "CREATE", "targetKey": "BAD_SQL", "sourceTable": "exam",
         "sourceColumn": "exam_id", "payload": {"ruleCode": "BAD_SQL", "sql": "DELETE FROM x"}},
        {"itemType": "ATTRIBUTE", "operation": "CREATE", "targetKey": "FAKE", "sourceTable": "exam",
         "sourceColumn": "missing", "payload": {"attrCode": "fake"}},
    ], ensure_ascii=False)
    result = service.parse_ai(raw, {"exam"}, {("exam", "exam_id")})
    assert [row["targetKey"] for row in result] == ["GOOD"]


def test_ai_rule_requires_strong_evidence(session):
    service = OntologyAnalysisService(session)
    raw = json.dumps([{"itemType": "RULE", "operation": "CREATE", "targetKey": "RULE_EXAM",
        "sourceTable": "exam", "sourceColumn": "exam_status", "confidence": .9,
        "evidence": ["只有一个证据"], "payload": {"ruleCode": "RULE_EXAM", "name": "体检规则",
        "conceptCode": "EXAM"}}], ensure_ascii=False)
    result = service.parse_ai(raw, {"exam"}, {("exam", "exam_status")})
    assert result[0]["operation"] == "INSUFFICIENT_EVIDENCE"


def test_adopt_dependencies_and_publish_atomically(session):
    baseline(session)
    analysis = OntologyAnalysisService(session)
    fingerprint, version = analysis.current_baseline("DS_NEW")
    task = BaseDAO(session, OntologyAnalysisTask).insert(OntologyAnalysisTask(
        ds_code="DS_NEW", status="PARTIAL", progress=100, scan_fingerprint=fingerprint,
        ontology_version=version, model="test", attempt_count=1))
    change = BaseDAO(session, OntologyChangeSet).insert(OntologyChangeSet(
        task_id=task.id, ds_code="DS_NEW", name="测试变更", status="DRAFT",
        scan_fingerprint=fingerprint, ontology_version=version, suggestion_count=3, high_risk_count=0))
    concept = BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="CONCEPT", operation="CREATE", review_status="PENDING",
        target_key="EXAM", payload_json=json.dumps({"code": "EXAM", "name": "体检", "domainCode": "IMPORT"}),
        evidence_json="[]", dependency_json="[]", confidence=.9, risk_level="LOW"))
    attribute = BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="ATTRIBUTE", operation="CREATE", review_status="PENDING",
        target_key="EXAM.exam_id", payload_json=json.dumps({"conceptCode": "EXAM", "attrCode": "exam_id",
            "attrName": "体检编号", "dataType": "NUMBER", "isKey": 1}), evidence_json="[]",
        dependency_json=json.dumps(["CONCEPT:EXAM"]), confidence=.9, risk_level="LOW"))
    mapping = BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="MAPPING", operation="CREATE", review_status="PENDING",
        target_key="exam.exam_id", payload_json=json.dumps({"dsCode": "DS_NEW", "tableName": "exam",
            "columnName": "exam_id", "conceptCode": "EXAM", "attrCode": "exam_id"}), evidence_json="[]",
        dependency_json=json.dumps(["ATTRIBUTE:EXAM.exam_id"]), confidence=.9, risk_level="LOW"))
    service = OntologyChangeSetService(session)
    adopted = service.adopt(change.id, [mapping.id], "editor")
    assert adopted["acceptedIds"] == sorted([concept.id, attribute.id, mapping.id])
    published = service.publish(change.id, "editor")
    assert published["status"] == "PUBLISHED"
    assert BaseDAO(session, Concept).select_one(Concept.code == "EXAM").status == "DRAFT"
    assert BaseDAO(session, Attribute).select_one(Attribute.concept_code == "EXAM", Attribute.attr_code == "exam_id")
    saved = BaseDAO(session, Mapping).select_one(Mapping.ds_code == "DS_NEW", Mapping.column_name == "exam_id")
    assert saved.confirmed == 0 and saved.source == "AI_GOVERNANCE"
    assert service.publish(change.id, "editor")["status"] == "PUBLISHED"


def test_conflict_cannot_be_accepted_and_stale_lock_is_recovered(session, monkeypatch):
    baseline(session)
    service = OntologyChangeSetService(session)
    fingerprint, version = service.current_baseline("DS_NEW")
    task = BaseDAO(session, OntologyAnalysisTask).insert(OntologyAnalysisTask(
        ds_code="DS_NEW", status="RUNNING", progress=10, scan_fingerprint=fingerprint,
        ontology_version=version, attempt_count=1, locked_at=datetime.now() - timedelta(hours=1)))
    change = BaseDAO(session, OntologyChangeSet).insert(OntologyChangeSet(
        task_id=task.id, ds_code="DS_NEW", name="冲突", status="DRAFT",
        scan_fingerprint=fingerprint, ontology_version=version, suggestion_count=1, high_risk_count=1))
    item = BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="CONCEPT", operation="CONFLICT", review_status="PENDING",
        target_key="X", payload_json='{"code":"X","name":"X","domainCode":"IMPORT"}',
        evidence_json="[]", dependency_json="[]", confidence=.5, risk_level="HIGH"))
    with pytest.raises(BizException):
        service.update_item(change.id, item.id, {"reviewStatus": "ACCEPTED"}, "editor")
    monkeypatch.setattr(settings, "ontology_analysis_lock_seconds", 30)
    recovered = service.claim_next("worker-test")
    assert recovered.id == task.id and recovered.status == "RUNNING" and recovered.attempt_count == 2


def test_disabling_datasource_cancels_active_tasks(session):
    baseline(session)
    service = OntologyAnalysisService(session)
    task = service.enqueue("DS_NEW", "editor")
    DatasourceService(session).update_status("DS_NEW", "DISABLED")
    cancelled = service.tasks.select_by_id(task.id)
    assert cancelled.status == "CANCELLED" and cancelled.finished_at is not None


def test_cancellation_during_ai_cannot_be_overwritten(session, monkeypatch):
    baseline(session)
    service = OntologyAnalysisService(session)
    monkeypatch.setattr(service, "collect_statistics", lambda *_: ({}, []))
    task = service.enqueue("DS_NEW", "editor")
    def cancel_during_ai(*_args):
        service.cancel_for_datasource("DS_NEW")
        return [], None
    monkeypatch.setattr(service, "ai_analysis", cancel_during_ai)
    service.run_task(task.id)
    current = service.tasks.select_by_id(task.id)
    assert current.status == "CANCELLED"
    assert service.sets.select_count(OntologyChangeSet.task_id == task.id) == 0


def test_governance_api_contract_and_permissions(client, session):
    baseline(session)
    task = OntologyAnalysisService(session).enqueue("DS_NEW", "editor")
    viewer = client.get("/api/datasource/DS_NEW/ontology-analysis/latest", headers=headers("VIEWER"))
    assert viewer.status_code == 200
    assert viewer.json()["data"]["id"] == task.id
    assert "workerId" not in viewer.json()["data"] and "lockedAt" not in viewer.json()["data"]
    assert client.post("/api/datasource/DS_NEW/ontology-analysis", json={"force": True},
                       headers=headers("VIEWER")).status_code == 403
    started = client.post("/api/datasource/DS_NEW/ontology-analysis", json={"force": True}, headers=headers())
    assert started.status_code == 200 and started.json()["code"] == 0


def test_publish_rolls_back_everything_when_mapping_conflicts(session):
    baseline(session)
    session.add(Mapping(ds_code="DS_NEW", table_name="exam", column_name="exam_id",
                        concept_code="OLD", attr_code="id", confirmed=1, source="MANUAL"))
    session.commit()
    service = OntologyChangeSetService(session)
    fingerprint, version = service.current_baseline("DS_NEW")
    task = BaseDAO(session, OntologyAnalysisTask).insert(OntologyAnalysisTask(
        ds_code="DS_NEW", status="PARTIAL", progress=100, scan_fingerprint=fingerprint,
        ontology_version=version, attempt_count=1))
    change = BaseDAO(session, OntologyChangeSet).insert(OntologyChangeSet(
        task_id=task.id, ds_code="DS_NEW", name="回滚测试", status="ADOPTED",
        scan_fingerprint=fingerprint, ontology_version=version, suggestion_count=2, high_risk_count=0))
    BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="CONCEPT", operation="CREATE", review_status="ACCEPTED",
        target_key="ROLLBACK_EXAM", payload_json=json.dumps({"code": "ROLLBACK_EXAM", "name": "回滚体检", "domainCode": "IMPORT"}),
        evidence_json="[]", dependency_json="[]", confidence=.9, risk_level="LOW"))
    BaseDAO(session, OntologyChangeItem).insert(OntologyChangeItem(
        change_set_id=change.id, item_type="MAPPING", operation="CREATE", review_status="ACCEPTED",
        target_key="exam.exam_id", payload_json=json.dumps({"dsCode": "DS_NEW", "tableName": "exam",
            "columnName": "exam_id", "conceptCode": "ROLLBACK_EXAM", "attrCode": "id"}),
        evidence_json="[]", dependency_json="[]", confidence=.9, risk_level="LOW"))
    with pytest.raises(BizException, match="已有映射"):
        service.publish(change.id, "editor")
    assert BaseDAO(session, Concept).select_one(Concept.code == "ROLLBACK_EXAM") is None
    assert service.sets.select_by_id(change.id).status == "ADOPTED"
