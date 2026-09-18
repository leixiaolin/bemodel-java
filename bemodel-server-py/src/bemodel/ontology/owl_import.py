import re
from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS, OWL
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import transactional
from bemodel.core.exceptions import BizException
from bemodel.core.java_compat import java_hex_hash
from bemodel.modeling.entities import Axiom
from .entities import Concept, Relation, Attribute, ConceptParent, Domain


def local_name(uri):
    return re.split(r"[#/]", str(uri))[-1]


def snake(value, upper=True):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value or "")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    value = (value.upper() if upper else value.lower()) or "X"
    if value[0].isdigit():
        value = ("C_" if upper else "c_") + value
    return value[:64]


def code_of(uri):
    code = snake(local_name(uri))
    return "OWL_" + java_hex_hash(str(uri)) if code == "X" and local_name(uri) else code


def map_data_type(uri):
    name = local_name(uri)
    if name in {"string", "literal", "PlainLiteral"}:
        return "STRING"
    if name in {"integer", "int", "long", "short", "byte", "decimal", "double", "float", "nonNegativeInteger",
                "nonPositiveInteger", "positiveInteger", "negativeInteger", "unsignedInt", "unsignedLong", "unsignedShort", "unsignedByte"}:
        return "NUMBER"
    return {"date": "DATE", "dateTime": "DATE", "time": "DATE", "boolean": "ENUM"}.get(name)


class OwlImportService:
    def __init__(self, session):
        self.session = session

    def dao(self, model):
        return BaseDAO(self.session, model)

    def preview(self, data, filename):
        if not data:
            raise BizException("请上传非空的 OWL/Turtle 文件（表单字段名 file）")
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Maximum upload size exceeded")
        graph = Graph()
        try:
            graph.parse(data=data, format="turtle" if (filename or "").lower().endswith(".ttl") else "xml")
        except Exception as exc:
            raise BizException("OWL 解析失败: " + str(exc)) from exc
        items, unprojected = [], 0
        def w3c(uri):
            return str(uri).startswith("http://www.w3.org/")
        def label(uri):
            fallback = local_name(uri)
            for value in graph.objects(uri, RDFS.label):
                if isinstance(value, Literal):
                    if not value.language or value.language.startswith("zh"):
                        return str(value)
                    fallback = str(value)
            return fallback
        def comment(uri):
            return next((str(v) for v in graph.objects(uri, RDFS.comment) if isinstance(v, Literal)), None)
        def named_ref(uri, prop):
            return next((local_name(v) for v in graph.objects(uri, prop) if isinstance(v, URIRef) and not w3c(v)), None)
        def named(kind):
            return sorted({v for v in graph.subjects(RDF.type, kind) if isinstance(v, URIRef)}, key=str)
        def append(kind, uri, code, name, disposition, detail):
            items.append(dict(kind=kind, iri=str(uri), code=code, name=name, disposition=disposition, reason=None, detail=detail))
        classes = set(graph.subjects(RDF.type, OWL.Class)) | set(graph.subjects(RDF.type, RDFS.Class))
        for uri in sorted(classes, key=str):
            if isinstance(uri, BNode):
                unprojected += 1
                continue
            if w3c(uri):
                continue
            parents = []
            for parent in graph.objects(uri, RDFS.subClassOf):
                if isinstance(parent, BNode):
                    unprojected += 1
                elif isinstance(parent, URIRef) and not w3c(parent) and parent != uri:
                    parents.append(snake(local_name(parent)))
            code, detail = code_of(uri), {"comment": comment(uri), "subClassOf": parents}
            existing = self.dao(Concept).select_one(Concept.iri == str(uri))
            disposition = "CREATE"
            if existing:
                detail["match"], disposition = "IRI 命中已有概念 " + existing.code, "UPDATE"
            else:
                existing = self.dao(Concept).select_one(Concept.code == code)
                if existing:
                    disposition = "UPDATE"
                    detail["match"] = "code 命中已有概念"
                    if existing.iri and existing.iri.strip() and existing.iri != str(uri):
                        detail["match"], disposition = "code 被不同 IRI 的概念占用: " + existing.iri, "KEY_TAKEN"
            append("CLASS", uri, code, label(uri), disposition, detail)
        for uri in named(OWL.ObjectProperty):
            if w3c(uri):
                continue
            domain, range_ = named_ref(uri, RDFS.domain), named_ref(uri, RDFS.range)
            if domain is None or range_ is None:
                unprojected += 1
                continue
            detail = {"fromConcept": snake(domain), "toConcept": snake(range_), "comment": comment(uri)}
            for field, kind in [("isSymmetric", OWL.SymmetricProperty), ("isTransitive", OWL.TransitiveProperty),
                ("isFunctional", OWL.FunctionalProperty), ("isInverseFunctional", OWL.InverseFunctionalProperty), ("isAsymmetric", OWL.AsymmetricProperty)]:
                detail[field] = int((uri, RDF.type, kind) in graph)
            inverse = graph.value(uri, OWL.inverseOf)
            if isinstance(inverse, URIRef):
                detail["inverseOfIri"] = str(inverse)
            name, disposition = label(uri), "CREATE"
            existing = self.dao(Relation).select_one(Relation.iri == str(uri))
            if existing:
                detail["match"], disposition = "IRI 命中已有关系", "UPDATE"
            else:
                existing = self.dao(Relation).select_one(Relation.from_concept == detail["fromConcept"], Relation.to_concept == detail["toConcept"], Relation.relation_name == name)
                if existing:
                    detail["match"], disposition = "关系唯一键 (from,to,name) 命中", "UPDATE"
                    if existing.iri and existing.iri.strip() and existing.iri != str(uri):
                        detail["match"], disposition = "关系唯一键被不同 IRI 占用: " + existing.iri, "KEY_TAKEN"
            append("RELATION", uri, code_of(uri), name, disposition, detail)
        for uri in named(OWL.DatatypeProperty):
            if w3c(uri):
                continue
            domain = named_ref(uri, RDFS.domain)
            if domain is None:
                unprojected += 1
                continue
            range_ = graph.value(uri, RDFS.range)
            range_ = str(range_) if isinstance(range_, URIRef) else None
            mapped = map_data_type(range_) if range_ else None
            detail = {"conceptCode": snake(domain), "dataType": mapped or "STRING", "definition": comment(uri)}
            code = snake(local_name(uri), False)
            existing = self.dao(Attribute).select_one(Attribute.concept_code == detail["conceptCode"], Attribute.attr_code == code)
            disposition = "UPDATE" if existing else "CREATE"
            if range_ is None:
                detail["degradeReason"], disposition = "未声明 rdfs:range，按 STRING 落库", "DEGRADED_TO_STRING"
            elif mapped is None:
                detail.update(originalRange=range_, degradeReason="数据类型 " + local_name(range_) + " 无法映射，降级为 STRING")
                disposition = "DEGRADED_TO_STRING"
            append("ATTRIBUTE", uri, code, label(uri), disposition, detail)
        for prop in (OWL.disjointWith, OWL.equivalentClass, OWL.propertyChainAxiom):
            unprojected += len(list(graph.triples((None, prop, None))))
        for kind in (OWL.Restriction, OWL.NamedIndividual):
            unprojected += len(set(graph.subjects(RDF.type, kind)))
        items.sort(key=lambda i: (i["kind"], i["code"]))
        summary = {key: sum(i["disposition"] == value for i in items) for key, value in
            [("create", "CREATE"), ("update", "UPDATE"), ("keyTaken", "KEY_TAKEN"), ("degraded", "DEGRADED_TO_STRING")]}
        return {"items": items, "summary": summary, "unprojected": unprojected}

    def execute(self, data, filename):
        with transactional(self.session):
            plan = self.preview(data, filename)
            if not self.dao(Domain).select_count(Domain.code == "IMPORT"):
                self.dao(Domain).insert(Domain(code="IMPORT", name="OWL导入域", description="外部 OWL 本体导入的概念默认落此域", sort=99))
            counts = dict(created=0, updated=0, skipped=0, degraded=0, unprojected=plan["unprojected"])
            for item in plan["items"]:
                if item["disposition"] == "KEY_TAKEN":
                    counts["skipped"] += 1
                    continue
                counts[{"CREATE": "created", "UPDATE": "updated", "DEGRADED_TO_STRING": "degraded"}[item["disposition"]]] += 1
                detail, code = item["detail"], item["code"]
                if item["kind"] == "CLASS":
                    dao = self.dao(Concept)
                    row = dao.select_one(Concept.code == code)
                    if row is None:
                        dao.insert(Concept(code=code, name=item["name"], domain_code="IMPORT", definition=detail["comment"], iri=item["iri"], status="DRAFT", version=1))
                    else:
                        row.name, row.iri = item["name"], item["iri"]
                        if detail["comment"] and detail["comment"].strip():
                            row.definition = detail["comment"]
                        dao.update_by_id(row)
                    for parent in detail["subClassOf"]:
                        ac = "AX-IMP-" + java_hex_hash(code + "|" + parent)
                        if not self.dao(Axiom).select_count(Axiom.axiom_code == ac):
                            self.dao(Axiom).insert(Axiom(axiom_code=ac, subject=code, predicate="subClassOf", object=parent,
                                axiom_type="继承", description="OWL 导入: " + item["iri"], status="PUBLISHED"))
                elif item["kind"] == "RELATION":
                    dao = self.dao(Relation)
                    row = dao.select_one(Relation.from_concept == detail["fromConcept"], Relation.to_concept == detail["toConcept"], Relation.relation_name == item["name"])
                    body = {k: v for k, v in detail.items() if k.startswith("is") or k in {"fromConcept", "toConcept"}}
                    body.update(relationName=item["name"], description=detail["comment"], iri=item["iri"])
                    if "inverseOfIri" in detail:
                        iri = detail["inverseOfIri"]
                        inverse = next((i["name"] for i in plan["items"] if i["kind"] == "RELATION" and i["iri"] == iri), None)
                        if inverse is None:
                            existing = dao.select_one(Relation.iri == iri)
                            inverse = existing.relation_name if existing else None
                        body["inverseOf"] = inverse
                    if row:
                        body["id"] = row.id
                        dao.update_by_id(body)
                    else:
                        dao.insert(body)
                else:
                    dao = self.dao(Attribute)
                    row = dao.select_one(Attribute.concept_code == detail["conceptCode"], Attribute.attr_code == code)
                    definition = detail["definition"]
                    if "degradeReason" in detail:
                        definition = (definition + "；" if definition is not None else "") + "[" + detail["degradeReason"] + "]"
                    body = dict(conceptCode=detail["conceptCode"], attrCode=code, attrName=item["name"], dataType=detail["dataType"], definition=definition)
                    if row:
                        body["id"] = row.id
                        dao.update_by_id(body)
                    else:
                        latest = dao.select_one(Attribute.concept_code == detail["conceptCode"], order=(Attribute.sort.desc(),))
                        body.update(isKey=0, sort=(latest.sort or 0) + 1 if latest else 1)
                        dao.insert(body)
            for item in plan["items"]:
                if item["kind"] == "CLASS" and item["disposition"] != "KEY_TAKEN":
                    for index, parent in enumerate(item["detail"]["subClassOf"]):
                        dao = self.dao(ConceptParent)
                        if self.dao(Concept).select_count(Concept.code == parent) and not dao.select_count(ConceptParent.child_code == item["code"], ConceptParent.parent_code == parent):
                            dao.insert(ConceptParent(child_code=item["code"], parent_code=parent, is_primary=int(index == 0)))
            return counts
