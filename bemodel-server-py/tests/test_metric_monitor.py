from bemodel.ontology.services import MetricService
from bemodel.impact.services import ImpactService


def test_monitor_and_impact(mysql_session):
    service = MetricService(mysql_session)
    result = service.evaluate('CANCEL_NOT_REFUND')
    assert result['value'] == 5 and result['alarm'] is True
    results = service.evaluate_all()
    assert len(results) == 4 and sum(r.get('alarm') is True for r in results) == 1
    impact = ImpactService(mysql_session).analyze('LAB_APPLY', '撤销状态码变更')
    assert 'DS_LIS' in impact['affectedTables']
    assert impact['relatedConcepts'] and len(impact['advice']) > 20
