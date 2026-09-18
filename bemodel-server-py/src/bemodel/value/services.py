from datetime import datetime
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.clinical.services import QcService
from bemodel.flow.services import FlowService
from bemodel.llm.services import DeepSeekClient
from bemodel.modeling.entities import Action
from . import presentations


class ValueService:
    def __init__(self, session):
        self.session = session
        self.flow = FlowService(session)

    def compare(self):
        qc = QcService(self.session)
        record = next(r for r in qc.records() if r['inhos_no'] == 'ZY20260805006')
        check = qc.check(record['record_id'])
        findings = check['findings']
        hit = next((f for f in findings if f['ruleCode'] == 'RULE-QC-007'), findings[0] if findings else {})
        gate = presentations.gate(hit, check['trace'])
        impact = self.flow.query('HIS', "SELECT COUNT(*) AS fee_cnt, IFNULL(SUM(f.amount),0) AS total_amount FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status='2' AND f.fee_status='1'")[0]
        dictionary = self.flow.query('LIS', "SELECT MAX(end_date) AS x_end, MAX(CASE WHEN status_code='C' THEN effective_date END) AS c_start FROM lab_dict_status")[0]
        adapter_has_c = self.flow.query('HIS', "SELECT COUNT(*) AS n FROM status_map WHERE src_system='LIS' AND src_status='C'")[0]['n']
        silo = presentations.silo(impact, dictionary, adapter_has_c)
        actions = BaseDAO(self.session, Action).select_list()
        material = self.flow.query('MATERIAL', "SELECT (SELECT quantity FROM material_stock WHERE material_code='M001') AS stock, (SELECT IFNULL(SUM(quantity),0) FROM material_in WHERE material_code='M001') AS in_sum, (SELECT IFNULL(SUM(quantity),0) FROM material_out WHERE material_code='M001') AS out_sum")[0]
        adversarial = presentations.adversarial(actions, material)
        detail = self.flow.staff_detail('护士 王芳')
        traverse = presentations.traverse(detail['staff'], detail['dept'], detail['footprint'], detail['colleagues'])
        experiments = [gate, silo, adversarial, traverse]
        summary = None
        if settings.deepseek_api_key.strip():
            prompt = '以下是同一医疗业务问题在三组系统形态下的实证结果（A=AI+本体，B=AI+裸SQL，C=传统固定系统）：\n'
            for e in experiments:
                prompt += f"{e['title']} → A:{e['a']['outcome']}；B:{e['b']['outcome']}；C:{e['c']['outcome']}。判断：{e['verdict']}\n"
            prompt += '请用 120 字以内总结本体论的价值，要求：不比速度比能力边界，说清「结构保证 vs 模型自觉」的区别，不要套话。'
            summary = DeepSeekClient(self.session).chat('VALUE_SUMMARY', '你是医疗信息化领域的架构师，总结要克制、有判断、有边界感。', prompt)
        if summary is None:
            summary = '四组实验的共同点：本体的价值不在「更快」，而在「能不能、靠什么」。语义闸门拦截过敏处方、跨库裂缝直出根因、越权改库存结构上没有这个动作、人名沿关系链下钻——A 组的每一步都有语义依据且必然如此；B 组的正确性全押在模型发挥上，C 组的新问题都要排期开发。'
        return dict(experiments=experiments, llmSummary=summary, generatedAt=datetime.now().strftime('%a %b %d %H:%M:%S CST %Y'))
