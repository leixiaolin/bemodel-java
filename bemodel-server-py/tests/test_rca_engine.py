import json
from bemodel.rca.services import RcaEngine


def test_seven_step_planted_fault(mysql_session):
    engine = RcaEngine(mysql_session)
    case = engine.start('T-20260901-001')
    assert case.status == 'DONE' and 'C' in case.conclusion and 'status_map' in case.conclusion
    result = engine.case_detail(case.id)
    steps = result['steps']
    assert len(steps) == 7 and [s.hit_count for s in steps[1:4]] == [1, 1, 1]
    assert '"C"' in steps[2].result_json
    impact = json.loads(steps[4].result_json)
    assert impact['patient_cnt'] == 5 and impact['fee_cnt'] == 5 and impact['total_amount'] == 205
    assert result['report'] is not None
