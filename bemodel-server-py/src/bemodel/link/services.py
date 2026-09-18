from collections import defaultdict, deque
from datetime import datetime
import json
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.core.result import to_camel_dict
from bemodel.datasource.services import DatasourceService
from .entities import LinkNode, LinkRel


class LinkService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, LinkNode)

    @staticmethod
    def conditions(node_type, concept):
        return ([LinkNode.node_type == node_type] if node_type and node_type.strip() else []) + ([LinkNode.concept_code == concept] if concept and concept.strip() else [])

    def list(self, node_type=None, concept=None):
        return self.select_list(*self.conditions(node_type, concept), order=(LinkNode.occurred_at.desc(),))

    def get_by_ref_no(self, ref):
        return self.select_one(LinkNode.ref_no == ref)

    def chain_by_concept(self, concept):
        groups = defaultdict(list)
        for row in self.list(concept=concept):
            groups[row.node_type].append(row)
        return dict(sorted(groups.items()))

    def add_rel(self, from_ref, to_ref, rel_type=None, remark=None):
        if not from_ref or not from_ref.strip() or not to_ref or not to_ref.strip():
            raise BizException("边的两端单号不能为空")
        if from_ref == to_ref:
            raise BizException("不允许节点关联自身: " + from_ref)
        if self.get_by_ref_no(from_ref) is None:
            raise BizException("上游节点不存在: " + from_ref)
        if self.get_by_ref_no(to_ref) is None:
            raise BizException("下游节点不存在: " + to_ref)
        rel_type = rel_type if rel_type and rel_type.strip() else "RELATES"
        dao = BaseDAO(self.session, LinkRel)
        conditions = (LinkRel.from_ref_no == from_ref, LinkRel.to_ref_no == to_ref, LinkRel.rel_type == rel_type)
        existing = dao.select_one(*conditions)
        if existing:
            return existing
        try:
            with self.session.begin_nested():
                row = LinkRel(from_ref_no=from_ref, to_ref_no=to_ref, rel_type=rel_type, remark=remark)
                self.session.add(row)
                self.session.flush()
            if not self.session.info.get("transaction_depth"):
                self.session.commit()
            return row
        except IntegrityError:
            existing = dao.select_one(*conditions)
            if existing is None:
                raise
            return existing

    def rels_of(self, ref):
        return BaseDAO(self.session, LinkRel).select_list(or_(LinkRel.from_ref_no == ref, LinkRel.to_ref_no == ref))

    def rels_by_concept(self, concept):
        refs = [r.ref_no for r in self.list(concept=concept)]
        return BaseDAO(self.session, LinkRel).select_list(or_(LinkRel.from_ref_no.in_(refs), LinkRel.to_ref_no.in_(refs))) if refs else []

    def trace(self, ref):
        root = self.get_by_ref_no(ref)
        if root is None:
            raise BizException("链路节点不存在: " + ref)
        visited, seen_edges, edges, queue = {ref}, set(), [], deque([ref])
        for depth in range(6):
            for _ in range(len(queue)):
                current = queue.popleft()
                for rel in self.rels_of(current):
                    if rel.id not in seen_edges:
                        seen_edges.add(rel.id)
                        edges.append(rel)
                    other = rel.to_ref_no if rel.from_ref_no == current else rel.from_ref_no
                    if other not in visited:
                        visited.add(other)
                        queue.append(other)
            if not queue:
                break
        return {"root": ref, "nodes": [root] + self.select_list(LinkNode.ref_no.in_(visited - {ref})), "edges": edges}

    def auto_ticket(self):
        rows = DatasourceService(self.session).query("DS_HIS", "SELECT f.inhos_no,i.patient_name,COUNT(*) AS cnt,SUM(f.amount) AS amt,MIN(f.charge_time) AS first_at FROM fee_detail f JOIN medical_order o ON f.order_id=o.order_id JOIN inpatient i ON i.inhos_no=f.inhos_no WHERE o.order_status='2' AND f.fee_status='1' GROUP BY f.inhos_no,i.patient_name")
        tickets, created = self.select_list(LinkNode.node_type == "TICKET"), []
        seq = len(tickets)
        for row in rows:
            if any(t.payload and row["inhos_no"] in t.payload for t in tickets):
                continue
            seq += 1
            ticket = self.insert(LinkNode(node_type="TICKET", ref_no=f"T-AUTO-{datetime.now():%Y%m%d}-{seq:03d}",
                title=f"系统预警：患者{row['patient_name']}存在{row['cnt']}笔取消未退费费用", concept_code="FEE_DETAIL", status="待处理", occurred_at=datetime.now(),
                payload=json.dumps(to_camel_dict(dict(patient=row["patient_name"], inhos_no=row["inhos_no"], fee_count=row["cnt"], amount=row["amt"], source="指标监控自动检测（取消未退费笔数告警）")), ensure_ascii=False, separators=(",", ":"))))
            created.append(dict(refNo=ticket.ref_no, title=ticket.title))
        return dict(scannedPatients=len(rows), createdCount=len(created), created=created)
