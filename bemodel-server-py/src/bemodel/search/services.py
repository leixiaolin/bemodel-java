from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.entities import Concept, Term, Metric
from bemodel.ontology.services import ConceptService
from bemodel.ontology.miss_service import MissService
from bemodel.llm.services import DeepSeekClient


def name_match(query, name):
    return bool(query and name and (query in name or name in query))


def def_match(query, definition):
    return bool(definition and len(query) >= 3 and any(query[i:i+n] in definition for n in (4, 3) for i in range(len(query)-n+1)))


class SearchService:
    def __init__(self, session):
        self.session = session

    def search(self, query, record_miss=True):
        query, hits = (query or "").strip(), []
        for term in BaseDAO(self.session, Term).select_list():
            if name_match(query, term.term):
                concept = ConceptService(self.session).get_by_code(term.concept_code)
                hits.append({"type": "术语", "title": f"{term.term}（{term.source_product or 'null'}）", "conceptCode": term.concept_code,
                    "content": "标准概念：" + term.concept_code + ("，定义：" + (concept.definition if concept.definition is not None else "无") if concept else "")})
        for concept in BaseDAO(self.session, Concept).select_list():
            if name_match(query, concept.name) or def_match(query, concept.definition):
                hits.append({"type": "概念", "title": f"{concept.name}（{concept.code}）", "conceptCode": concept.code, "content": concept.definition or ""})
        for m in BaseDAO(self.session, Metric).select_list(order=(Metric.id,)):
            if name_match(query, m.name) or def_match(query, m.definition):
                hits.append({"type": "指标", "title": f"{m.name}（负责人：{m.owner if m.owner is not None else '-'}）", "conceptCode": m.concept_code or "",
                    "metricCode": m.metric_code or "", "name": m.name or "", "content": f"口径：{m.definition if m.definition is not None else 'null'} 公式：{m.formula if m.formula is not None else '-'}"})
        if not hits and record_miss:
            MissService(self.session).record_miss(query, "CONCEPT", "SEARCH")
        answer = None
        if hits:
            prompt = "用户问题：" + query + "\n\n平台检索到的口径定义：\n"
            prompt += "".join(f"- [{h['type']}] {h['title']}：{h['content']}\n" for h in hits)
            prompt += "\n请基于以上定义用中文简洁回答用户问题（不超过200字）。若定义不足以回答，请说明缺口。"
            answer = DeepSeekClient(self.session).chat("SEARCH_ANSWER", "你是医疗本体平台的口径解答助手，严格基于给定定义回答。", prompt)
        return dict(query=query, llmUsed=answer is not None, answer=answer or "", hits=hits)
