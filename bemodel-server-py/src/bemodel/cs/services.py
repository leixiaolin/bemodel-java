from datetime import datetime
from decimal import Decimal
import json
import re
from urllib.parse import quote_plus
from sqlalchemy import text
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import transactional
from bemodel.core.exceptions import BizException
from bemodel.flow.services import FlowService, string
from bemodel.link.entities import LinkNode
from bemodel.llm.services import DeepSeekClient
from bemodel.ontology.entities import Concept, Metric
from bemodel.rca.entities import RcaCase, RcaReport
from bemodel.rca.services import RcaEngine
from bemodel.search.services import SearchService
from .entities import CsFeedback
from .semantic import SemanticQaService
from .prompts import CS_ROUTE_PROMPT, ANALYTICS_ROUTE_PROMPT


def parse_json(value):
    try:
        return json.loads(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def evidence(*pairs):
    return [dict(label=k, value=v) for k, v in pairs]


def links(*pairs):
    return [dict(label=k, route=v) for k, v in pairs]


class CsService:
    def __init__(self, session):
        self.session = session
        self.flow = FlowService(session)
        self.llm = DeepSeekClient(session)
        self.rca = RcaEngine(session)
        self.feedback = BaseDAO(session, CsFeedback)

    def ticket(self, ticket_id):
        ticket = BaseDAO(self.session, LinkNode).select_by_id(ticket_id)
        if ticket is None or ticket.node_type != 'TICKET':
            raise BizException('客服工单不存在: '+str(ticket_id))
        return ticket

    def diagnosis(self, ticket_id):
        ticket = self.ticket(ticket_id)
        case = BaseDAO(self.session, RcaCase).select_one(RcaCase.ticket_ref == ticket.ref_no, order=(RcaCase.id.desc(),))
        legacy = False
        if case is not None:
            detail = self.rca.case_detail(case.id)
            report = detail['report']
            legacy = bool(report and report.evidence_json and '"P1 ' in report.evidence_json) or any(string(s.step_name).startswith('探针P') for s in detail['steps'])
        fresh = case is None or case.status != 'DONE' or legacy
        if fresh:
            case = self.rca.start(ticket.ref_no)
        detail = self.rca.case_detail(case.id)
        report = detail['report']
        detail.update(ticket=ticket, fresh=fresh, suggestions=parse_json(report.suggestions_json if report else None), impact=parse_json(report.impact_json if report else None), customerReply=self.customer_reply(ticket, case, report))
        return detail

    def customer_reply(self, ticket, case, report):
        root = report.root_cause if report else case.conclusion
        if settings.deepseek_api_key.strip():
            user = f'你是医院客服主管。根据以下客诉工单与平台诊断结论，写一段给客户的中文回复（150字内，先致歉，再说清原因与整改措施，口语化，不要技术术语）。\n工单：{ticket.title}\n诊断结论：{root}'
            reply = self.llm.chat('CS_REPLY', '你是医院客服主管，回复要专业、诚恳、简短。', user)
            if reply is not None:
                return reply
        return f'您好，非常抱歉给您带来了困扰。您反馈的「{ticket.title}」我们已核实：是系统升级后状态字典未同步导致的计费异常，涉及的费用将原路退回。我们已同步完成规则修复并补充了核查机制，避免此类问题再次发生。感谢您的监督与理解。'

    def refund_action(self, ticket_id, operator):
        with transactional(self.session):
            ticket = self.ticket(ticket_id)
            if ticket.status == '已处置':
                raise BizException('工单已处置，无需重复操作')
            affected = self.flow.query('HIS', "SELECT f.fee_id, f.inhos_no, f.item_name, f.amount FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'")
            total, ids = Decimal(0), []
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for fee in affected:
                rid = 'RA'+datetime.now().strftime('%Y%m%d')+f'{len(ids)+1:04d}'
                # The Java platform transaction does not enlist its dynamic product
                # data sources; each refund insert independently commits as there.
                with self.flow.ds.jdbc('DS_CHARGE').begin() as conn:
                    conn.execute(text('INSERT INTO refund_apply(refund_id,inhos_no,fee_id,amount,reason,apply_time,status) VALUES(:id,:inhos,:fee,:amount,:reason,:time,:status)'), dict(id=rid, inhos=fee['inhos_no'], fee=fee['fee_id'], amount=fee['amount'], reason=f'客诉「撤销后仍收费」批量退费（工单 {ticket.ref_no}，经办 {operator}）', time=now, status='0'))
                ids.append(rid)
                total += fee['amount']
            payload = f'{{"ticketRef":"{ticket.ref_no}","refundIds":{len(ids)},"totalAmount":{total},"operator":"{operator}"}}'
            dao = BaseDAO(self.session, LinkNode)
            disposal = dao.insert(LinkNode(node_type='DISPOSAL', ref_no='DP-'+ticket.ref_no, title=f'批量退费处置：{len(ids)} 笔，合计 ¥{total}', concept_code=ticket.concept_code, status='已完成', occurred_at=datetime.now(), payload=payload))
            ticket.status = '已处置'
            dao.update_by_id(ticket)
            return dict(refundCount=len(ids), totalAmount=total, refundIds=ids, disposalRef=disposal.ref_no)

    def save_feedback(self, question, intent, router, correct, comment):
        if not question or not question.strip():
            raise BizException('question 不能为空')
        return self.feedback.insert(CsFeedback(question=question.strip(), intent=intent, router=router, correct=int(correct == 1), comment=comment))

    def feedback_page(self, page, size):
        return self.feedback.page(page=page, size=size, order=(CsFeedback.id.desc(),))

    def route_prompt(self, q):
        prompt = CS_ROUTE_PROMPT
        mistakes = self.feedback.select_list(CsFeedback.correct == 0, order=(CsFeedback.id.desc(),), limit=10)
        if mistakes:
            prompt += '以下是人工评议员标注的历史误分类（前车之鉴，类似问题不要再错）：\n'
            for row in mistakes:
                prompt += f'- 问「{row.question}」误归 {string(row.intent)}'
                if row.comment and row.comment.strip():
                    prompt += '；正确应为/备注：'+row.comment
                prompt += '\n'
        return prompt+'问题：'+q

    def route_by_keyword(self, q, analytics):
        groups = [
            ('FEE', ('取消', '撤销', '未退', '多收', '退费', '收费')),
            ('GLOSSARY', ('口径', '怎么算', '什么是', '什么叫', '定义')),
            ('DISPENSE_SPLIT', ('分开发药', '分次发药', '多次发药', '拆零', '分批')),
            ('DISPENSE_RETURN', ('退药', '退掉', '退货')),
            ('DISPENSE_PAY', ('发药', '拿药', '取药', '买药', '药费', '缴费')),
            ('MATERIAL', ('耗材', '物资', '申领', '库存')),
            ('STAFF', ('医生', '护士', '药师', '技师', '谁', '科室', '人员')),
        ]
        if analytics:
            if any(k in q for k in groups[1][1]):
                return 'GLOSSARY'
            words = [k for intent, keywords in groups if intent != 'GLOSSARY' for k in keywords]+['多少', '哪些', '几条', '统计', '记录', '名单', '合计', '总额', '排名']
            return 'SEMANTIC_QUERY' if any(k in q for k in words) else None
        return next((intent for intent, words in groups if any(k in q for k in words)), None)

    def ask(self, question, scene=None):
        q, analytics = (question or '').strip(), (scene or '').strip().upper() == 'ANALYTICS'
        if analytics and any(k in q for k in ('口径', '怎么算', '什么是', '什么叫', '定义')):
            card = self.glossary_answer(q, False, True)
            if card and card.get('card') == 'METRIC':
                card.setdefault('router', 'RULE')
                return card
        intent, router = None, 'NONE'
        if settings.deepseek_api_key.strip():
            response = self.llm.chat('CS_ROUTE', '你是医院信息平台的意图分类器，只输出标签本身，不要任何解释。', ANALYTICS_ROUTE_PROMPT+q if analytics else self.route_prompt(q))
            label = re.sub('[^A-Z_]', '', response.strip().upper()) if response else ''
            allowed = {'GLOSSARY', 'SEMANTIC_QUERY'} if analytics else {'FEE', 'DISPENSE_PAY', 'DISPENSE_SPLIT', 'DISPENSE_RETURN', 'MATERIAL', 'STAFF', 'GLOSSARY', 'SEMANTIC_QUERY'}
            if label in allowed:
                intent, router = label, 'LLM'
        if intent is None:
            intent = self.route_by_keyword(q, analytics)
            if intent:
                router = 'RULE'
        if intent == 'SEMANTIC_QUERY':
            result, recorded = SemanticQaService(self.session).answer(q, analytics)
            if result is not None:
                result.setdefault('router', router)
                return result
            result = self.menu(q, analytics)
            result['router'] = router
            if recorded:
                result.update(missRecorded=True, answer=result['answer']+'这个问题已记录为本体完善提案（本体页-扩展提案可见）。')
            return result
        handlers = dict(FEE=self.fee_answer, DISPENSE_PAY=self.dispense_pay_answer, DISPENSE_SPLIT=self.dispense_split_answer, DISPENSE_RETURN=self.dispense_return_answer, MATERIAL=self.material_answer, STAFF=self.staff_answer, GLOSSARY=self.glossary_answer)
        result = handlers[intent](q) if intent in handlers else None
        if result is not None:
            result.setdefault('router', router)
            return result
        return dict(self.menu(q, analytics), router=router if intent is not None else 'REFERRAL')

    def fee_answer(self, q):
        impact = self.flow.query('HIS', "SELECT COUNT(DISTINCT f.inhos_no) AS patient_cnt, COUNT(*) AS fee_cnt, IFNULL(SUM(f.amount),0) AS total_amount FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'")[0]
        tickets = BaseDAO(self.session, LinkNode).select_list(LinkNode.node_type == 'TICKET', LinkNode.status == '待处理')
        pc, fc, amount = impact['patient_cnt'], impact['fee_cnt'], impact['total_amount']
        result = dict(question=q, intent='取消未退费排查', answer=f'当前全院共有 {pc} 名患者、{fc} 笔「医嘱已取消但费用未退」，合计 ¥{amount}。根因是 LIS v5.2 升级后撤销码 X→C，HIS 计费适配器未同步。现有 {len(tickets)} 张待处理工单，点开即可看 AI 的完整排查过程并一键退费。', evidence=evidence(('影响患者', f'{pc} 人'), ('未退费用', f'{fc} 笔'), ('涉及金额', f'¥{amount}'), ('待处理工单', f'{len(tickets)} 张')))
        result['links'] = (links(('打开待处理工单', '/cs?ticketId='+str(tickets[0].id))) if tickets else [])+links(('去链路追溯看费用明细概念', '/link?concept=FEE_DETAIL'))
        return result

    def dispense_pay_answer(self, q):
        paid = {r['inhos_no'] for r in self.flow.query('CHARGE', "SELECT DISTINCT inhos_no FROM pay_record WHERE pay_type IN ('1','2','4')")}
        dispensed = self.flow.query('PHARMACY', "SELECT dispense_id, patient_no, item_name FROM dispense_record WHERE status = '1'")
        unpaid = [d for d in dispensed if string(d.get('patient_no')) not in paid]
        charged = self.flow.query('HIS', "SELECT DISTINCT o.order_id, o.inhos_no, o.item_name FROM medical_order o JOIN fee_detail f ON f.order_id = o.order_id WHERE o.order_type = '药品' AND o.order_status IN ('0','1')")
        delivered = {r['order_id'] for r in self.flow.query('PHARMACY', "SELECT DISTINCT order_id FROM dispense_record WHERE status IN ('0','1')")}
        backlog = [o for o in charged if string(o.get('inhos_no')) in paid and string(o.get('order_id')) not in delivered]
        suffix = '，两个方向都无异常' if not unpaid and not backlog else '，异常需逐笔核查'
        return dict(question=q, intent='缴费发药双向核对', answer=f'流程规则：缴费是发药的前置环节，先药后费属违规；反方向「已缴费未发药」是发药滞留，同样需要核查。跨三库实测：已发药 {len(dispensed)} 笔中先药后费 {len(unpaid)} 笔；已计费药品医嘱 {len(charged)} 条中已缴费未发药 {len(backlog)} 条{suffix}。', evidence=evidence(('先药后费（违规）', f'{len(unpaid)} 笔 / 已发药共 {len(dispensed)} 笔'), ('已缴费未发药（滞留）', f'{len(backlog)} 条 / 已计费药品医嘱共 {len(charged)} 条'), ('数据来源', 'DS_PHARMACY.dispense_record × DS_CHARGE.pay_record × DS_HIS.medical_order×fee_detail 内存核对')), links=links(('去流程演示页看住院闭环', '/flow'), ('去本体页看发药记录概念', '/ontology?concept=DISPENSE')))

    def dispense_split_answer(self, q):
        split = self.flow.query('PHARMACY', "SELECT order_id, COUNT(*) AS cnt FROM dispense_record WHERE status IN ('0','1') GROUP BY order_id HAVING COUNT(*) > 1")
        total = self.flow.query('PHARMACY', "SELECT COUNT(DISTINCT order_id) AS n FROM dispense_record WHERE status IN ('0','1')")[0]['n']
        dispensed = self.flow.query('PHARMACY', "SELECT COUNT(*) AS n FROM dispense_record WHERE status = '1'")[0]['n']
        suffix = '——目前全部是一单一发，未发生分次' if not split else ''
        return dict(question=q, intent='分次发药核对', answer=f'可以。本体上「医嘱—调剂发药→发药记录」是 1:N 关系，一张药品医嘱允许拆成多次调剂/发药（拆零、分批发药都是合法场景）。实时核对药房库：当前 {total} 条医嘱共产生 {dispensed} 笔发药，其中 {len(split)} 条医嘱存在多次发药{suffix}。', evidence=evidence(('有发药的医嘱', f'{total} 条'), ('发药总笔数', f'{dispensed} 笔'), ('多次发药医嘱', f'{len(split)} 条'), ('数据来源', 'DS_PHARMACY.dispense_record 按医嘱分组实时统计')), links=links(('去本体页看「医嘱—发药」关系', '/ontology?concept=DISPENSE'), ('去流程演示页看发药环节', '/flow')))

    def dispense_return_answer(self, q):
        returned = self.flow.query('PHARMACY', "SELECT dispense_id, order_id, item_name FROM dispense_record WHERE status = '2'")
        count = 0
        if returned:
            params = {'p'+str(i): r['order_id'] for i, r in enumerate(returned)}
            count = self.flow.query('HIS', "SELECT COUNT(*) AS n FROM fee_detail WHERE order_id IN ("+','.join(':'+k for k in params)+") AND fee_status = '2'", **params)[0]['n']
        suffix = '，退药退费全部联动一致' if len(returned) == count else '，存在退药未退费的裂缝，需核查'
        return dict(question=q, intent='退药核对', answer=f'可以退药（含部分退药），闭环上退药是发药的逆环节：药房把发药记录置为已退药，收费侧同步退费，两步必须成对。实时核对：当前已退药 {len(returned)} 笔，对应费用已退费 {count} 笔{suffix}。', evidence=evidence(('已退药笔数', f'{len(returned)} 笔'), ('费用已退费', f'{count} 笔'), ('数据来源', 'DS_PHARMACY.dispense_record × DS_HIS.fee_detail 按医嘱号核对')), links=links(('去本体页看发药记录概念', '/ontology?concept=DISPENSE'), ('去流程演示页看闭环', '/flow')))

    def material_answer(self, q):
        stocks = self.flow.query('MATERIAL', 'SELECT material_name, quantity, unit FROM material_stock ORDER BY quantity')
        pending = self.flow.query('MATERIAL', "SELECT COUNT(*) AS n FROM material_apply WHERE status = '待发'")[0]['n']
        answer = '耗材库存当前（库存=Σ入库-Σ出库，账实相符）：'+''.join(f"{s['material_name']} {s['quantity']}{s['unit']}；" for s in stocks)+f'另有 {pending} 张科室申领单待发放。'
        return dict(question=q, intent='耗材库存查询', answer=answer, evidence=evidence(*[(string(s['material_name']), f"{s['quantity']} {s['unit']}") for s in stocks]), links=links(('去实例浏览看耗材库存/申领/发放', '/ontology')))

    def staff_answer(self, q):
        hit = next((s for s in self.flow.query('HIS', 'SELECT staff_name, role, title, dept_code FROM staff') if string(s['staff_name']) in q), None)
        if hit is None:
            return None
        detail = self.flow.staff_detail(hit['staff_name'])
        dept, footprint = detail['dept'], detail['footprint']
        answer = f"{hit['staff_name']}：{hit['role']} · {hit['title']}，隶属{dept['dept_name']}（{dept['category']}）。业务足迹：开立医嘱 {footprint['开立医嘱']} 条、执行确认 {footprint['执行确认']} 次、处方审核 {footprint['处方审核']} 次、调剂发药 {footprint['调剂发药']} 次。"
        return dict(question=q, intent='人员归属查询', answer=answer, evidence=evidence(('科室', f"{dept['dept_name']}（{dept['category']}）"), ('职称', string(hit['title'])), ('数据来源', '人员主数据 DS_HIS.staff（流程页人名可点击下钻）')), links=links(('去流程演示页看人名下钻', '/flow')))

    def glossary_answer(self, q, record_miss=True, allow_card=False):
        stripped = re.sub('(怎么算|什么是|什么叫|的口径|口径|定义)', '', q).strip()
        search = SearchService(self.session).search(stripped, record_miss)
        hits = search.get('hits')
        if not hits:
            return None
        top, metric_card = hits[0], False
        for hit in hits:
            name = string(hit.get('name'))
            if hit.get('type') == '指标' and name and stripped and (stripped in name or name in stripped):
                if not metric_card or len(name) > len(string(top.get('name'))):
                    top, metric_card = hit, True
        if metric_card and not allow_card:
            top, metric_card = hits[0], False
        answer_llm = string(search.get('answer')) if search.get('llmUsed') is True else ''
        result = dict(question=q, intent='口径查询', answer=f"「{top['title']}」{top['content']}"+('\n\n'+answer_llm if answer_llm else ''), evidence=evidence(('命中'+top['type'], string(top['title']))))
        result['links'] = links(('去统一口径页查看全部术语', '/glossary'))
        if metric_card:
            metric = BaseDAO(self.session, Metric).select_one(Metric.metric_code == string(top.get('metricCode')))
            if metric:
                has_probe = bool(metric.probe_sql and metric.probe_sql.strip() and metric.ds_code and metric.ds_code.strip())
                card = dict(metricCode=metric.metric_code, name=metric.name, definition=metric.definition, formula=metric.formula, probeSql=metric.probe_sql, dsCode=metric.ds_code, hasProbe=has_probe, owner=metric.owner, warnThreshold=metric.warn_threshold, lastVal=metric.last_val)
                if metric.last_eval_at:
                    card['lastEvalAt'] = metric.last_eval_at.strftime('%Y-%m-%d %H:%M')
                result.update(card='METRIC', metric=card, answerLlm=answer_llm, links=links(('去统一口径页看该指标（可执行检测）' if has_probe else '去统一口径页查看该指标', '/glossary?metric='+quote_plus(metric.metric_code))))
        return result

    def menu(self, q, analytics):
        if analytics:
            count = BaseDAO(self.session, Concept).select_count(Concept.status == 'PUBLISHED')
            return dict(question=q, intent='场景引导', answer=f'本页面向数据问题：把提问解析为「概念→关系→物理表」的查询计划，SQL 经白名单校验后在业务库实时执行。这个问题暂时没有命中语义层能力——可以换个数据问法，或转 AI 客服处理业务咨询。当前发布版本体覆盖 {count} 个概念；语义层答不了的问题会自动回流概念缺口页，按提问热度生长。', evidence=evidence(('已发布概念', f'{count} 个（本体管理-发布版）'), ('典型问法', '「最近10条缴费记录」「出院人数怎么算」')), links=links(('业务咨询/投诉处置？去 AI 客服', '/cs?q='+quote_plus(q))))
        return dict(question=q, intent='能力引导', answer='我目前能查证这几类问题，也可以直接问我业务数据（如「内科有多少住院患者」）：', evidence=evidence(
            ('开放查询', '「头孢克肟还有多少库存？」「昨天的缴费总额是多少？」→ 本体语义层直接查业务库'),
            ('费用投诉', '「检验取消了怎么还收费？」→ 全院取消未退费排查 + 一键退费工单'),
            ('缴费发药', '「没缴费可以发药吗？」→ 发药×缴费跨库实时核对'),
            ('发药方式', '「一个医嘱可以分开发药吗？」→ 医嘱×发药 1:N 实时统计'),
            ('退药核对', '「发药后可以部分退药吗？」→ 退药×退费联动核对'),
            ('耗材库存', '「一次性输液器还有多少库存？」→ 库存=Σ入-Σ出实时账'),
            ('人员归属', '「王芳是谁？」→ 科室/职称/业务足迹'),
            ('指标口径', '「出院人数怎么算？」→ 标准定义与负责人')),
            links=links(('找数据？去智能问数继续提问', '/ask?q='+quote_plus(q))))
