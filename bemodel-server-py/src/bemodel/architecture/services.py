from collections import defaultdict
from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.entities import Domain, Concept, Relation, Metric
from bemodel.datasource.entities import Datasource, Mapping, PhysicalTable
from bemodel.modeling.entities import Rule


class ArchitectureService:
    def __init__(self, session):
        self.session = session

    def overview(self):
        domains = BaseDAO(self.session, Domain).select_list(order=(Domain.sort,))
        concepts, relations, mappings, rules, metrics = [BaseDAO(self.session, cls).select_list() for cls in (Concept, Relation, Mapping, Rule, Metric)]
        sources = BaseDAO(self.session, Datasource).select_list(order=(Datasource.ds_code,))
        tables = [t for ds in sources for t in BaseDAO(self.session, PhysicalTable).select_list(PhysicalTable.ds_code == ds.ds_code, order=(PhysicalTable.table_name,))]
        coverage = defaultdict(set)
        for m in mappings:
            coverage[m.concept_code].add((m.ds_code, m.table_name))
        nodes, edges = {}, {}
        def node(id, type, code, name, domain=None, stats=None):
            value = dict(id=id, type=type, code=code, name=name)
            if domain is not None:
                value["domainCode"] = domain
            if stats is not None:
                value["stats"] = stats
            nodes.setdefault(id, value)
        def edge(kind, source, target, label=None):
            if source not in nodes or target not in nodes:
                return
            id = f"{kind}|{source}->{target}" + ("|" + label if label is not None else "")
            value = dict(id=id, source=source, target=target, kind=kind)
            if label is not None:
                value["label"] = label
            edges.setdefault(id, value)
        for d in domains:
            node("D:"+d.code, "DOMAIN", d.code, d.name)
        for c in concepts:
            node("C:"+c.code, "CONCEPT", c.code, c.name, c.domain_code, {"mappingCount": len(coverage[c.code])})
        for ds in sources:
            node("DS:"+ds.ds_code, "DATASOURCE", ds.ds_code, ds.ds_name)
        for t in tables:
            node(f"T:{t.ds_code}.{t.table_name}", "TABLE", t.table_name, t.table_comment if t.table_comment and t.table_comment.strip() else t.table_name)
        for r in rules:
            node("R:"+r.rule_code, "RULE", r.rule_code, r.name)
        for m in metrics:
            node("M:"+m.metric_code, "METRIC", m.metric_code, m.name)
        for c in concepts:
            edge("BELONG", "D:"+(c.domain_code or "null"), "C:"+c.code)
        for r in relations:
            edge("RELATION", "C:"+r.from_concept, "C:"+r.to_concept, r.relation_name)
        for m in mappings:
            edge("MAPPING", "C:"+m.concept_code, f"T:{m.ds_code}.{m.table_name}")
        for r in rules:
            edge("RULE_BIND", "C:"+(r.concept_code or "null"), "R:"+r.rule_code)
        for m in metrics:
            if m.concept_code and m.concept_code.strip():
                edge("METRIC_BIND", "C:"+m.concept_code, "M:"+m.metric_code)
        for t in tables:
            edge("DS_TABLE", "DS:"+t.ds_code, f"T:{t.ds_code}.{t.table_name}")
        return dict(nodes=sorted(nodes.values(), key=lambda n: (n["type"], n["id"])), edges=sorted(edges.values(), key=lambda e: (e["kind"], e["id"])))
