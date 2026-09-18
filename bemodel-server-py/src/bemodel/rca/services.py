from collections import deque
from datetime import datetime
import json
import logging
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.core.result import to_camel_dict
from bemodel.core.java_compat import java_hash_set_order, java_local_datetime
from bemodel.flow.services import FlowService, string
from bemodel.link.services import LinkService
from bemodel.link.entities import LinkNode
from bemodel.llm.services import DeepSeekClient
from bemodel.ontology.entities import Relation
from .entities import RcaCase, RcaReport, RcaStep


def dumps(value):
    return json.dumps(to_camel_dict(value), ensure_ascii=False, separators=(',', ':'))


def java_list(values):
    return '['+', '.join(map(string, values))+']'


class RcaEngine:
    def __init__(self, session):
        self.session = session
        self.cases = BaseDAO(session, RcaCase)
        self.steps = BaseDAO(session, RcaStep)
        self.reports = BaseDAO(session, RcaReport)
        self.link = LinkService(session)
        self.flow = FlowService(session)

    def list_cases(self):
        return self.cases.select_list(order=(RcaCase.id.desc(),))

    def case_detail(self, case_id):
        case = self.cases.select_by_id(case_id)
        if case is None:
            raise BizException('案例不存在: '+str(case_id))
        return {'case': case, 'steps': self.steps.select_list(RcaStep.case_id == case_id, order=(RcaStep.step_no,)), 'report': self.reports.select_one(RcaReport.case_id == case_id)}

    def save_step(self, case, number, name, kind, sql, count, result, start):
        try:
            self.steps.insert(RcaStep(case_id=case.id, step_no=number, step_name=name, step_type=kind, sql_text=sql,
                hit_count=count, result_json=dumps(result), status='SUCCESS', started_at=start, finished_at=datetime.now()))
        except Exception as exc:
            raise BizException('步骤落库失败: '+str(exc)) from exc

    def start(self, ticket_ref):
        ticket = self.link.get_by_ref_no(ticket_ref)
        if ticket is None or ticket.node_type != 'TICKET':
            raise BizException('客服工单不存在: '+ticket_ref)
        try:
            payload = json.loads(ticket.payload)
        except (ValueError, TypeError):
            payload = {}
        inhos_no, patient = payload.get('inhos_no', ''), payload.get('patient', '')
        case = self.cases.insert(RcaCase(case_no='RCA-'+datetime.now().strftime('%Y%m%d%H%M%S'), ticket_ref=ticket_ref, concept_code=ticket.concept_code, status='RUNNING'))
        try:
            path = self.traverse(case)
            p1 = self.patient_charged(case, inhos_no, patient)
            p2 = self.lis_confirm(case, p1)
            p3 = self.mapping_gap(case)
            p4 = self.impact(case)
            links = self.link_step(case, path)
            self.report(case, ticket, patient, p1, p2, p3, p4, links)
            for node in links:
                if node.node_type == 'CHANGE':
                    try:
                        self.link.add_rel(node.ref_no, ticket_ref, 'CAUSES', '根因分析 '+case.case_no+' 关联')
                    except Exception:
                        logging.getLogger(__name__).warning('回写追溯边失败', exc_info=True)
        except Exception as exc:
            self.session.rollback()
            case.status, case.conclusion, case.finished_at = 'FAILED', '分析中断: '+str(exc), datetime.now()
            self.cases.update_by_id(case)
        return case

    def traverse(self, case):
        start = datetime.now()
        relations = BaseDAO(self.session, Relation).select_list()
        visited, queue, edges = {case.concept_code: None}, deque([case.concept_code]), []
        for _ in range(4):
            for _ in range(len(queue)):
                current = queue.popleft()
                for rel in relations:
                    next_code = rel.to_concept if rel.from_concept == current else rel.from_concept if rel.to_concept == current else None
                    if next_code is not None and next_code not in visited:
                        visited[next_code] = None
                        queue.append(next_code)
                        edges.append(f'{rel.from_concept} —{rel.relation_name}→ {rel.to_concept}')
        self.save_step(case, 1, '摸清业务范围：从客诉涉及的概念沿本体关系图展开，确定要查哪些系统', 'TRAVERSE', None, len(edges), {'起点': case.concept_code, '探查路径': edges}, start)
        return java_hash_set_order(visited)

    def patient_charged(self, case, inhos_no, patient):
        start = datetime.now()
        sql = "SELECT f.fee_id, f.order_id, f.item_name, f.amount, f.charge_time, o.order_status FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1' AND f.inhos_no = ?"
        rows = self.flow.query('HIS', sql.replace('?', ':id'), id=inhos_no) if inhos_no and inhos_no.strip() else []
        self.save_step(case, 2, f'核查患者[{patient}]的账单：是否存在「医嘱已取消、费用仍正常」的记录', 'PROBE', sql+f'  [参数 inhos_no={inhos_no}]', len(rows), {'口径说明': '医嘱状态=已取消 但 费用状态=正常（标准概念口径，经映射落为物理值 2/1）', '命中记录': rows}, start)
        return rows

    def lis_confirm(self, case, p1):
        start = datetime.now()
        if not p1:
            self.save_step(case, 3, '跨库核实：到 LIS 确认检验申请的真实状态', 'PROBE', None, 0, {'说明': '患者账单无异常，跳过'}, start)
            return []
        ids = [string(r.get('order_id')) for r in p1]
        sql = 'SELECT apply_id, order_id, patient_no, item_name, apply_status, update_time FROM lab_apply WHERE order_id IN ('+','.join('?' for _ in ids)+')'
        params = {'p'+str(i): value for i, value in enumerate(ids)}
        actual_sql = sql.split(' IN (')[0]+' IN ('+','.join(':'+key for key in params)+')'
        rows = self.flow.query('LIS', actual_sql, **params)
        self.save_step(case, 3, '跨库核实：到 LIS 确认这些医嘱的检验申请确实已撤销（经映射 patient_no↔住院号）', 'PROBE', sql+'  [参数 order_id='+java_list(ids)+']', len(rows), {'口径说明': 'apply_status=C 即标准口径「已撤销」', '命中记录': rows}, start)
        return rows

    def mapping_gap(self, case):
        start = datetime.now()
        a = "SELECT src_status, src_status_name, target_action, updated_at FROM status_map WHERE src_system = 'LIS'"
        b = 'SELECT DISTINCT apply_status FROM lab_apply'
        c = 'SELECT status_code, status_name, app_version, effective_date FROM lab_dict_status ORDER BY effective_date'
        mapped = self.flow.query('HIS', a)
        actual = [row['apply_status'] for row in self.flow.query('LIS', b)]
        missing = [s for s in actual if s not in [string(m['src_status']) for m in mapped]]
        result = {'适配器已映射状态': mapped, 'LIS实际使用状态': actual, '未映射状态（裂缝）': missing, 'LIS状态字典版本演进': self.flow.query('LIS', c)}
        self.save_step(case, 4, '比对字典找裂缝：HIS 计费适配器认识的撤销码 vs LIS 升级后实际使用的状态码', 'PROBE', a+' ; '+b+' ; '+c, len(missing), result, start)
        return result

    def impact(self, case):
        start = datetime.now()
        sql = "SELECT COUNT(DISTINCT f.inhos_no) AS patient_cnt, COUNT(*) AS fee_cnt, IFNULL(SUM(f.amount),0) AS total_amount, MIN(f.charge_time) AS first_at, MAX(f.charge_time) AS last_at FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'"
        result = self.flow.query('HIS', sql)[0]
        self.save_step(case, 5, '计算影响面：全院还有多少患者存在同样的「取消未退费」，涉及多少费用', 'PROBE', sql, int(result['fee_cnt']), result, start)
        return result

    def link_step(self, case, path):
        start = datetime.now()
        nodes = BaseDAO(self.session, LinkNode).select_list(LinkNode.concept_code.in_(path), LinkNode.node_type.in_(['CHANGE', 'DEPLOY', 'TESTCASE', 'REQUIREMENT']), order=(LinkNode.occurred_at,))
        self.save_step(case, 6, '翻变更留痕：该业务概念路径上的需求/变更/发布/测试记录', 'LINK', 'link_node WHERE concept_code IN '+java_list(path), len(nodes), {'关联节点': [dict(type=n.node_type, refNo=n.ref_no, title=n.title, at=java_local_datetime(n.occurred_at)) for n in nodes]}, start)
        return nodes

    def report(self, case, ticket, patient, p1, p2, p3, p4, links):
        start = datetime.now()
        missing = p3['未映射状态（裂缝）']
        pc, fc, amount = p4['patient_cnt'], p4['fee_cnt'], p4['total_amount']
        conclusion = f"LIS v5.2升级（2026-08-15）将检验申请撤销状态码由X改为C，但HIS计费适配器status_map未同步配置新码「{','.join(missing)}」的退费映射，导致升级后已撤销的检验医嘱仍正常计费。全院共影响{pc}名患者、{fc}笔费用，合计¥{amount}。"
        evidence = [
            dict(probe='患者账单核查', finding=f'患者{patient}存在{len(p1)}笔「医嘱已取消、费用仍正常」记录', data=p1),
            dict(probe='跨库事实核实', finding='对应LIS申请状态均为C（已撤销），撤销事实成立', data=p2),
            dict(probe='字典裂缝定位', finding=f'status_map缺少状态码 {java_list(missing)} 的映射，该码由LIS v5.2于2026-08-15引入', data=p3),
            dict(probe='全院影响面', finding=f'全院{pc}名患者、{fc}笔费用未退，合计¥{amount}', data=p4),
        ]
        impact = dict(affectedPatients=pc, affectedFees=fc, totalAmount=amount, firstOccurrence=p4.get('first_at'), lastOccurrence=p4.get('last_at'), relatedLinks=[f'{n.node_type}:{n.ref_no} {n.title}' for n in links])
        suggestions = [
            '【研发】HIS计费适配器status_map补充 LIS:C → 退费 映射，并建立状态字典变更的强制影响评估工单（堵住「口头通知」漏洞）',
            f'【运维】对影响期内{fc}笔费用执行批量退费，同步核对其他医技系统（PACS等）状态映射表',
            '【测试】TC-FEE-0032用例扩展：覆盖LIS侧撤销状态码（含新增码）的退费回归场景，纳入版本升级准入',
            '【治理】将「取消未退费笔数」指标（CANCEL_NOT_REFUND）接入日常监控，口径异常自动告警',
        ]
        context = f'客诉工单：{ticket.title}\n分析结论：{conclusion}\n\n证据链：\n'
        context += ''.join(f"- {e['probe']}：{e['finding']}\n" for e in evidence)
        context += '\n关联链路记录：\n'+''.join(f'- [{n.node_type}] {java_local_datetime(n.occurred_at)} {n.title}\n' for n in links)
        answer = DeepSeekClient(self.session).chat('RCA_REPORT', '你是医疗信息化根因分析专家。基于给定证据输出根因分析报告，结构：一、问题概述；二、根因结论；三、证据链分析；四、影响范围；五、整改建议。语言专业简洁，500字以内。', context)
        self.reports.insert(RcaReport(case_id=case.id, root_cause=answer if answer is not None else conclusion, evidence_json=dumps(evidence), impact_json=dumps(impact), suggestions_json=dumps(suggestions), llm_used=int(answer is not None)))
        case.status, case.conclusion, case.finished_at = 'DONE', conclusion, datetime.now()
        self.cases.update_by_id(case)
        self.save_step(case, 7, '产出诊断结论与处置建议（'+('deepseek-v4-flash' if answer is not None else '模板降级')+'）', 'REPORT', None, 1, dict(llmUsed=answer is not None, conclusion=conclusion), start)
