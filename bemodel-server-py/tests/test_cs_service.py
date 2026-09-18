from datetime import datetime
import pytest
from sqlalchemy import text
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.cs.services import CsService
from bemodel.link.entities import LinkNode
from bemodel.rca.entities import RcaCase


@pytest.fixture
def cs_ticket(mysql_session):
    dao = BaseDAO(mysql_session, LinkNode)
    cs = CsService(mysql_session)
    def cleanup():
        with cs.flow.ds.jdbc('DS_CHARGE').begin() as conn:
            conn.execute(text("DELETE FROM refund_apply WHERE reason LIKE '%TEST-PY-CS-001%'"))
        BaseDAO(mysql_session, RcaCase).delete(RcaCase.ticket_ref == 'TEST-PY-CS-001')
        dao.delete(LinkNode.ref_no.in_(['TEST-PY-CS-001', 'DP-TEST-PY-CS-001']))
    cleanup()
    row = dao.insert(LinkNode(node_type='TICKET', ref_no='TEST-PY-CS-001', title='测试工单：住院患者检验项目撤销后仍收费', concept_code='FEE_DETAIL', status='未处置', occurred_at=datetime.now(), payload='{"inhos_no":"ZY20260815001","patient":"张建国"}'))
    yield cs, row
    cleanup()


def test_diagnosis_reuse(cs_ticket):
    cs, row = cs_ticket
    result = cs.diagnosis(row.id)
    assert result['case'].status == 'DONE' and len(result['steps']) == 7 and result['report']
    assert len(result['customerReply']) > 20 and result['suggestions']
    again = cs.diagnosis(row.id)
    assert again['fresh'] is False and again['case'].id == result['case'].id


def test_refund_action_and_duplicate_guard(cs_ticket):
    cs, row = cs_ticket
    result = cs.refund_action(row.id, '测试经办')
    assert result['refundCount'] == 5 and result['totalAmount'] == 205
    assert len(result['refundIds']) == 5 and result['disposalRef'] == 'DP-TEST-PY-CS-001'
    assert cs.ticket(row.id).status == '已处置'
    with pytest.raises(BizException, match='已处置'):
        cs.refund_action(row.id, '测试经办')


def test_product_writes_survive_platform_rollback(cs_ticket, monkeypatch):
    cs, row = cs_ticket
    original = BaseDAO.insert
    def fail_disposal(self, value):
        if isinstance(value, LinkNode) and value.node_type == 'DISPOSAL':
            raise RuntimeError('injected platform failure')
        return original(self, value)
    monkeypatch.setattr(BaseDAO, 'insert', fail_disposal)
    with pytest.raises(RuntimeError, match='injected platform failure'):
        cs.refund_action(row.id, '测试经办')
    assert cs.ticket(row.id).status == '未处置'
    assert BaseDAO(cs.session, LinkNode).select_count(LinkNode.ref_no == 'DP-TEST-PY-CS-001') == 0
    with cs.flow.ds.jdbc('DS_CHARGE').connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM refund_apply WHERE reason LIKE '%TEST-PY-CS-001%'")).scalar_one()
    assert count == 5


@pytest.mark.parametrize('question,intent', [
    ('没缴费可以发药吗？', '缴费发药双向核对'), ('一个医嘱可以分开发药吗？', '分次发药核对'),
    ('发药后可以部分退药吗', '退药核对'), ('今天天气怎么样', '能力引导'),
])
def test_customer_service_intents(mysql_session, question, intent):
    assert CsService(mysql_session).ask(question)['intent'] == intent


def test_analytics_referral_and_metric_card(mysql_session):
    cs = CsService(mysql_session)
    assert cs.ask('没缴费可以发药吗？', 'ANALYTICS')['intent'] == '场景引导'
    for scene, route in [('CS', '/ask'), ('ANALYTICS', '/cs')]:
        menu = cs.ask('今天天气怎么样', scene)
        assert menu['router'] == 'REFERRAL' and menu['links'][0]['route'].startswith(route)
    card = cs.ask('出院人数怎么算？', 'ANALYTICS')
    assert card['card'] == 'METRIC' and card['metric']['metricCode'] == 'DISCHARGE_COUNT'
    assert card['metric']['definition'] and card['metric']['formula'] and card['metric']['hasProbe']


def test_feedback_enriches_prompt(mysql_session):
    cs = CsService(mysql_session)
    row = cs.save_feedback('TEST-PY 路由问题', 'FEE', 'RULE', 0, '应该语义查询')
    try:
        prompt = cs.route_prompt('下一问')
        assert 'TEST-PY 路由问题' in prompt and '应该语义查询' in prompt
        assert cs.feedback_page(1, 20)['total'] >= 1
    finally:
        cs.feedback.delete_by_id(row.id)
