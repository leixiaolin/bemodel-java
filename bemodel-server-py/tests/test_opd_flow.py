from bemodel.flow.services import FlowService
from bemodel.link.services import LinkService
from bemodel.link.entities import LinkNode


def test_opd_pagination_and_chain(mysql_session):
    flow = FlowService(mysql_session)
    first, second = flow.opd_patients(None, 1, 20), flow.opd_patients(None, 2, 20)
    assert first['total'] == 25 and len(first['list']) == 20 and len(second['list']) == 5
    loop = flow.opd_loop('KC2026900001')
    assert loop['register'] and loop['visit'] and loop['prescriptions'] and loop['payments']
    for p in loop['prescriptions']:
        assert p['statusName'] in ('已执行', '未执行', '已取消')
        if p['loopStatus'] == 'CLOSED' and p['itemType'] == '检验':
            assert p.get('labReport')
        if p['loopStatus'] == 'CLOSED' and p['itemType'] == '药品':
            assert p.get('dispense')
    assert any(e['system'] == '门诊' for e in loop['timeline'])


def test_auto_ticket_idempotency(mysql_session):
    link = LinkService(mysql_session)
    link.delete(LinkNode.ref_no.startswith('T-AUTO-'))
    try:
        first = link.auto_ticket()
        assert first['scannedPatients'] == 5 and first['createdCount'] == 3
        assert link.auto_ticket()['createdCount'] == 0
    finally:
        link.delete(LinkNode.ref_no.startswith('T-AUTO-'))
