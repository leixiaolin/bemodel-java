from collections import defaultdict, deque
from datetime import datetime
import re
from sqlalchemy import or_, and_, text
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.core.state_machine import check
from bemodel.datasource.entities import Mapping
from .entities import Concept, ConceptParent, Attribute, Relation, Term, Disjoint, Metric


class ConceptService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Concept)

    def get_by_code(self, code):
        return self.select_one(Concept.code == code)

    def require(self, code):
        concept = self.get_by_code(code)
        if concept is None:
            raise BizException("概念不存在: " + code)
        return concept

    def list_by_domain(self, domain_code=None):
        return self.select_list(*([Concept.domain_code == domain_code] if domain_code and domain_code.strip() else []), order=(Concept.code,))

    def detail(self, code):
        return {"concept": self.require(code),
                "attributes": BaseDAO(self.session, Attribute).select_list(Attribute.concept_code == code, order=(Attribute.sort,)),
                "relations": BaseDAO(self.session, Relation).select_list(or_(Relation.from_concept == code, Relation.to_concept == code)),
                "terms": BaseDAO(self.session, Term).select_list(Term.concept_code == code), "parents": self.list_parents(code)}

    def list_parents(self, code):
        return BaseDAO(self.session, ConceptParent).select_list(ConceptParent.child_code == code,
                    order=(ConceptParent.is_primary.desc(), ConceptParent.parent_code))

    def ancestors_of(self, code):
        seen, queue = set(), deque([code])
        while queue:
            for row in self.list_parents(queue.popleft()):
                if row.parent_code not in seen:
                    seen.add(row.parent_code)
                    queue.append(row.parent_code)
        return seen - {code}

    def clear_primary(self, code):
        dao = BaseDAO(self.session, ConceptParent)
        for row in dao.select_list(ConceptParent.child_code == code, ConceptParent.is_primary == 1):
            row.is_primary = 0
            dao.update_by_id(row)

    def add_parent(self, code, parent_code, is_primary=0):
        self.require(code)
        if not parent_code or not parent_code.strip():
            raise BizException("父概念编码不能为空")
        if code == parent_code:
            raise BizException("概念不能继承自身: " + code)
        if self.get_by_code(parent_code) is None:
            raise BizException("父概念不存在: " + parent_code)
        dao = BaseDAO(self.session, ConceptParent)
        if dao.select_count(ConceptParent.child_code == code, ConceptParent.parent_code == parent_code):
            raise BizException(f"继承关系已存在: {code} → {parent_code}")
        if code in self.ancestors_of(parent_code):
            raise BizException(f"不允许成环: {parent_code} 的祖先链上已存在 {code}")
        if is_primary == 1:
            self.clear_primary(code)
        return dao.insert(ConceptParent(child_code=code, parent_code=parent_code, is_primary=int(is_primary == 1)))

    def remove_parent(self, code, parent_code):
        BaseDAO(self.session, ConceptParent).delete(ConceptParent.child_code == code, ConceptParent.parent_code == parent_code)

    def set_primary_parent(self, code, parent_code):
        dao = BaseDAO(self.session, ConceptParent)
        row = dao.select_one(ConceptParent.child_code == code, ConceptParent.parent_code == parent_code)
        if row is None:
            raise BizException(f"继承关系不存在: {code} → {parent_code}")
        self.clear_primary(code)
        row.is_primary = 1
        return dao.update_by_id(row)

    def create(self, data):
        row = self.entity(data)
        if self.get_by_code(row.code) is not None:
            raise BizException("概念编码已存在: " + row.code)
        row.status, row.version = "DRAFT", 1
        return self.insert(row)

    def delete_draft(self, code):
        row = self.require(code)
        if row.status != "DRAFT":
            raise BizException("仅草稿(DRAFT)状态可删除，当前状态: " + row.status)
        counts = [BaseDAO(self.session, model).select_count(condition) for model, condition in [
            (Attribute, Attribute.concept_code == code),
            (Relation, or_(Relation.from_concept == code, Relation.to_concept == code)),
            (Term, Term.concept_code == code), (Mapping, Mapping.concept_code == code),
            (ConceptParent, or_(ConceptParent.child_code == code, ConceptParent.parent_code == code))]]
        if sum(counts):
            raise BizException("概念存在引用，拒绝删除: 属性%d个、关系%d条、术语%d条、字段映射%d条、继承边%d条" % tuple(counts))
        self.delete_by_id(row.id)

    def transition(self, code, target):
        row = self.require(code)
        check(row.status, target)
        row.status = target
        if target == "PUBLISHED":
            row.version += 1
        return self.update_by_id(row)


class RelationService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Relation)

    @staticmethod
    def ref(row):
        return f"{row.from_concept}->{row.to_concept}#{row.relation_name}"

    @staticmethod
    def defaults(row):
        for field in ("is_symmetric", "is_transitive", "is_functional", "is_inverse_functional", "is_asymmetric"):
            if getattr(row, field) is None:
                setattr(row, field, 0)

    def create(self, data):
        row = self.entity(data)
        if self.select_count(Relation.from_concept == row.from_concept, Relation.to_concept == row.to_concept,
                             Relation.relation_name == row.relation_name):
            raise BizException("关系已存在: " + self.ref(row))
        self.defaults(row)
        return self.insert(row)

    def update(self, data):
        row = self.entity(data)
        if row.id is None or self.select_by_id(row.id) is None:
            raise BizException("关系不存在，无法更新: id=" + (str(row.id) if row.id is not None else "null"))
        self.defaults(row)
        return self.update_by_id(row)


class DisjointService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Disjoint)

    def find_pair(self, a, b):
        return self.select_one(or_(and_(Disjoint.concept_a_code == a, Disjoint.concept_b_code == b),
                                   and_(Disjoint.concept_a_code == b, Disjoint.concept_b_code == a)))

    def is_disjoint(self, a, b):
        return self.find_pair(a, b) is not None

    def create(self, a, b, definition=None):
        if not a or not a.strip() or not b or not b.strip():
            raise BizException("互斥两端的概念编码不能为空")
        if a == b:
            raise BizException("互斥两端不能是同一概念: " + a)
        ConceptService(self.session).require(a)
        ConceptService(self.session).require(b)
        if self.find_pair(a, b):
            raise BizException(f"互斥对已存在: {a} ✕ {b}")
        return self.insert(Disjoint(concept_a_code=min(a, b), concept_b_code=max(a, b), definition=definition, status="PUBLISHED"))

    def resolve_concept_code(self, value):
        if value is None:
            return None
        value = re.sub("（.*?）", "", value).strip()
        row = BaseDAO(self.session, Concept).select_one(or_(Concept.code == value, Concept.name == value))
        return row.code if row else None


class OntologyCheckService:
    def __init__(self, session):
        self.session = session

    def check(self):
        defects = []
        def add(kind, severity, message, refs):
            defects.append(dict(type=kind, severity=severity, message=message, refs=refs))
        relations = BaseDAO(self.session, Relation).select_list()
        concepts = BaseDAO(self.session, Concept).select_list()
        for r in relations:
            refs = [RelationService.ref(r)]
            if r.is_symmetric == 1 and r.is_asymmetric == 1:
                add("SYMMETRIC_ASYMMETRIC", "BLOCKER", "关系同时声明了对称与反对称公理", refs)
            if r.is_transitive == 1 and r.is_functional == 1:
                add("TRANSITIVE_FUNCTIONAL", "WARN", "关系同时声明了传递与函数公理（传递闭包与唯一值语义冲突）", refs)
            if r.inverse_of and r.inverse_of.strip():
                if r.inverse_of == r.relation_name:
                    add("INVERSE_SELF", "BLOCKER", "关系的互逆关系指向自身", refs)
                else:
                    candidates = [c for c in relations if c.relation_name == r.inverse_of]
                    inverse = next((c for c in candidates if c.from_concept == r.to_concept and c.to_concept == r.from_concept), candidates[0] if candidates else None)
                    if inverse is None:
                        add("INVERSE_NOT_MUTUAL", "WARN", "inverse_of 指向的关系不存在: " + r.inverse_of, refs)
                    elif inverse.inverse_of != r.relation_name:
                        add("INVERSE_NOT_MUTUAL", "WARN", f"互逆未成对声明: {r.inverse_of} 的 inverse_of={inverse.inverse_of or 'null'}", refs + [RelationService.ref(inverse)])
        codes = {c.code for c in concepts}
        for row in BaseDAO(self.session, Disjoint).select_list():
            pair = [row.concept_a_code, row.concept_b_code]
            if pair[0] == pair[1]:
                add("DISJOINT_SELF", "BLOCKER", "互斥行两端是同一概念", pair)
            elif any(c not in codes for c in pair):
                add("DISJOINT_DANGLING", "WARN", "互斥行引用了不存在的概念: " + "、".join(c for c in pair if c not in codes), pair)
        iris = defaultdict(list)
        for c in concepts:
            if c.iri and c.iri.strip():
                iris[c.iri].append(c.code)
        for iri, refs in iris.items():
            if len(refs) > 1:
                add("IRI_DUPLICATE", "BLOCKER", "多个概念共用同一 IRI: " + iri, sorted(refs))
        adjacency, nodes = defaultdict(list), set()
        for p in BaseDAO(self.session, ConceptParent).select_list():
            adjacency[p.child_code].append(p.parent_code)
            nodes.update([p.child_code, p.parent_code])
        colors, cycles, stack = {}, set(), []
        def visit(node):
            colors[node] = 1
            stack.append(node)
            for parent in adjacency[node]:
                if colors.get(parent, 0) == 1:
                    ring = stack[stack.index(parent):]
                    i = ring.index(min(ring))
                    rotated = ring[i:] + ring[:i] + [ring[i]]
                    cycles.add("→".join(rotated))
                elif colors.get(parent, 0) == 0:
                    visit(parent)
            stack.pop()
            colors[node] = 2
        for node in sorted(nodes):
            if not colors.get(node):
                visit(node)
        for cycle in sorted(cycles):
            add("SUBCLASS_CYCLE", "BLOCKER", "概念继承存在环: " + cycle, cycle.split("→"))
        return sorted(defects, key=lambda d: (d["type"], ",".join(d["refs"])))

    @staticmethod
    def describe(defects):
        return "；".join(f"[{d['type']}/{d['severity']}] {d['message']} [{', '.join(d['refs'])}]" for d in defects)


class MetricService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Metric)

    def evaluate(self, code):
        from bemodel.datasource.services import DatasourceService
        row = self.select_one(Metric.metric_code == code)
        if row is None:
            raise BizException("指标不存在: " + code)
        if not row.probe_sql or not row.probe_sql.strip() or not row.ds_code or not row.ds_code.strip():
            raise BizException("指标未绑定实测探针: " + code)
        with DatasourceService(self.session).jdbc(row.ds_code).connect() as conn:
            value = conn.execute(text(row.probe_sql)).scalar_one()
        row.last_val, row.last_eval_at = value, datetime.now()
        self.update_by_id(row)
        return {"metricCode": row.metric_code, "name": row.name, "value": value, "warnThreshold": row.warn_threshold,
                "alarm": row.warn_threshold is not None and value is not None and value > row.warn_threshold, "evaluatedAt": row.last_eval_at}

    def evaluate_all(self):
        results = []
        for row in self.select_list(Metric.probe_sql.is_not(None)):
            try:
                results.append(self.evaluate(row.metric_code))
            except Exception as exc:
                results.append({"metricCode": row.metric_code, "name": row.name, "alarm": True, "error": str(exc)})
        return results
