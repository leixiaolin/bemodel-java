import json
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from bemodel.core.base_dao import BaseDAO
from bemodel.core.exceptions import BizException
from bemodel.datasource.services import DatasourceService, SchemaScanService
from bemodel.modeling.entities import Axiom
from bemodel.ontology.entities import Disjoint, Relation
from bemodel.ontology.services import DisjointService

FRESHNESS = [
    ("DS_HIS", "inpatient", 41), ("DS_PHARMACY", "dispense_record", 1),
    ("DS_OPD", "opd_reg", 25), ("DS_EMR", "emr_record", 1), ("DS_PACS", "exam_report", 1),
    ("DS_NURSE", "nurse_exec", 1), ("DS_PHARMACY", "drug_dict", 12), ("DS_PHARMACY", "presc_review", 1),
    ("DS_NURSE", "vital_sign", 1), ("DS_EMR", "drg_group", 1), ("DS_EMR", "followup", 1),
    ("DS_MATERIAL", "material_out", 1), ("DS_HIS", "staff", 17),
]


def decode(value):
    for key, converter in [("$decimal", Decimal), ("$datetime", datetime.fromisoformat), ("$date", date.fromisoformat)]:
        if key in value:
            return converter(value[key])
    return value


logger = logging.getLogger(__name__)


class DataSeeder:
    """Native Python loader for the fixed Java demo scenario, with identical freshness gates.

    The fixed scenario is stored as a checked-in data resource rather than repeating
    procedural string/array construction. No Java process is needed at runtime.
    """
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)
        self._usable, self._blocked = set(), set()

    def usable(self, code):
        """演示库生命周期过滤：不存在/已失效/已删除的数据源跳过种子校验与补种，只告警，不阻断启动。"""
        if code not in self._usable and code not in self._blocked:
            try:
                self.ds.require(code)
                self._usable.add(code)
            except BizException:
                self._blocked.add(code)
                logger.warning("演示种子跳过不可用数据源（不存在/已失效/已删除）: %s", code)
        return code in self._usable

    def seed_structured_axioms(self):
        disjoints = DisjointService(self.session)
        for axiom in BaseDAO(self.session, Axiom).select_list(Axiom.axiom_type == "互斥"):
            a, b = disjoints.resolve_concept_code(axiom.subject), disjoints.resolve_concept_code(axiom.object)
            if a is None or b is None or a == b:
                continue
            a, b = sorted([a, b])
            if not disjoints.select_count(Disjoint.concept_a_code == a, Disjoint.concept_b_code == b):
                disjoints.insert(Disjoint(concept_a_code=a, concept_b_code=b, definition=axiom.axiom_code + "：" + (axiom.description or "null"), status="PUBLISHED"))
        dao = BaseDAO(self.session, Relation)
        part = dao.select_one(Relation.from_concept == "VITAL_SIGN", Relation.to_concept == "EMR_RECORD", Relation.relation_name == "属于")
        if part:
            part.is_transitive = 1
            dao.update_by_id(part)
        else:
            dao.insert(Relation(from_concept="VITAL_SIGN", to_concept="EMR_RECORD", relation_name="属于", description="partOf 公理示例：体征记录是病案的组成部分，「属于」沿组合链传递", is_transitive=1))
        inverse = dao.select_one(Relation.from_concept == "DEPT", Relation.to_concept == "STAFF", Relation.relation_name == "包含成员")
        if inverse is None:
            dao.insert(Relation(from_concept="DEPT", to_concept="STAFF", relation_name="包含成员", description="inverse_of 公理示例：与「工作于」互为逆关系", inverse_of="工作于"))
        for source, target, name, inverse_name in [("STAFF", "DEPT", "工作于", "包含成员"), ("DEPT", "STAFF", "包含成员", "工作于")]:
            for row in dao.select_list(Relation.from_concept == source, Relation.to_concept == target, Relation.relation_name == name):
                row.inverse_of = inverse_name
                dao.update_by_id(row)

    def run(self):
        self.seed_structured_axioms()
        # 不可用数据源不参与新鲜度校验（视为无需补种），尊重手动失效/删除的生命周期决策
        gates = [spec for spec in FRESHNESS if self.usable(spec[0])]
        counts = [self.ds.query(ds, f"SELECT COUNT(*) AS n FROM `{table}`")[0]["n"] for ds, table, minimum in gates]
        if all(count >= spec[2] for count, spec in zip(counts, gates)):
            return False
        resource = Path(__file__).resolve().parents[1] / "resources/seed/demo.json"
        fixture = json.loads(resource.read_text(encoding="utf-8"), object_hook=decode)
        for ds, tables in fixture["datasources"].items():
            if not self.usable(ds):
                continue
            # Product DB writes are independent of the platform transaction, as in Java.
            with self.ds.jdbc(ds).connect() as conn:
                for table in tables:
                    conn.execute(text(f"DELETE FROM `{table}`"))
                    conn.commit()
                for table, rows in tables.items():
                    for row in rows:
                        columns = list(row)
                        sql = f"INSERT INTO `{table}` (" + ",".join(f"`{c}`" for c in columns) + ") VALUES (" + ",".join(f":v{i}" for i in range(len(columns))) + ")"
                        conn.execute(text(sql), {f"v{i}": row[c] for i, c in enumerate(columns)})
                        conn.commit()
        for ds in fixture["datasources"]:
            if self.usable(ds):
                SchemaScanService(self.session).scan(ds)
        return True
