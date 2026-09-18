from datetime import datetime
import json
from bemodel.core.base_dao import BaseDAO
from bemodel.datasource.services import DatasourceService
from bemodel.modeling.entities import Rule, Axiom
from bemodel.ontology.entities import Term
from bemodel.ontology.services import DisjointService

SOURCES = {
    "DIAG_REQUIRES_ITEM": ["诊断 ← 病案（EMR）", "医嘱执行 ← HIS"],
    "PREOP_REQUIRES": ["手术记录 ← 病案（EMR）", "术前检验 ← HIS / LIS"],
    "ABNORMAL_REQUIRES_COVER": ["检验报告 ← LIS", "诊断与处置 ← 病案（EMR）/ HIS"],
    "COMPLICATION_REQUIRES_ITEM": ["并发症诊断 ← 病案（EMR）", "处置医嘱 ← HIS"],
    "SEX_DISJOINT_DIAG": ["患者性别 ← HIS 住院登记", "诊断 ← 病案（EMR）"],
    "EXAM_ABNORMAL_REQUIRES_COVER": ["检查报告 ← PACS", "诊断与处置 ← 病案（EMR）/ HIS"],
    "ALLERGY_DISJOINT": ["过敏史 ← 病案（EMR）", "药品医嘱 ← HIS", "药品过敏原 ← 药房·药品字典"],
    "DOSE_LIMIT": ["医嘱剂量/频次 ← HIS", "日最大剂量 ← 药房·药品字典"],
}


def timestamp(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds" if value.microsecond else "seconds" if value.second else "minutes")
    return str(value)


def java_g(value):
    # Java Formatter %g retains significant trailing zeros (Python g removes them).
    return format(float(value), "#.6g")


class QcRuleEngine:
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)

    def term_expand(self, keyword):
        try:
            dao = BaseDAO(self.session, Term)
            seed = dao.select_one(Term.term == keyword)
            return list(dict.fromkeys([keyword] + ([t.term for t in dao.select_list(Term.concept_code == seed.concept_code)] if seed else [])))
        except Exception:
            return [keyword]

    def disjoint_basis(self, expr):
        if expr.get("axiom") is None:
            return None
        axiom = BaseDAO(self.session, Axiom).select_one(Axiom.axiom_code == expr["axiom"])
        if axiom is None:
            return None
        service = DisjointService(self.session)
        a, b = service.resolve_concept_code(axiom.subject), service.resolve_concept_code(axiom.object)
        return service.find_pair(a, b) if a is not None and b is not None and a != b else None

    def run_rules(self, inhos_no, sex, diags):
        findings, cited_rules, cited_axioms = [], [], []
        for rule in BaseDAO(self.session, Rule).select_list(Rule.engine == "QC", Rule.status == "PUBLISHED"):
            try:
                expr = json.loads(rule.expr_json)
                evidence = self.evaluate(expr, inhos_no, sex, diags)
                for message in evidence:
                    findings.append(dict(ruleCode=rule.rule_code, ruleName=rule.name, severity=rule.severity,
                        evidence=message, axiom=expr.get("axiom"), sources=SOURCES.get(expr["type"], [])))
                if evidence:
                    if rule.rule_code not in cited_rules:
                        cited_rules.append(rule.rule_code)
                    if expr.get("axiom") is not None and expr["axiom"] not in cited_axioms:
                        cited_axioms.append(expr["axiom"])
            except Exception:
                # Java isolates malformed expressions to the individual rule.
                continue
        return dict(findings=findings, rulesCited=cited_rules, axiomsCited=cited_axioms)

    def evaluate(self, e, patient, sex, diags):
        query = lambda ds, sql: self.ds.query(ds, sql, {"patient": patient})
        def executed(codes, before=None):
            orders = query("DS_HIS", "SELECT item_code,create_time FROM medical_order WHERE inhos_no=:patient AND order_status='1'")
            return any(o["item_code"] in codes and (before is None or o["create_time"] < before) for o in orders)
        result, kind = [], e["type"]
        if kind in {"DIAG_REQUIRES_ITEM", "COMPLICATION_REQUIRES_ITEM"}:
            for case in e["cases"]:
                for diag in diags:
                    if any(k in diag for k in case["diagKeywords"]) and not executed(case["codes"]):
                        result.append(f"诊断「{diag}」缺少客观依据：未见{case['requireName']}记录" if kind == "DIAG_REQUIRES_ITEM" else f"并发症「{diag}」未见处置：无{case['requireName']}医嘱")
        elif kind == "PREOP_REQUIRES":
            for surgery in query("DS_EMR", "SELECT * FROM emr_surgery WHERE inhos_no=:patient"):
                missing = [r["requireName"] for r in e["requires"] if not executed(r["codes"], surgery["proc_time"])]
                if missing:
                    result.append(f"手术「{surgery['proc_name']}」({timestamp(surgery['proc_time'])}) 术前缺少：{'、'.join(missing)}")
        elif kind == "ABNORMAL_REQUIRES_COVER":
            for ab in query("DS_LIS", "SELECT report_id,item_code,report_time FROM lab_report WHERE patient_no=:patient AND result_status='A'"):
                if not any(k in d for d in diags for k in e["coverDiagKeywords"]) and not executed(e["coverCodes"]):
                    result.append(f"检验报告 {ab['report_id']}（{ab['item_code']}，{timestamp(ab['report_time'])}）结果异常，但病案中无对应诊断或处置医嘱")
        elif kind == "SEX_DISJOINT_DIAG" and e["sex"] == sex:
            basis, expanded, origins = self.disjoint_basis(e), [], {}
            for keyword in e["diagKeywords"]:
                for term in self.term_expand(keyword):
                    if term not in expanded:
                        expanded.append(term)
                        if term != keyword:
                            origins[term] = keyword
            for diag in diags:
                via = next((t for t in expanded if t in diag and t in origins), None)
                if any(t in diag for t in expanded):
                    evidence = (f"{sex}患者出现互斥诊断「{diag}」（公理表 bm_concept_disjoint：{basis.concept_a_code} ✕ {basis.concept_b_code}）" if basis else f"{sex}患者出现互斥诊断「{diag}」（违反公理{e['axiom']}）")
                    result.append(evidence + (f"（术语扩展命中：{origins[via]}→{via}）" if via else ""))
        elif kind == "EXAM_ABNORMAL_REQUIRES_COVER":
            surgeries = query("DS_EMR", "SELECT surg_id FROM emr_surgery WHERE inhos_no=:patient")
            for ab in query("DS_PACS", "SELECT exam_id,item_name,conclusion,report_time FROM exam_report WHERE patient_no=:patient AND abnormal_flag='Y'"):
                if not any(k in d for d in diags for k in e["coverDiagKeywords"]) and not (e.get("coverProcedure") and surgeries):
                    result.append(f"检查报告 {ab['exam_id']}（{ab['item_name']}）结论异常「{ab['conclusion']}」，但无对应诊断或进一步处置")
        elif kind == "ALLERGY_DISJOINT":
            allergies = [r["allergen"] for r in query("DS_EMR", "SELECT allergen FROM patient_allergy WHERE inhos_no=:patient")]
            if not allergies:
                return []
            basis = self.disjoint_basis(e)
            dictionary = {r["drug_code"]: r["allergen"] for r in self.ds.query("DS_PHARMACY", "SELECT drug_code,allergen FROM drug_dict WHERE allergen IS NOT NULL")}
            for order in query("DS_HIS", "SELECT order_id,item_code,item_name FROM medical_order WHERE inhos_no=:patient AND order_type='药品' AND order_status='1'"):
                allergen = dictionary.get(order["item_code"])
                if allergen is None:
                    continue
                direct = allergen in allergies
                via = None if direct else next((a for a in allergies if a != allergen and set(self.term_expand(a)) & set(self.term_expand(allergen))), None)
                if direct or via:
                    evidence = f"患者对「{allergen}」过敏，已执行医嘱 {order['order_id']}（{order['item_name']}，含{allergen}过敏原）违反过敏禁忌"
                    if basis:
                        evidence += f"（公理表 bm_concept_disjoint：{basis.concept_a_code} ✕ {basis.concept_b_code}）"
                    if via:
                        evidence += f"（术语扩展命中：过敏史「{via}」与药品过敏原「{allergen}」同词族）"
                    result.append(evidence)
        elif kind == "DOSE_LIMIT":
            dictionary = {r["drug_code"]: r for r in self.ds.query("DS_PHARMACY", "SELECT drug_code,drug_name,max_daily_dose FROM drug_dict WHERE max_daily_dose IS NOT NULL")}
            for order in query("DS_HIS", "SELECT order_id,item_code,item_name,single_dose,dose_unit,frequency FROM medical_order WHERE inhos_no=:patient AND order_type='药品' AND order_status='1' AND single_dose IS NOT NULL"):
                drug = dictionary.get(order["item_code"])
                if drug is None:
                    continue
                dose, maximum = order["single_dose"], drug["max_daily_dose"]
                daily = dose * {"bid": 2, "tid": 3, "q8h": 3}.get(order["frequency"], 1)
                if daily > maximum:
                    unit = order["dose_unit"]
                    result.append(f"医嘱 {order['order_id']}（{order['item_name']}）单日剂量 {java_g(daily)}{unit} 超日最大剂量 {java_g(maximum)}{unit}（{java_g(dose)}×{order['frequency']}）")
        return result
