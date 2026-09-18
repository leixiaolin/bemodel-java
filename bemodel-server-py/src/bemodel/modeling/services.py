from collections import defaultdict, deque
import json
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import transactional
from bemodel.core.exceptions import BizException
from bemodel.core.result import to_camel_dict
from bemodel.core.state_machine import check
from bemodel.ontology.entities import Concept, Attribute, Relation, RelationClosure, Term, Metric
from bemodel.ontology.services import OntologyCheckService
from .entities import Rule, Action, Release


class ElementService(BaseDAO):
    def __init__(self, session, model, code_field, label):
        super().__init__(session, model)
        self.code_field, self.label = code_field, label

    def list(self, concept_code=None):
        return self.select_list(*([self.model.concept_code == concept_code] if concept_code and concept_code.strip() else []),
                                order=(getattr(self.model, self.code_field),))

    def create(self, data):
        row = self.entity(data)
        code = getattr(row, self.code_field)
        if self.select_count(getattr(self.model, self.code_field) == code):
            raise BizException(self.label + "编码已存在: " + code)
        row.status, row.version = "DRAFT", 1
        return self.insert(row)

    def transition(self, code, target):
        row = self.select_one(getattr(self.model, self.code_field) == code)
        if row is None:
            raise BizException(self.label + "不存在: " + code)
        check(row.status, target)
        row.status = target
        if target == "PUBLISHED":
            row.version += 1
        return self.update_by_id(row)


class RuleService(ElementService):
    def __init__(self, session):
        super().__init__(session, Rule, "rule_code", "规则")


class ActionService(ElementService):
    def __init__(self, session):
        super().__init__(session, Action, "action_code", "动作")


class ReleaseService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Release)

    def current_tag(self):
        row = self.select_one(order=(Release.id.desc(),))
        return row.version_tag if row else None

    def next_tag(self):
        current = self.current_tag()
        if current is None:
            return "v1.0"
        try:
            major, minor, *_ = current[1:].split(".")
            return f"v{major}.{int(minor)+1}"
        except (ValueError, IndexError):
            return current + ".1"

    def publish(self, summary=None, released_by=None, force=False):
        with transactional(self.session):
            checker = OntologyCheckService(self.session)
            defects = checker.check()
            blockers = [d for d in defects if d["severity"] == "BLOCKER"]
            if blockers:
                raise BizException(f"本体自检未通过，存在 {len(blockers)} 个阻断缺陷，禁止发布: " + checker.describe(blockers))
            if defects and not force:
                raise BizException(f"本体自检存在 {len(defects)} 个警告，确认后可带 force=true 发布: " + checker.describe(defects))
            try:
                concepts = BaseDAO(self.session, Concept).select_list(Concept.status == "PUBLISHED")
                snapshot = {"concepts": concepts,
                    "attributes": BaseDAO(self.session, Attribute).select_list(Attribute.concept_code.in_([c.code for c in concepts])),
                    "relations": BaseDAO(self.session, Relation).select_list(),
                    "terms": BaseDAO(self.session, Term).select_list(), "metrics": BaseDAO(self.session, Metric).select_list(),
                    "rules": BaseDAO(self.session, Rule).select_list(Rule.status == "PUBLISHED"),
                    "actions": BaseDAO(self.session, Action).select_list(Action.status == "PUBLISHED")}
                count = sum(len(v) for v in snapshot.values())
                snapshot["relationClosures"] = self.rebuild_relation_closures()
                return self.insert(Release(version_tag=self.next_tag(), change_summary=summary, element_count=count,
                    snapshot_json=json.dumps(to_camel_dict(snapshot), ensure_ascii=False, separators=(",", ":")), released_by=released_by))
            except Exception as exc:
                raise RuntimeError("发布失败: " + str(exc)) from exc

    def rebuild_relation_closures(self):
        rows = BaseDAO(self.session, Relation).select_list()
        dao, stats = BaseDAO(self.session, RelationClosure), {}
        for name in sorted({r.relation_name for r in rows if r.is_transitive == 1}):
            adjacency = defaultdict(list)
            for r in rows:
                if r.relation_name == name:
                    adjacency[r.from_concept].append(r.to_concept)
            dao.delete(RelationClosure.relation_name == name)
            derived, capped = 0, False
            for source in sorted(adjacency):
                depths, queue = {}, deque()
                for first in adjacency[source]:
                    if first != source and first not in depths:
                        depths[first] = 1
                        queue.append(first)
                while queue:
                    current = queue.popleft()
                    depth = depths[current]
                    if depth >= 12:
                        capped = capped or bool(adjacency.get(current))
                        continue
                    for target in adjacency.get(current, []):
                        if target != source and target not in depths:
                            depths[target] = depth + 1
                            queue.append(target)
                for target, depth in depths.items():
                    dao.insert(RelationClosure(relation_name=name, from_concept=source, to_concept=target, depth=depth))
                    derived += 1
            stats[name] = {"edges": sum(map(len, adjacency.values())), "derived": derived, "capped": capped}
        return stats

    def closure_of(self, relation, concept):
        rows = BaseDAO(self.session, RelationClosure).select_list(RelationClosure.relation_name == relation,
            RelationClosure.from_concept == concept, order=(RelationClosure.depth, RelationClosure.to_concept))
        return {"relation": relation, "concept": concept, "count": len(rows),
                "reachable": [{"concept": r.to_concept, "depth": r.depth} for r in rows]}
