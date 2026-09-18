from datetime import datetime
from pathlib import Path
from threading import Lock
import re
from rdflib import Graph, Namespace
from pyshacl import validate
from bemodel.core.exceptions import BizException
from bemodel.datasource.services import DatasourceService


def mask_name(name):
    if not name or len(name) == 1:
        return "*"
    return name[0] + "*" + (name[-1] if len(name) > 2 else "")


class RdfService:
    def __init__(self, session):
        self.ds = DatasourceService(session)

    def export_patient(self, inhos_no, mask=True):
        def query(ds, sql, value=None):
            return self.ds.query(ds, sql, {"value": value} if value is not None else {})
        patients = query("DS_HIS", "SELECT * FROM inpatient WHERE inhos_no=:value", inhos_no)
        if not patients:
            raise BizException("患者不存在: " + inhos_no)
        p = patients[0]
        name = mask_name(p["patient_name"]) if mask else p["patient_name"]
        patient, encounter = "med:Patient_" + inhos_no, "med:InpEncounter_" + inhos_no
        out = ['@prefix med:  <http://bemodel.com/ontology/med#> .\n',
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n',
            '@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n\n',
            '# ===== 患者 ABox（由 BeModel 实例装配器从产品库实时投影生成） =====\n',
            f'# 患者：{name} 住院号：{inhos_no} 导出时间：{datetime.now().isoformat()}\n',
            '# 覆盖 SHACL 输入：Shape1 过敏禁忌 / Shape2 剂量上限 / Shape3 儿童禁用 / Shape4 性别互斥 / Shape5 相互作用 / Shape6 审核闭环\n\n',
            f'{patient} a med:Patient ;\n   rdfs:label "{name}" ;\n   med:sex "{p["sex"]}" ;\n   med:age "{p["age"]}"^^xsd:integer ;\n   med:hasEncounter {encounter} .\n\n',
            f'{encounter} a med:InpEncounter ;\n   rdfs:label "住院就诊 {inhos_no}" .\n',
            f'{encounter} a med:Encounter .\n\n']
        for a in query("DS_EMR", "SELECT * FROM patient_allergy WHERE inhos_no=:value", inhos_no):
            uri = "med:Allergen_" + a["allergen"]
            out.append(f'{uri} a med:Allergen ; rdfs:label "{a["allergen"]}" .\n{patient} med:hasAllergyTo {uri} .\n\n')
        drugs = {d["drug_code"]: d for d in query("DS_PHARMACY", "SELECT * FROM drug_dict")}
        seq = 0
        for record in query("DS_EMR", "SELECT * FROM emr_record WHERE inhos_no=:value", inhos_no):
            for diag_name in re.split("[，,]", record["diag_list"] or "null"):
                diag_name = diag_name.strip()
                if not diag_name:
                    continue
                seq += 1
                uri = f"med:Diagnosis_{inhos_no}_{seq}"
                dictionary = query("DS_EMR", "SELECT snomed_code,icd10 FROM diag_dict WHERE diag_name=:value", diag_name)
                out.append(f'{uri} a med:Diagnosis ;\n   rdfs:label "{diag_name}"')
                if dictionary:
                    for column, prop in [("snomed_code", "snomedCode"), ("icd10", "icd10Code")]:
                        if dictionary[0][column] is not None:
                            out.append(f' ;\n   med:{prop} "{dictionary[0][column]}"')
                out.append(f' .\n{encounter} med:hasDiagnosis {uri} .\n\n')
        orders = query("DS_HIS", "SELECT * FROM medical_order WHERE inhos_no=:value AND order_type='药品' AND order_status='1'", inhos_no)
        for o in orders:
            order, drug, doctor = "med:DrugOrder_" + o["order_id"], "med:Drug_" + o["item_code"], "med:Doctor_" + o["doctor"]
            out.append(f'{order} a med:DrugOrder ;\n   rdfs:label "{o["item_name"]} 医嘱 {o["order_id"]}" ;\n   med:prescribesDrug {drug} ;\n   med:prescribedBy {doctor} ;\n   med:orderStatus "已执行"')
            if o.get("single_dose") is not None:
                out.append(f' ;\n   med:singleDose "{o["single_dose"]}"^^xsd:decimal')
            if o.get("frequency") is not None:
                out.append(f' ;\n   med:frequency "{o["frequency"]}"')
            out.append(f' .\n{drug} a med:Drug ; rdfs:label "{o["item_name"]}"')
            dk = drugs.get(o["item_code"])
            if dk:
                if dk.get("max_daily_dose") is not None:
                    out.append(f' ;\n   med:maxDailyDose "{dk["max_daily_dose"]}"^^xsd:decimal')
                if dk.get("allergen") is not None:
                    out.append(f' ;\n   med:containsAllergen med:Allergen_{dk["allergen"]}')
                if dk.get("child_forbidden") == "Y":
                    out.append(' ;\n   med:childForbidden true')
                if dk.get("interacts_with") is not None:
                    for other in dk["interacts_with"].split(","):
                        out.append(' ;\n   med:interactsWith med:Drug_' + other.strip())
            out.append(f' .\n{doctor} a med:Doctor ; rdfs:label "{o["doctor"]}" .\n{encounter} med:hasOrder {order} .\n')
            passed = query("DS_PHARMACY", "SELECT pharmacist FROM presc_review WHERE order_id=:value AND review_result='通过'", o["order_id"])
            out.append(f'med:Prescription_{o["order_id"]} a med:Prescription ;\n   rdfs:label "处方 {o["order_id"]}" ;\n   med:prescribedBy {doctor}')
            if passed:
                out.append(' ;\n   med:reviewedBy med:Pharmacist_' + passed[0]["pharmacist"])
            out.append(' .\n')
            if passed:
                pharmacist = passed[0]["pharmacist"]
                out.append(f'med:Pharmacist_{pharmacist} a med:Pharmacist ; rdfs:label "{pharmacist}" .\n')
            for d in query("DS_PHARMACY", "SELECT * FROM dispense_record WHERE order_id=:value AND status='1'", o["order_id"]):
                out.append(f'med:Dispense_{d["dispense_id"]} a med:ClinicalAct ;\n   rdfs:label "发药 {d["dispense_id"]}" ;\n   rdfs:comment "药师 {d["pharmacist"]}" .\n\n')
        for r in query("DS_LIS", "SELECT r.*,a.item_name FROM lab_report r JOIN lab_apply a ON r.apply_id=a.apply_id WHERE r.patient_no=:value", inhos_no):
            abnormal = "true" if r["result_status"] == "A" else "false"
            out.append(f'med:LabResult_{r["report_id"]} a med:LabResult ;\n   rdfs:label "{r["item_name"]}报告 {r["report_id"]}" ;\n   med:isAbnormal {abnormal} .\n')
            out.append(f'{encounter} med:hasOrder med:LabOrder_{r["apply_id"]} .\nmed:LabOrder_{r["apply_id"]} a med:LabOrder ; rdfs:label "{r["item_name"]}" .\n\n')
        return "".join(out)


_shapes = None
_lock = Lock()


def load_shapes():
    global _shapes
    if _shapes is None:
        with _lock:
            if _shapes is None:
                _shapes = Graph().parse(Path(__file__).resolve().parents[1] / "resources/shacl/clinical-shapes.ttl", format="turtle")
    return _shapes


class ShaclService:
    def __init__(self, session):
        self.rdf = RdfService(session)

    def validate_patient(self, inhos_no):
        return self.validate_turtle(inhos_no, self.rdf.export_patient(inhos_no))

    @staticmethod
    def validate_turtle(inhos_no, turtle):
        conforms, report, _ = validate(Graph().parse(data=turtle, format="turtle"), shacl_graph=load_shapes(), advanced=True)
        sh = Namespace("http://www.w3.org/ns/shacl#")
        violations = []
        for result in report.subjects(sh.focusNode, None):
            path = report.value(result, sh.resultPath)
            violations.append({"focusNode": str(report.value(result, sh.focusNode)), "path": f"<{path}>" if path is not None else "",
                "message": str(report.value(result, sh.resultMessage)), "severity": "Violation"})
        return {"patientId": inhos_no, "conforms": bool(conforms), "violations": violations, "violationCount": len(violations),
                "shapes": "shacl/clinical-shapes.ttl（6 Shapes）", "engine": "pySHACL"}
