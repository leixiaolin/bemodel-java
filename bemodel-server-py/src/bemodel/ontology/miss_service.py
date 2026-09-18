import json
import logging
from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.llm.services import DeepSeekClient
from .entities import OntologyMiss, Domain, Term
from .services import ConceptService


class MissService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, OntologyMiss)
        self.concepts = ConceptService(session)

    def record_miss(self, term, kind, source):
        if term is None or not 2 <= len(term.strip()) <= 128:
            return
        try:
            with self.session.begin_nested():
                statement = insert(OntologyMiss).values(term=term.strip(), kind=kind, source=source, count=1,
                    dismissed=0, revoked=0, first_seen=func.now(), last_seen=func.now())
                self.session.execute(statement.on_duplicate_key_update(count=OntologyMiss.count + 1, last_seen=func.now()))
            if not self.session.info.get("transaction_depth"):
                self.session.commit()
        except Exception:
            logging.getLogger(__name__).exception("记录本体 miss 失败（静默降级）")

    @staticmethod
    def is_pending(row):
        return row.dismissed != 1 and (row.adopted_concept_code is None or row.revoked == 1)

    def board(self):
        rows = self.select_list()
        return {"items": sorted(rows, key=lambda r: (not self.is_pending(r), -r.count, r.id)),
                "pendingCount": sum(self.is_pending(r) for r in rows)}

    def require(self, id):
        row = self.select_by_id(id)
        if row is None:
            raise BizException("miss 不存在: " + str(id))
        return row

    def dismiss(self, id, reason=None):
        row = self.require(id)
        row.dismissed = 1
        # updateById ignores null; retain the previous stored reason.
        if reason is not None:
            row.dismiss_reason = reason
        return self.update_by_id(row)

    def undismiss(self, id):
        row = self.require(id)
        row.dismissed = 0
        return self.update_by_id(row)

    def available(self, id):
        row = self.require(id)
        if row.adopted_concept_code is not None and row.revoked != 1:
            raise BizException("该 miss 已采纳，概念: " + row.adopted_concept_code)
        return row

    def adopt(self, id, code, name, domain_code, definition):
        row = self.available(id)
        if not code or not code.strip() or not name or not name.strip():
            raise BizException("概念编码与名称不能为空")
        if self.concepts.get_by_code(code):
            raise BizException("概念编码已存在: " + code)
        if not BaseDAO(self.session, Domain).select_count(Domain.code == domain_code):
            raise BizException("业务域不存在: " + str(domain_code))
        concept = self.concepts.create(dict(code=code, name=name, domainCode=domain_code, definition=definition))
        row.adopted_concept_code, row.adopted_as, row.revoked = code, "CONCEPT", 0
        self.update_by_id(row)
        return concept

    def adopt_as_term(self, id, code):
        row = self.available(id)
        if not code or not code.strip():
            raise BizException("概念编码不能为空")
        self.concepts.require(code)
        dao = BaseDAO(self.session, Term)
        if not dao.select_one(Term.term == row.term, Term.concept_code == code):
            own = dao.select_one(Term.term == row.term, Term.source_product == "ONTOLOGY_MISS")
            if own:
                own.concept_code = code
                dao.update_by_id(own)
            else:
                dao.insert(Term(term=row.term, concept_code=code, source_product="ONTOLOGY_MISS", term_type="ALIAS", code_system="平台标准"))
        row.adopted_concept_code, row.adopted_as, row.revoked = code, "TERM", 0
        return self.update_by_id(row)

    def revoke(self, id):
        row = self.require(id)
        if row.adopted_concept_code is None or row.revoked == 1:
            raise BizException("该 miss 未采纳或已撤销")
        if row.adopted_as == "TERM":
            BaseDAO(self.session, Term).delete(Term.term == row.term, Term.concept_code == row.adopted_concept_code, Term.source_product == "ONTOLOGY_MISS")
        else:
            concept = self.concepts.get_by_code(row.adopted_concept_code)
            while concept and concept.status != "DEPRECATED":
                target = {"DRAFT": "REVIEW", "REVIEW": "PUBLISHED", "PUBLISHED": "DEPRECATED"}.get(concept.status)
                if target is None:
                    raise BizException("概念当前状态不可撤销: " + concept.status)
                concept = self.concepts.transition(concept.code, target)
        row.revoked = 1
        return self.update_by_id(row)

    def classify(self, id):
        row = self.require(id)
        domains = BaseDAO(self.session, Domain).select_list(order=(Domain.sort,))
        concepts = self.concepts.list_by_domain()
        prompt = f'词表外说法："{row.term}"（类型 {row.kind}，来源 {row.source}，累计出现 {row.count} 次）\n\n可选业务域：\n'
        for d in domains:
            prompt += f'- {d.code}({d.name})' + (": " + d.description if d.description is not None else "") + "\n"
        prompt += "\n现有概念（按域分组）：\n"
        for d in domains:
            cs = [f"{c.code}({c.name})" for c in concepts if c.domain_code == d.code]
            if cs:
                prompt += d.code + ": " + ", ".join(cs) + "\n"
        prompt += '\n请为该说法建议一个标准概念，只返回JSON对象：{"code":"大写蛇形编码（风格参考 INP_VISIT、FEE_DETAIL）","name":"中文名称","domainCode":"从上面业务域列表中选择的编码","definition":"业务定义","reason":"一句中文人话解释为什么这样归类"}。只返回JSON。'
        response = DeepSeekClient(self.session).chat("MISS_CLASSIFY", "你是医疗本体治理助手，为平台使用中出现的词表外说法建议标准概念归类。只返回JSON，不要多余文字。", prompt)
        try:
            if response is None:
                raise ValueError()
            parsed = json.loads(response[response.index("{"):response.rindex("}")+1])
            suggestion = {k: str(parsed.get(k) or "") for k in ("code", "name", "domainCode", "definition", "reason")}
            for key in ("code", "name", "domainCode"):
                suggestion[key] = suggestion[key].strip()
            suggestion["codeTaken"] = bool(suggestion["code"] and self.concepts.get_by_code(suggestion["code"]))
            suggestion["domainValid"] = any(d.code == suggestion["domainCode"] for d in domains)
            if not suggestion["domainValid"]:
                suggestion["domainCode"] = ""
            suggestion["degraded"] = False
            return suggestion
        except (ValueError, TypeError, AttributeError):
            return dict(code="", name=row.term, domainCode="", definition="", reason="AI 服务不可用，请手工填写", codeTaken=False, domainValid=False, degraded=True)
