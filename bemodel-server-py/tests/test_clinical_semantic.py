import json
import pytest
from bemodel.clinical.services import QcService, AlertService
from bemodel.core.base_dao import BaseDAO
from bemodel.modeling.entities import Rule, Axiom
from bemodel.modeling.services import RuleService
from bemodel.link.entities import LinkNode


@pytest.mark.parametrize('patient,rule', [
    ('ZY20260812002', 'RULE-QC-001'), ('ZY20260802011', 'RULE-QC-002'),
    ('ZY20260822007', 'RULE-QC-003'), ('ZY20260828010', 'RULE-QC-004'),
    ('ZY202682000013', 'RULE-QC-005'), ('ZY20260822007', 'RULE-QC-006'),
    ('ZY20260805006', 'RULE-QC-007'), ('ZY20260728012', 'RULE-QC-008'),
])
def test_configured_clinical_rules(mysql_session, patient, rule):
    qc = QcService(mysql_session)
    record = next(r for r in qc.records() if r['inhos_no'] == patient)
    result = qc.check(record['record_id'])
    assert result['pass'] is False
    assert rule in [f['ruleCode'] for f in result['findings']]
    assert 'ontologyVersion' in result['trace']


def test_qc_totals_and_runtime_rule(mysql_session):
    qc = QcService(mysql_session)
    assert BaseDAO(mysql_session, Axiom).select_count() == 9
    total = qc.check_all()
    assert total['total'] == 13 and total['fail'] == 7
    record = next(r for r in qc.records() if r['inhos_no'] == 'ZY20260815001')['record_id']
    assert qc.check(record)['pass'] is True
    rules = RuleService(mysql_session)
    row = rules.create(dict(ruleCode='RULE-TEST-RUNTIME', name='运行时规则验证', conceptCode='DIAGNOSIS', ruleType='校验', severity='低', expression='验证用，无临床意义', engine='QC', exprJson=json.dumps(dict(type='DIAG_REQUIRES_ITEM', cases=[dict(diagKeywords=['冠心病'], kind='DRUG', codes=['D011'], requireName='头孢呋辛')]), ensure_ascii=False)))
    try:
        rules.transition(row.rule_code, 'REVIEW')
        rules.transition(row.rule_code, 'PUBLISHED')
        assert 'RULE-TEST-RUNTIME' in [f['ruleCode'] for f in qc.check(record)['findings']]
    finally:
        rules.delete_by_id(row.id)
    assert qc.check(record)['pass'] is True


def test_alert_idempotency(mysql_session):
    nodes = BaseDAO(mysql_session, LinkNode)
    nodes.delete(LinkNode.ref_no.startswith('ALERT-'))
    service = AlertService(mysql_session)
    first = service.detect()
    assert first['abnormalReports'] == 2 and first['handled'] == 1 and first['createdCount'] == 1
    assert service.detect()['createdCount'] == 0
