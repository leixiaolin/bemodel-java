from collections import Counter, defaultdict
from datetime import datetime
import json
import time
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.core.page_result import page_result
from bemodel.core.result import to_camel_dict
from bemodel.datasource.entities import Mapping, PhysicalTable, PhysicalColumn
from bemodel.datasource.services import DatasourceService
from bemodel.ontology.entities import Concept
from bemodel.link.entities import LinkNode
from .entities import GovRule, GovIssue, GovScan


class GovService:
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)

    def dao(self, model):
        return BaseDAO(self.session, model)

    def latest_scan(self):
        return self.dao(GovScan).select_one(order=(GovScan.id.desc(),))

    def issue(self, rule, ds, table, count, sample):
        return GovIssue(rule_code=rule.rule_code, rule_name=rule.rule_name, rule_type=rule.rule_type,
            severity=rule.severity, concept_code=rule.concept_code, ds_code=ds, table_name=table,
            hit_count=count, sample_json=json.dumps(to_camel_dict(sample), ensure_ascii=False, separators=(",", ":")))

    def probe(self, rule):
        e = {}
        try:
            e = json.loads(rule.expr_json)
            ds, table = e.get("ds"), e.get("table")
            query = lambda sql, params=None: self.ds.query(ds, sql, params)
            match rule.rule_type:
                case "PK_UNIQUE":
                    col = e["column"]
                    rows = query(f"SELECT {col} AS value,COUNT(*) AS cnt FROM {table} GROUP BY {col} HAVING COUNT(*)>1 LIMIT 5")
                    return [self.issue(rule, ds, table, len(rows), rows)] if rows else []
                case "NOT_NULL":
                    condition = " OR ".join(c + " IS NULL" for c in e["columns"])
                    count = query(f"SELECT COUNT(*) AS n FROM {table} WHERE {condition}")[0]["n"]
                    return [self.issue(rule, ds, table, count, query(f"SELECT * FROM {table} WHERE {condition} LIMIT 5"))] if count else []
                case "DICT_CONSISTENT":
                    col, dc, dt = e["column"], e["dictColumn"], e["dictTable"]
                    params, conditions = {}, []
                    for i, (key, value) in enumerate(e.get("dictFilter", {}).items()):
                        conditions.append(f" AND {key}=:p{i}")
                        params[f"p{i}"] = str(value)
                    dictionary = {str(r[dc]) if r[dc] is not None else "null" for r in self.ds.query(e["dictDs"], f"SELECT DISTINCT {dc} FROM {dt} WHERE 1=1" + "".join(conditions), params)}
                    rows = query(f"SELECT {col} AS value, COUNT(*) AS cnt FROM {table} GROUP BY {col}")
                    outliers = [{"value": str(r["value"]) if r["value"] is not None else "null", "cnt": r["cnt"], "note": f"字典({dt}.{dc})中无此值"}
                        for r in rows if (str(r["value"]) if r["value"] is not None else "null") not in dictionary]
                    return [self.issue(rule, ds, table, sum(r["cnt"] for r in outliers), outliers[:5])] if outliers else []
                case "REF_INTACT":
                    col, rc, rt = e["column"], e["refColumn"], e["refTable"]
                    keys = {str(r[rc]) for r in self.ds.query(e["refDs"], f"SELECT {rc} FROM {rt}")}
                    orphans = [str(r["k"]) for r in query(f"SELECT {col} AS k FROM {table} WHERE {col} IS NOT NULL") if str(r["k"]) not in keys]
                    return [self.issue(rule, ds, table, len(orphans), [{"orphanKey": k, "note": f"在 {rt} 中无对应记录"} for k in orphans[:5]])] if orphans else []
                case "STOCK_BALANCE":
                    key, quantity = e["keyColumn"], e["qtyColumn"]
                    stock = {str(r["k"]): int(r["q"] or 0) for r in query(f"SELECT {key} AS k,{quantity} AS q FROM {e['stockTable']}")}
                    sums = [{str(r["k"]): int(r["q"] or 0) for r in query(f"SELECT {key} AS k,SUM({quantity}) AS q FROM {e[t]} GROUP BY {key}")} for t in ("inTable", "outTable")]
                    bad = [{"drug": k, "账面库存": v, "应为(Σ入-Σ出)": sums[0].get(k, 0)-sums[1].get(k, 0)} for k, v in stock.items() if v != sums[0].get(k, 0)-sums[1].get(k, 0)]
                    return [self.issue(rule, ds, e["stockTable"], len(bad), bad[:5])] if bad else []
                case _:
                    return []
        except Exception as exc:
            return [self.issue(rule, e.get("ds", "-"), e.get("table", "-"), 1, [{"probeError": str(exc)}])]

    def scan(self):
        started = time.monotonic()
        rules = self.dao(GovRule).select_list(GovRule.status == "PUBLISHED")
        passed, total, issues = 0, 0, []
        for rule in rules:
            weight = {"高": 3, "中": 2, "低": 1}.get(rule.severity, 1)
            total += weight
            found = self.probe(rule)
            if not found:
                passed += weight
            issues.extend(found)
        duration = int((time.monotonic()-started)*1000)
        score = int(100*passed/total + .5) if total else 100
        scan = self.dao(GovScan).insert(GovScan(scan_time=datetime.now(), duration_ms=duration, rule_count=len(rules), issue_count=len(issues), quality_score=score))
        for issue in issues:
            issue.scan_id, issue.status = scan.id, "未处理"
            self.dao(GovIssue).insert(issue)
        return dict(scanId=scan.id, durationMs=duration, ruleCount=len(rules), issueCount=len(issues), qualityScore=score)

    def overview(self):
        count = self.dao(PhysicalColumn).select_count()
        mapped = len({(m.ds_code, m.table_name, m.column_name) for m in self.dao(Mapping).select_list()})
        latest = self.latest_scan()
        return dict(tableCount=self.dao(PhysicalTable).select_count(), columnCount=count, mappedCount=mapped,
            coverage=int(1000*mapped/count + .5)/10 if count else 0, qualityScore=latest.quality_score if latest else None,
            openIssues=self.dao(GovIssue).select_count(GovIssue.scan_id == latest.id, GovIssue.status == "未处理") if latest else 0,
            lastScan=latest)

    def tables(self):
        tables, columns, mappings = (self.dao(m).select_list() for m in (PhysicalTable, PhysicalColumn, Mapping))
        concepts = {c.code: c for c in self.dao(Concept).select_list()}
        counts = Counter((c.ds_code, c.table_name) for c in columns)
        mapped, domains, issues, worst = defaultdict(set), {}, Counter(), {}
        for m in mappings:
            key = (m.ds_code, m.table_name)
            mapped[key].add(m.column_name)
            if m.concept_code in concepts:
                domains.setdefault(key, concepts[m.concept_code].domain_code)
        latest = self.latest_scan()
        if latest:
            for issue in self.dao(GovIssue).select_list(GovIssue.scan_id == latest.id, GovIssue.status == "未处理"):
                key = (issue.ds_code, issue.table_name)
                issues[key] += 1
                if issue.severity == "高" or key not in worst:
                    worst[key] = issue.severity
        result = []
        for t in tables:
            key = (t.ds_code, t.table_name)
            total, covered = counts[key], len(mapped[key])
            rows = self.ds.query(t.ds_code, "SELECT COUNT(*) AS n FROM `" + t.table_name.replace("`", "``") + "`")[0]["n"]
            result.append(dict(dsCode=t.ds_code, tableName=t.table_name, tableComment=t.table_comment,
                rowCount=rows or 0, colCount=total, mappedCount=covered, coverage=int(1000*covered/total+.5)/10 if total else 0,
                domain=domains.get(key, "未认领"), issueCount=issues[key], health="优" if key not in worst else "差" if worst[key] == "高" else "良"))
        return sorted(result, key=lambda r: -r["issueCount"])

    def issues(self, page, size):
        latest = self.latest_scan()
        return self.dao(GovIssue).page(GovIssue.scan_id == latest.id, page=page, size=size, order=(GovIssue.id,)) if latest else page_result([], 0, page, size)

    def resolve_issue(self, id):
        self.dao(GovIssue).update_by_id(dict(id=id, status="已处理"))

    def issue_to_ticket(self, id):
        issue = self.dao(GovIssue).select_by_id(id)
        if issue is None:
            raise BizException("治理问题不存在: " + str(id))
        ref = "T-GOV-" + issue.rule_code
        existing = self.dao(LinkNode).select_one(LinkNode.ref_no == ref)
        if existing:
            return dict(ticketId=existing.id, refNo=ref, reused=True)
        ticket = LinkNode(node_type="TICKET", ref_no=ref, title=f"数据治理发现：{issue.rule_name}（{issue.ds_code}.{issue.table_name} 命中 {issue.hit_count} 行）",
            status="待处理", occurred_at=datetime.now(), concept_code=issue.concept_code)
        if issue.rule_code == "GOV-004":
            ticket.concept_code = "FEE_DETAIL"
            rows = self.ds.query("DS_HIS", "SELECT f.inhos_no,i.patient_name FROM fee_detail f JOIN medical_order o ON f.order_id=o.order_id JOIN inpatient i ON i.inhos_no=f.inhos_no WHERE o.order_status='2' AND f.fee_status='1' LIMIT 1")
            if rows:
                ticket.payload = json.dumps({"inhos_no": rows[0]["inhos_no"], "patient": rows[0]["patient_name"]}, ensure_ascii=False, separators=(",", ":"))
        self.dao(LinkNode).insert(ticket)
        return dict(ticketId=ticket.id, refNo=ref, reused=False)
