from datetime import datetime
import json
import re
from sqlalchemy import text
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.core.page_result import page_result
from bemodel.datasource.services import DatasourceService
from bemodel.modeling.services import ReleaseService
from bemodel.llm.services import DeepSeekClient
from bemodel.link.services import LinkService
from bemodel.link.entities import LinkNode
from .rule_engine import QcRuleEngine, timestamp
from .entities import QcResult


class QcService:
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)

    def records(self, keyword=None):
        where = " WHERE patient_name LIKE :keyword OR inhos_no LIKE :keyword" if keyword and keyword.strip() else ""
        return self.ds.query("DS_EMR", "SELECT * FROM emr_record" + where + " ORDER BY create_time DESC", {"keyword": f"%{keyword}%"})

    def records_page(self, keyword, page, size):
        where = " WHERE patient_name LIKE :keyword OR inhos_no LIKE :keyword" if keyword and keyword.strip() else ""
        params = dict(keyword=f"%{keyword}%", size=size, offset=(page-1)*size)
        total = self.ds.query("DS_EMR", "SELECT COUNT(*) AS n FROM emr_record" + where, params)[0]["n"]
        rows = self.ds.query("DS_EMR", "SELECT * FROM emr_record" + where + " ORDER BY create_time DESC LIMIT :size OFFSET :offset", params)
        return page_result(rows, total, page, size)

    def check(self, record_id):
        rows = self.ds.query("DS_EMR", "SELECT * FROM emr_record WHERE record_id=:id", {"id": record_id})
        if not rows:
            raise BizException("病案不存在: " + record_id)
        record = rows[0]
        patient = self.ds.query("DS_HIS", "SELECT sex,patient_name FROM inpatient WHERE inhos_no=:id", {"id": record["inhos_no"]})[0]
        diags = [d.strip() for d in re.split("[，,]", record["diag_list"] or "null") if d.strip()]
        output = QcRuleEngine(self.session).run_rules(record["inhos_no"], patient["sex"], diags)
        findings = []
        for finding in output["findings"]:
            row = {k: v for k, v in finding.items() if v is not None and (k != "sources" or v)}
            row["passed"] = False
            findings.append(row)
        passed = not findings
        trace = dict(ontologyVersion=ReleaseService(self.session).current_tag() or "未发布", rulesCited=output["rulesCited"],
            axiomsCited=output["axiomsCited"], conceptsInvolved=["EMR_RECORD", "DIAGNOSIS", "PROCEDURE", "LAB_REPORT", "CHECK_REPORT", "MEDICAL_ORDER"])
        prompt = f"病案 {record_id}（患者 {record['patient_name']}，{record['record_type']}，主要诊断：{record['diag_main']}，全部诊断：{record['diag_list']}）内涵质控发现 {len(findings)} 项问题：\n"
        prompt += "".join(f"- [{f['ruleCode']}] {f['evidence']}\n" for f in findings) if findings else "未发现逻辑矛盾。\n"
        answer = DeepSeekClient(self.session).chat("QC_REVIEW", "你是医院病案质控专家。基于质控发现输出质控意见：一、总体结论（通过/不通过）；二、问题清单的临床风险解读；三、整改建议（给书写医生）。专业简洁，300字以内。", prompt)
        summary = answer if answer is not None else "未发现内涵逻辑矛盾，质控通过。" if passed else f"质控不通过，发现 {len(findings)} 项逻辑矛盾：{'；'.join(f['evidence'] for f in findings)}。请书写医生核实整改。"
        dumps = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        try:
            BaseDAO(self.session, QcResult).insert(QcResult(record_id=record_id, inhos_no=record["inhos_no"], record_type=record["record_type"],
                pass_flag=int(passed), findings_json=dumps(findings), trace_json=dumps(trace), llm_used=int(answer is not None), llm_summary=summary, created_at=datetime.now()))
        except Exception as exc:
            raise RuntimeError("质控结果落库失败: " + str(exc)) from exc
        with self.ds.jdbc("DS_EMR").begin() as conn:
            conn.execute(text("UPDATE emr_record SET qc_status=:status WHERE record_id=:id"), {"status": "通过" if passed else "不通过", "id": record_id})
        return {"recordId": record_id, "pass": passed, "findings": findings, "trace": trace, "llmSummary": summary, "llmUsed": answer is not None}

    def check_all(self):
        details = []
        for r in self.records():
            one = self.check(r["record_id"])
            details.append({"recordId": r["record_id"], "patient": r["patient_name"], "pass": one["pass"], "findingCount": len(one["findings"])})
        passed = sum(r["pass"] for r in details)
        return {"total": len(details), "pass": passed, "fail": len(details)-passed, "details": details}

    def latest_result(self, id):
        return BaseDAO(self.session, QcResult).select_one(QcResult.record_id == id, order=(QcResult.id.desc(),))


class AlertService:
    def __init__(self, session):
        self.session = session

    def detect(self):
        ds, links = DatasourceService(self.session), LinkService(self.session)
        abnormals = ds.query("DS_LIS", "SELECT r.report_id,r.patient_no,r.item_code,r.report_time,a.item_name FROM lab_report r JOIN lab_apply a ON r.apply_id=a.apply_id WHERE r.result_status='A'")
        created, handled = [], 0
        for ab in abnormals:
            params = {"id": ab["patient_no"]}
            records = ds.query("DS_EMR", "SELECT diag_list FROM emr_record WHERE inhos_no=:id", params)
            diag_cover = any(k in (r["diag_list"] or "") for r in records for k in ("感染", "肺炎", "脓毒", "炎"))
            drug_cover = ds.query("DS_HIS", "SELECT COUNT(*) AS n FROM medical_order WHERE inhos_no=:id AND order_status='1' AND item_code IN ('D006','D011')", params)[0]["n"]
            if diag_cover or drug_cover:
                handled += 1
                continue
            ref = "ALERT-" + ab["report_id"]
            if links.get_by_ref_no(ref):
                continue
            patient = ds.query("DS_HIS", "SELECT patient_name,dept,ward FROM inpatient WHERE inhos_no=:id", params)[0]
            payload = dict(patient=patient["patient_name"], inhos_no=ab["patient_no"], dept=patient["dept"], item=ab["item_name"],
                report_id=ab["report_id"], report_time=timestamp(ab["report_time"]), basis="RULE-QC-003/AX-004", suggestion=f"请 {patient['dept']} 立即核实患者状态并补录诊断或处置医嘱")
            alert = links.insert(LinkNode(node_type="ALERT", ref_no=ref, title=f"危急值预警：{patient['patient_name']} {ab['item_name']} 检验结果异常未处置",
                concept_code="LAB_REPORT", status="待处置", occurred_at=datetime.now(), payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
            created.append(dict(refNo=ref, title=alert.title))
        return dict(abnormalReports=len(abnormals), handled=handled, createdCount=len(created), created=created)
