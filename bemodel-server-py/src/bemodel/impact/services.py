from collections import defaultdict, deque
from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.services import ConceptService
from bemodel.ontology.entities import Relation, Metric
from bemodel.datasource.entities import Mapping
from bemodel.link.entities import LinkNode
from bemodel.llm.services import DeepSeekClient


class ImpactService:
    def __init__(self, session):
        self.session = session

    def analyze(self, code, description, depth=None):
        concept = ConceptService(self.session).require(code)
        mappings = BaseDAO(self.session, Mapping).select_list(Mapping.concept_code == code)
        tables = defaultdict(list)
        for m in mappings:
            tables[m.ds_code].append(m.table_name + "." + m.column_name + ("（含值字典 " + m.value_map + "）" if m.value_map is not None else ""))
        metrics = BaseDAO(self.session, Metric).select_list(Metric.concept_code == code)
        testcases = BaseDAO(self.session, LinkNode).select_list(LinkNode.concept_code == code, LinkNode.node_type == "TESTCASE")
        max_depth = 3 if depth is None or depth < 1 else min(depth, 6)
        relations = BaseDAO(self.session, Relation).select_list()
        hops, related, seen, queue, capped = {code: 0}, [], set(), deque([code]), False
        while queue:
            current = queue.popleft()
            hop = hops[current]
            for r in relations:
                is_out, is_in = r.from_concept == current, r.to_concept == current
                if not is_out and not is_in:
                    continue
                other = r.to_concept if is_out else r.from_concept
                if other == code:
                    continue
                if hop >= max_depth:
                    capped = True
                    continue
                if r.id not in seen:
                    seen.add(r.id)
                    related.append(f"{r.from_concept} —{r.relation_name}→ {r.to_concept}（{'下游受影响' if is_out else '上游来源'} · {hop+1}跳）")
                if other not in hops:
                    hops[other] = hop + 1
                    queue.append(other)
        layers = defaultdict(list)
        for c, hop in hops.items():
            if hop:
                layers[hop].append(c)
        history = BaseDAO(self.session, LinkNode).select_list(LinkNode.concept_code == code, LinkNode.node_type.in_(["CHANGE", "TICKET"]), order=(LinkNode.occurred_at.desc(),))
        java_list = lambda rows: "[" + ", ".join(rows) + "]"
        prompt = f"变更描述：{description if description is not None else 'null'}\n涉及概念：{concept.name}（{code}）\n受影响产品库物理映射：\n"
        prompt += "".join(f"- {ds}：{'、'.join(cols)}\n" for ds, cols in tables.items())
        prompt += "关联指标：" + java_list([m.name for m in metrics]) + "\n已有测试用例：" + java_list([t.title for t in testcases])
        prompt += f"\n上下游概念（多跳影响面，最多{max_depth}跳）：" + java_list(related) + "\n同类历史变更与工单：" + java_list([h.ref_no + " " + h.title for h in history]) + "\n"
        answer = DeepSeekClient(self.session).chat("IMPACT_ADVICE", "你是医疗信息化变更评审专家。基于影响面信息输出变更评估意见：一、风险点（按严重度排序）；二、必须同步修改的下游清单；三、测试补充建议。300字以内，直接给结论。", prompt)
        advice = answer if answer is not None else (f"本次变更涉及概念「{concept.name}」，影响 {len(tables)} 个产品库 {len(mappings)} 处物理映射（{','.join(tables)}）、{len(metrics)} 个指标、{len(testcases)} 个已有测试用例。" + ("请核对测试用例是否覆盖本次变更场景。" if testcases else "当前无测试用例覆盖，必须补充。") + "请逐项确认下游同步改造后再发布。")
        return dict(conceptCode=code, conceptName=concept.name, changeDesc=description, affectedTables=dict(tables),
            affectedMetrics=[dict(code=m.metric_code, name=m.name) for m in metrics], coveredTestcases=[dict(refNo=t.ref_no, title=t.title, status=t.status) for t in testcases],
            relatedConcepts=related, impactLayers=dict(sorted(layers.items())), impactDepth=max_depth, impactCapped=capped,
            history=[dict(refNo=h.ref_no, title=h.title, type=h.node_type) for h in history], advice=advice, llmUsed=answer is not None)
