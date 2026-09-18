from bemodel.governance.services import GovService


def test_governance_fault_and_stock(mysql_session):
    service = GovService(mysql_session)
    scan = service.scan()
    assert scan['ruleCount'] >= 10 and scan['durationMs'] >= 0 and scan['issueCount'] >= 1
    issues = service.issues(1, 200)['list']
    gap = next(i for i in issues if i.rule_code == 'GOV-004')
    assert gap.hit_count > 0 and 'C' in gap.sample_json
    assert all(i.rule_code != 'GOV-007' for i in issues)
    overview = service.overview()
    assert overview['tableCount'] >= 40 and overview['coverage'] > 0 and overview['qualityScore'] is not None
    tables = service.tables()
    assert any(t['tableName'] == 'lab_apply' for t in tables)
    assert any(t['tableName'] == 'drug_stock' for t in tables)
