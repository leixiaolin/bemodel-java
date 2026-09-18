from bemodel.flow.services import FlowService


def test_patient_pagination_and_complete_chain(mysql_session):
    flow = FlowService(mysql_session)
    pages = [flow.patients(None, p, 20) for p in (1, 2, 3)]
    assert [len(p['list']) for p in pages] == [20, 20, 1]
    assert all(p['total'] == 41 for p in pages)
    assert all(p['orderCount'] > 0 for p in pages[0]['list'])
    loop = flow.loop('ZY20260815001')
    assert loop['orders'] and loop['payments'] and loop['settlement']
    assert sum(o['loopStatus'] == 'BROKEN' for o in loop['orders']) == 1
    assert {'护士站', 'PACS', '药房', 'LIS', '收费'} <= {e['system'] for e in loop['timeline']}
    for order in loop['orders']:
        if order['orderType'] == '药品':
            assert order.get('prescReview')
        if order['loopStatus'] == 'BROKEN':
            assert order['labApply']['statusName'] == '已撤销'


def test_overdose_rejected(mysql_session):
    flow = FlowService(mysql_session)
    loop = flow.loop('ZY20260728012')
    rejected = [o['prescReview'] for o in loop['orders'] if o.get('prescReview', {}).get('review_result') == '驳回']
    assert rejected and any('2.4g' in r['reject_reason'] for r in rejected)
    assert any(e['event'] == '处方审核驳回' for e in loop['timeline'])
