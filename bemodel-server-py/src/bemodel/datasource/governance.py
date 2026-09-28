from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
import socket
import logging
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import transactional
from bemodel.core.exceptions import BizException
from bemodel.core.result import to_camel_dict
from bemodel.llm.services import DeepSeekClient
from bemodel.modeling.entities import Action, Rule
from bemodel.modeling.services import ReleaseService
from bemodel.ontology.entities import Attribute, Concept, Domain, Metric, Relation, Term
from .entities import Mapping, PhysicalColumn, PhysicalTable
from .governance_entities import OntologyAnalysisTask, OntologyChangeItem, OntologyChangeSet

CHANGE_MUTABLE = {"DRAFT", "REVIEWED", "ADOPTED"}
ITEM_TYPES = {"CONCEPT", "ATTRIBUTE", "TERM", "RELATION", "RULE", "ACTION", "METRIC", "MAPPING"}
OPERATIONS = {"REUSE_EXISTING", "CREATE", "EXTEND", "CONFLICT", "INSUFFICIENT_EVIDENCE"}
REVIEW_STATES = {"PENDING", "ACCEPTED", "REJECTED", "NEEDS_INPUT"}
SENSITIVE = re.compile(
    r"(^|_)(name|patient_name|person_name|id_card|identity|phone|mobile|address|email|病历|姓名|证件|身份证|电话|手机|地址)(?=$|[^A-Za-z0-9])",
    re.IGNORECASE,
)
CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_value(raw, default):
    try:
        value = json.loads(raw) if raw else default
        return value
    except (TypeError, ValueError):
        return default


def contains_sql_key(value):
    if isinstance(value, dict):
        return any("sql" in str(key).lower() or contains_sql_key(child) for key, child in value.items())
    if isinstance(value, list):
        return any(contains_sql_key(child) for child in value)
    return False


def schema_fingerprint(tables, columns):
    payload = {
        "tables": sorted((t.table_name or "", t.table_comment or "") for t in tables),
        "columns": sorted((c.table_name or "", c.column_name or "", (c.data_type or "").lower(),
                           c.column_comment or "", int(c.is_pk or 0), int(c.ordinal_position or 0),
                           c.referenced_table or "", c.referenced_column or "") for c in columns),
    }
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def safe_code(value, fallback):
    code = re.sub(r"[^A-Z0-9_]+", "_", str(value or "").upper()).strip("_")[:64]
    if not code or not code[0].isalpha():
        code = fallback
    return code


def canonical_type(db_type):
    value = (db_type or "").lower()
    if any(part in value for part in ("int", "decimal", "numeric", "number", "float", "double")):
        return "NUMBER"
    if any(part in value for part in ("date", "time", "year")):
        return "DATE"
    if "bool" in value or "bit" in value:
        return "BOOLEAN"
    return "STRING"


class OntologyAnalysisService:
    def __init__(self, session):
        self.session = session
        self.tasks = BaseDAO(session, OntologyAnalysisTask)
        self.sets = BaseDAO(session, OntologyChangeSet)
        self.items = BaseDAO(session, OntologyChangeItem)

    def current_baseline(self, ds_code):
        tables = BaseDAO(self.session, PhysicalTable).select_list(PhysicalTable.ds_code == ds_code)
        columns = BaseDAO(self.session, PhysicalColumn).select_list(PhysicalColumn.ds_code == ds_code)
        if not tables:
            raise BizException("未找到扫描结果，请先扫描数据源: " + ds_code)
        return schema_fingerprint(tables, columns), ReleaseService(self.session).current_tag() or "未发布"

    def enqueue(self, ds_code, created_by=None, force=False, ai_only=False, scan_diff=None):
        from .services import DatasourceService
        DatasourceService(self.session).require(ds_code)
        fingerprint, version = self.current_baseline(ds_code)
        if not force:
            existing = self.tasks.select_one(
                OntologyAnalysisTask.ds_code == ds_code,
                OntologyAnalysisTask.scan_fingerprint == fingerprint,
                OntologyAnalysisTask.ontology_version == version,
                OntologyAnalysisTask.status.in_(("PENDING", "RUNNING", "SUCCEEDED", "PARTIAL")),
                order=(OntologyAnalysisTask.id.desc(),),
            )
            if existing:
                return existing
        dedupe_key = None if force else hashlib.sha256(f"{ds_code}|{fingerprint}|{version}".encode()).hexdigest()
        try:
            task = self.tasks.insert(OntologyAnalysisTask(
                ds_code=ds_code, status="PENDING", progress=0, scan_fingerprint=fingerprint,
                ontology_version=version, model=settings.deepseek_model,
                analysis_mode="AI_ONLY" if ai_only else "FULL", dedupe_key=dedupe_key,
                scan_diff_json=stable_json(scan_diff) if scan_diff else None, created_by=created_by,
            ))
        except IntegrityError:
            self.session.rollback()
            task = self.tasks.select_one(OntologyAnalysisTask.dedupe_key == dedupe_key)
            if task is None:
                raise
        return task

    def mark_stale(self, ds_code, current_fingerprint):
        rows = self.sets.select_list(OntologyChangeSet.ds_code == ds_code,
                                    OntologyChangeSet.status.in_(tuple(CHANGE_MUTABLE)),
                                    OntologyChangeSet.scan_fingerprint != current_fingerprint)
        for row in rows:
            row.status = "STALE"
            row.updated_at = datetime.now()
            self.sets.update_by_id(row)

    def cancel_for_datasource(self, ds_code, reason="数据源已失效"):
        now = datetime.now()
        self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.ds_code == ds_code,
            OntologyAnalysisTask.status.in_(("PENDING", "RUNNING")),
        ).values(status="CANCELLED", error_message=reason, worker_id=None, locked_at=None,
                 dedupe_key=None, finished_at=now))
        self.session.execute(update(OntologyChangeSet).where(
            OntologyChangeSet.ds_code == ds_code,
            OntologyChangeSet.status.in_(tuple(CHANGE_MUTABLE)),
        ).values(status="STALE", updated_at=now))
        self.session.commit()

    def latest(self, ds_code):
        task = self.tasks.select_one(OntologyAnalysisTask.ds_code == ds_code,
                                     order=(OntologyAnalysisTask.id.desc(),))
        if task is None:
            return None
        result = to_camel_dict(task)
        result.pop("workerId", None)
        result.pop("lockedAt", None)
        result.pop("dedupeKey", None)
        result.pop("scanDiffJson", None)
        if task.change_set_id:
            change = self.sets.select_by_id(task.change_set_id)
            result["changeSet"] = self.change_set_summary(change)
        return result

    def change_set_summary(self, change):
        if change is None:
            return None
        value = to_camel_dict(change)
        value["summary"] = json_value(value.pop("summaryJson", None), {})
        return value

    def detail(self, change_set_id):
        change = self.sets.select_by_id(change_set_id)
        if change is None:
            raise BizException("变更集不存在: " + str(change_set_id))
        items = self.items.select_list(OntologyChangeItem.change_set_id == change_set_id,
                                       order=(OntologyChangeItem.source_table, OntologyChangeItem.item_type, OntologyChangeItem.id))
        result = self.change_set_summary(change)
        result["items"] = [self.item_dto(item) for item in items]
        return result

    @staticmethod
    def item_dto(item):
        value = to_camel_dict(item)
        value["payload"] = json_value(value.pop("payloadJson", None), {})
        value["evidence"] = json_value(value.pop("evidenceJson", None), [])
        value["dependencies"] = json_value(value.pop("dependencyJson", None), [])
        value["resultRef"] = json_value(value.pop("resultRefJson", None), None)
        value["confidence"] = float(value.get("confidence") or 0)
        return value

    def claim_next(self, worker_id=None):
        worker_id = worker_id or socket.gethostname()
        now = datetime.now()
        stale = now - timedelta(seconds=max(30, settings.ontology_analysis_lock_seconds))
        self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.status == "RUNNING", OntologyAnalysisTask.locked_at < stale,
            OntologyAnalysisTask.attempt_count < settings.ontology_analysis_max_attempts,
        ).values(status="PENDING", worker_id=None, locked_at=None, error_message="任务锁超时，已重新排队"))
        self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.status == "RUNNING", OntologyAnalysisTask.locked_at < stale,
            OntologyAnalysisTask.attempt_count >= settings.ontology_analysis_max_attempts,
        ).values(status="FAILED", worker_id=None, locked_at=None, finished_at=now,
                 error_message="任务超过最大重试次数", dedupe_key=None))
        self.session.commit()
        candidate = self.session.scalar(select(OntologyAnalysisTask.id).where(
            OntologyAnalysisTask.status == "PENDING",
            OntologyAnalysisTask.attempt_count < settings.ontology_analysis_max_attempts,
        ).order_by(OntologyAnalysisTask.id).limit(1))
        if candidate is None:
            return None
        changed = self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.id == candidate, OntologyAnalysisTask.status == "PENDING"
        ).values(status="RUNNING", progress=1, worker_id=worker_id, locked_at=now,
                 started_at=now, attempt_count=OntologyAnalysisTask.attempt_count + 1))
        self.session.commit()
        return self.tasks.select_by_id(candidate) if changed.rowcount == 1 else None

    def run_next(self, worker_id=None):
        task = self.claim_next(worker_id)
        if task is None:
            return None
        self.run_task(task.id)
        return task.id

    def run_task(self, task_id):
        task = self.tasks.select_by_id(task_id)
        if task is None or task.status not in {"PENDING", "RUNNING"}:
            return
        if task.status == "PENDING":
            task.status = "RUNNING"
            task.started_at = task.started_at or datetime.now()
            task.locked_at = datetime.now()
            task.attempt_count = (task.attempt_count or 0) + 1
            self.tasks.update_by_id(task)
        try:
            from .services import DatasourceService
            DatasourceService(self.session).require(task.ds_code)
            fingerprint, version = self.current_baseline(task.ds_code)
            if fingerprint != task.scan_fingerprint or version != task.ontology_version:
                raise BizException("扫描结果或本体版本已变化，请重新分析")
            self.update_progress(task_id, 10)
            previous = self.previous_baseline_result(task) if task.analysis_mode == "AI_ONLY" else None
            if previous:
                suggestions, coverage, warnings = previous
            else:
                suggestions, coverage, warnings = self.deterministic_analysis(task.ds_code,
                    lambda: self.heartbeat(task_id))
            self.update_progress(task_id, 45)
            llm_suggestions, llm_error = self.ai_analysis(task.ds_code, suggestions,
                                                           lambda: self.heartbeat(task_id))
            self.heartbeat(task_id)
            suggestions = self.merge_suggestions(suggestions, llm_suggestions)
            self.update_progress(task_id, 75)
            scan_diff = json_value(task.scan_diff_json, {})
            if scan_diff:
                coverage["scanDiff"] = scan_diff
            with transactional(self.session):
                change = self.save_change_set(task, suggestions, coverage, warnings, llm_error)
                changed = self.session.execute(update(OntologyAnalysisTask).where(
                    OntologyAnalysisTask.id == task_id, OntologyAnalysisTask.status == "RUNNING"
                ).values(status="PARTIAL" if llm_error else "SUCCEEDED", progress=100,
                         change_set_id=change.id, error_message=llm_error, finished_at=datetime.now(),
                         worker_id=None, locked_at=None))
                if changed.rowcount != 1:
                    raise BizException("分析任务已取消")
        except Exception as exc:
            logging.getLogger(__name__).exception("数据源本体治理任务失败: task=%s", task_id)
            self.session.rollback()
            task = self.tasks.select_by_id(task_id)
            if task and task.status == "RUNNING":
                retry = (task.attempt_count or 0) < settings.ontology_analysis_max_attempts
                task.status = "PENDING" if retry else "FAILED"
                task.error_message = (str(exc)[:1024] if isinstance(exc, BizException)
                                      else "分析执行失败，请查看服务日志")
                task.finished_at = None if retry else datetime.now()
                if not retry:
                    task.dedupe_key = None
                task.worker_id = None
                task.locked_at = None
                self.tasks.update_by_id(task)

    def previous_baseline_result(self, task):
        previous = self.sets.select_one(
            OntologyChangeSet.ds_code == task.ds_code,
            OntologyChangeSet.scan_fingerprint == task.scan_fingerprint,
            OntologyChangeSet.ontology_version == task.ontology_version,
            OntologyChangeSet.task_id != task.id,
            order=(OntologyChangeSet.id.desc(),),
        )
        if previous is None:
            return None
        rows = self.items.select_list(OntologyChangeItem.change_set_id == previous.id)
        suggestions = []
        for row in rows:
            suggestions.append({"itemType": row.item_type, "operation": row.operation,
                "targetKey": row.target_key, "payload": json_value(row.payload_json, {}),
                "sourceTable": row.source_table, "sourceColumn": row.source_column,
                "confidence": float(row.confidence or 0), "riskLevel": row.risk_level,
                "evidence": json_value(row.evidence_json, []), "reason": row.reason or "",
                "dependencies": json_value(row.dependency_json, []),
                "missingInformation": row.missing_information})
        summary = json_value(previous.summary_json, {})
        warnings = list(summary.pop("warnings", []) or [])
        summary.pop("llmError", None)
        return suggestions, summary, warnings

    def heartbeat(self, task_id):
        changed = self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.id == task_id, OntologyAnalysisTask.status == "RUNNING"
        ).values(locked_at=datetime.now()))
        self.session.commit()
        if changed.rowcount != 1:
            raise BizException("分析任务已取消")

    def update_progress(self, task_id, progress):
        changed = self.session.execute(update(OntologyAnalysisTask).where(
            OntologyAnalysisTask.id == task_id, OntologyAnalysisTask.status == "RUNNING"
        ).values(progress=progress, locked_at=datetime.now()))
        self.session.commit()
        if changed.rowcount != 1:
            raise BizException("分析任务已取消")

    def deterministic_analysis(self, ds_code, heartbeat=None):
        tables = BaseDAO(self.session, PhysicalTable).select_list(PhysicalTable.ds_code == ds_code,
                                                                  order=(PhysicalTable.table_name,))
        columns = BaseDAO(self.session, PhysicalColumn).select_list(PhysicalColumn.ds_code == ds_code,
                                                                    order=(PhysicalColumn.table_name, PhysicalColumn.ordinal_position))
        concepts = BaseDAO(self.session, Concept).select_list(Concept.status == "PUBLISHED")
        attrs = BaseDAO(self.session, Attribute).select_list()
        mappings = BaseDAO(self.session, Mapping).select_list(Mapping.ds_code == ds_code)
        terms = BaseDAO(self.session, Term).select_list()
        domains = BaseDAO(self.session, Domain).select_list(order=(Domain.sort,))
        by_table = {}
        for column in columns:
            by_table.setdefault(column.table_name, []).append(column)
        physical = {(c.table_name, c.column_name) for c in columns}
        mapped = {(m.table_name, m.column_name) for m in mappings if (m.table_name, m.column_name) in physical}
        suggestions = []
        for mapping in mappings:
            if (mapping.table_name, mapping.column_name) not in physical:
                suggestions.append(self.suggestion("MAPPING", "CONFLICT",
                    f"{mapping.table_name}.{mapping.column_name}",
                    {"dsCode": ds_code, "tableName": mapping.table_name, "columnName": mapping.column_name,
                     "conceptCode": mapping.concept_code, "attrCode": mapping.attr_code},
                    mapping.table_name, mapping.column_name, 1.0, "HIGH",
                    ["映射引用的物理列已不在最新扫描快照中"], "Schema 漂移导致历史映射失效"))
        stats, warnings = self.collect_statistics(ds_code, by_table, heartbeat)
        for table in tables:
            table_cols = by_table.get(table.table_name, [])
            words = " ".join((table.table_name, table.table_comment or "")).lower()
            concept = next((c for c in concepts if c.code.lower() in words or c.name and c.name.lower() in words), None)
            if concept is None:
                concept = next((c for c in concepts if any(t.concept_code == c.code and t.term and t.term.lower() in words for t in terms)), None)
            concept_code = concept.code if concept else safe_code(table.table_name, "CONCEPT_" + str(table.id))
            if concept is None:
                domain_code = next((d.code for d in domains if d.code == "IMPORT"), domains[0].code if domains else "IMPORT")
                suggestions.append(self.suggestion("CONCEPT", "CREATE", concept_code,
                    {"code": concept_code, "name": table.table_comment or table.table_name,
                     "domainCode": domain_code, "definition": f"由数据源 {ds_code}.{table.table_name} 扫描发现，待业务确认"},
                    table.table_name, None, .72 if table.table_comment else .5, "MEDIUM",
                    [f"物理表 {table.table_name}", f"表注释：{table.table_comment or '无'}"], "扫描发现未匹配业务实体"))
            known_attrs = [a for a in attrs if a.concept_code == concept_code]
            for column in table_cols:
                if (table.table_name, column.column_name) in mapped:
                    continue
                attr = next((a for a in known_attrs if a.attr_code.lower() == column.column_name.lower()
                             or a.attr_name and column.column_comment and a.attr_name in column.column_comment), None)
                if attr:
                    physical_type = canonical_type(column.data_type)
                    ontology_type = canonical_type(attr.data_type)
                    if physical_type != ontology_type:
                        suggestions.append(self.suggestion("MAPPING", "CONFLICT",
                            f"{table.table_name}.{column.column_name}",
                            {"dsCode": ds_code, "tableName": table.table_name, "columnName": column.column_name,
                             "conceptCode": concept_code, "attrCode": attr.attr_code},
                            table.table_name, column.column_name, 1.0, "HIGH",
                            [f"物理类型：{physical_type}", f"本体属性类型：{ontology_type}"],
                            "字段语义匹配但数据类型不兼容"))
                        continue
                    suggestions.append(self.suggestion("MAPPING", "REUSE_EXISTING",
                        f"{table.table_name}.{column.column_name}",
                        {"dsCode": ds_code, "tableName": table.table_name, "columnName": column.column_name,
                         "conceptCode": concept_code, "attrCode": attr.attr_code, "confirmed": 0,
                         "source": "AI_GOVERNANCE"}, table.table_name, column.column_name, .9, "LOW",
                        ["字段名或注释命中已有属性"], "复用现有本体属性"))
                    continue
                attr_code = safe_code(column.column_name, "ATTR_" + str(column.id)).lower()
                dependencies = [] if concept else [f"CONCEPT:{concept_code}"]
                suggestions.append(self.suggestion("ATTRIBUTE", "EXTEND" if concept else "CREATE",
                    f"{concept_code}.{attr_code}",
                    {"conceptCode": concept_code, "attrCode": attr_code,
                     "attrName": column.column_comment or column.column_name,
                     "dataType": canonical_type(column.data_type), "isKey": int(column.is_pk or 0),
                     "definition": f"来源 {ds_code}.{table.table_name}.{column.column_name}"},
                    table.table_name, column.column_name, .78 if column.column_comment else .55, "MEDIUM",
                    [f"物理类型：{column.data_type}", f"主键：{bool(column.is_pk)}"],
                    "新增或扩充概念属性", dependencies))
                suggestions.append(self.suggestion("MAPPING", "CREATE", f"{table.table_name}.{column.column_name}",
                    {"dsCode": ds_code, "tableName": table.table_name, "columnName": column.column_name,
                     "conceptCode": concept_code, "attrCode": attr_code, "confirmed": 0,
                     "source": "AI_GOVERNANCE", "valueMap": stats.get((table.table_name, column.column_name), {}).get("valueMap")},
                    table.table_name, column.column_name, .7, "LOW", ["依赖建议属性"], "创建候选映射",
                    [f"ATTRIBUTE:{concept_code}.{attr_code}"]))
                if column.referenced_table:
                    target = next((c for c in concepts if c.code.lower() == column.referenced_table.lower()), None)
                    if target:
                        suggestions.append(self.suggestion("RELATION", "CREATE",
                            f"{concept_code}->{target.code}#关联",
                            {"fromConcept": concept_code, "toConcept": target.code, "relationName": "关联",
                             "description": f"来源外键 {table.table_name}.{column.column_name} -> {column.referenced_table}.{column.referenced_column}"},
                            table.table_name, column.column_name, .95, "LOW",
                            ["数据库外键约束"], "根据显式外键生成关系候选",
                            ([] if concept else [f"CONCEPT:{concept_code}"])))
            # A status column plus observed low-cardinality values is evidence for a non-executable action skeleton.
            for column in table_cols:
                info = stats.get((table.table_name, column.column_name), {})
                if "status" in column.column_name.lower() and len(info.get("values", [])) >= 2:
                    suggestions.append(self.suggestion("ACTION", "INSUFFICIENT_EVIDENCE", f"ACT_{concept_code}_{column.column_name.upper()}",
                        {"actionCode": f"ACT_{concept_code}_{column.column_name.upper()}"[:64],
                         "name": f"{table.table_comment or table.table_name}状态迁移（待确认）",
                         "conceptCode": concept_code, "fromStatus": None, "toStatus": None,
                         "triggerDesc": "根据扫描值域补充前置状态、目标状态和触发条件",
                         "description": "仅为候选骨架，不包含可执行逻辑"}, table.table_name, column.column_name,
                        .45, "HIGH", ["状态字段", "脱敏低基数值域"], "发现潜在状态机，但迁移方向证据不足",
                        [f"CONCEPT:{concept_code}"], "需业务人员补齐并确认状态迁移"))
        total = len(columns)
        coverage = {"tableCount": len(tables), "columnCount": total, "mappedColumnCount": len(mapped),
                    "mappingCoverage": round(len(mapped) / total, 4) if total else 0}
        return suggestions, coverage, warnings

    def collect_statistics(self, ds_code, by_table, heartbeat=None):
        from .services import DatasourceService
        result, warnings = {}, []
        budget = max(0, settings.ontology_stats_max_columns)
        for table_name, columns in by_table.items():
            for column in columns:
                if heartbeat:
                    heartbeat()
                if budget <= 0:
                    warnings.append("统计字段预算已用尽")
                    return result, warnings
                budget -= 1
                sensitive = bool(SENSITIVE.search(" ".join((column.column_name or "", column.column_comment or ""))))
                qt = "`" + table_name.replace("`", "``") + "`"
                qc = "`" + column.column_name.replace("`", "``") + "`"
                try:
                    timeout = max(1, settings.ontology_stats_timeout_seconds) * 1000
                    aggregates = DatasourceService(self.session).query(ds_code,
                        f"SELECT /*+ MAX_EXECUTION_TIME({timeout}) */ COUNT(*) totalCount, COUNT({qc}) nonNullCount, COUNT(DISTINCT {qc}) distinctCount"
                        + (f", MIN({qc}) minValue, MAX({qc}) maxValue" if canonical_type(column.data_type) == "NUMBER" else "")
                        + f" FROM {qt}")
                    info = dict(aggregates[0]) if aggregates else {}
                    info["sensitive"] = sensitive
                    if not sensitive and canonical_type(column.data_type) in {"STRING", "BOOLEAN"} and int(info.get("distinctCount") or 0) <= settings.ontology_stats_enum_limit:
                        rows = DatasourceService(self.session).query(ds_code,
                            f"SELECT /*+ MAX_EXECUTION_TIME({timeout}) */ {qc} value, COUNT(*) count FROM {qt} WHERE {qc} IS NOT NULL GROUP BY {qc} LIMIT {int(settings.ontology_stats_enum_limit) + 1}")
                        if len(rows) <= settings.ontology_stats_enum_limit:
                            values = [{"value": str(r["value"])[:128], "count": int(r["count"])} for r in rows]
                            info.update(values=values,
                                valueMap=stable_json({v["value"]: v["value"] for v in values}) if values else None)
                    result[(table_name, column.column_name)] = info
                except Exception as exc:
                    warnings.append(f"{table_name}.{column.column_name} 统计失败（{type(exc).__name__}）")
        return result, warnings

    @staticmethod
    def suggestion(item_type, operation, key, payload, table, column, confidence, risk, evidence, reason,
                   dependencies=None, missing=None):
        return {"itemType": item_type, "operation": operation, "targetKey": key, "payload": payload,
                "sourceTable": table, "sourceColumn": column, "confidence": confidence, "riskLevel": risk,
                "evidence": evidence, "reason": reason, "dependencies": dependencies or [],
                "missingInformation": missing}

    def ai_analysis(self, ds_code, deterministic, heartbeat=None):
        if not settings.deepseek_api_key.strip():
            return [], "API Key 未配置，已保留确定性分析结果"
        tables = BaseDAO(self.session, PhysicalTable).select_list(PhysicalTable.ds_code == ds_code,
                                                                  order=(PhysicalTable.table_name,))
        columns = BaseDAO(self.session, PhysicalColumn).select_list(PhysicalColumn.ds_code == ds_code,
                                                                    order=(PhysicalColumn.table_name, PhysicalColumn.ordinal_position))
        chunks = [tables[i:i + max(1, settings.ontology_analysis_chunk_tables)]
                  for i in range(0, len(tables), max(1, settings.ontology_analysis_chunk_tables))]
        output, errors = [], []
        allowed_columns = {(c.table_name, c.column_name) for c in columns}
        for chunk in chunks:
            if heartbeat:
                heartbeat()
            names = {t.table_name for t in chunk}
            schema = [{"table": t.table_name, "comment": t.table_comment or "",
                       "columns": [{"name": c.column_name, "type": c.data_type, "comment": c.column_comment or "",
                                    "primaryKey": bool(c.is_pk), "sensitive": bool(SENSITIVE.search(" ".join((c.column_name or "", c.column_comment or ""))))}
                                   for c in columns if c.table_name == t.table_name]} for t in chunk]
            prompt = stable_json({"datasource": ds_code, "schema": schema,
                "existingSuggestions": [s for s in deterministic if s["sourceTable"] in names],
                "requirements": "仅补充确定性分析遗漏。输出JSON数组；不得输出SQL；不得虚构表列。"})
            raw = DeepSeekClient(self.session).chat("DATASOURCE_ONTOLOGY_ANALYSIS",
                "你是医疗本体治理助手。只返回JSON数组。候选类型仅限CONCEPT/ATTRIBUTE/TERM/RELATION/RULE/ACTION/METRIC/MAPPING。", prompt)
            parsed = self.parse_ai(raw, names, allowed_columns)
            if parsed is None:
                errors.append("AI 分片返回无效结构")
            else:
                output.extend(parsed)
        return output, "; ".join(errors) or None

    def parse_ai(self, raw, allowed_tables, allowed_columns):
        if not raw:
            return None
        try:
            data = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        except (ValueError, TypeError):
            return None
        valid = []
        for row in data if isinstance(data, list) else []:
            if not isinstance(row, dict):
                continue
            kind, operation = str(row.get("itemType", "")).upper(), str(row.get("operation", "")).upper()
            table, column = row.get("sourceTable"), row.get("sourceColumn")
            payload = row.get("payload")
            if kind not in ITEM_TYPES or operation not in OPERATIONS or not isinstance(payload, dict):
                continue
            if table not in allowed_tables or column is not None and (table, column) not in allowed_columns:
                continue
            if contains_sql_key(payload) or len(stable_json(payload)) > 16384:
                continue
            key = str(row.get("targetKey") or "")[:256]
            if not key:
                continue
            try:
                confidence = max(0.0, min(1.0, float(row.get("confidence", .5))))
            except (TypeError, ValueError):
                continue
            raw_evidence = row.get("evidence")
            raw_dependencies = row.get("dependencies")
            evidence = [str(value)[:512] for value in (raw_evidence[:20] if isinstance(raw_evidence, list) else [])]
            missing = str(row.get("missingInformation") or "")[:1024] or None
            if kind in {"RULE", "ACTION", "METRIC"} and (confidence < .75 or len(evidence) < 2 or missing):
                operation = "INSUFFICIENT_EVIDENCE"
            valid.append(self.suggestion(kind, operation, key, payload, table, column, confidence,
                str(row.get("riskLevel", "MEDIUM")).upper() if str(row.get("riskLevel", "")).upper() in {"LOW", "MEDIUM", "HIGH"} else "MEDIUM",
                evidence, str(row.get("reason") or "")[:1024],
                [str(value)[:256] for value in (raw_dependencies[:20] if isinstance(raw_dependencies, list) else [])], missing))
        return valid

    @staticmethod
    def merge_suggestions(first, second):
        merged = {(s["itemType"], s["targetKey"]): s for s in first}
        for suggestion in second:
            key = suggestion["itemType"], suggestion["targetKey"]
            if key not in merged or suggestion["confidence"] > merged[key]["confidence"]:
                merged[key] = suggestion
        return list(merged.values())

    def save_change_set(self, task, suggestions, coverage, warnings, llm_error):
        with transactional(self.session):
            change = self.sets.insert(OntologyChangeSet(task_id=task.id, ds_code=task.ds_code,
                name=f"{task.ds_code} 本体治理分析 #{task.id}", status="DRAFT",
                scan_fingerprint=task.scan_fingerprint, ontology_version=task.ontology_version,
                suggestion_count=len(suggestions), high_risk_count=sum(s["riskLevel"] == "HIGH" for s in suggestions),
                summary_json=stable_json({**coverage, "warnings": warnings, "llmError": llm_error}),
                created_by=task.created_by))
            for suggestion in suggestions:
                self.items.insert(OntologyChangeItem(change_set_id=change.id,
                    item_type=suggestion["itemType"], operation=suggestion["operation"],
                    review_status="PENDING", target_key=suggestion["targetKey"],
                    payload_json=stable_json(suggestion["payload"]), evidence_json=stable_json(suggestion["evidence"]),
                    dependency_json=stable_json(suggestion["dependencies"]), confidence=Decimal(str(suggestion["confidence"])),
                    risk_level=suggestion["riskLevel"], reason=suggestion["reason"],
                    missing_information=suggestion["missingInformation"], source_table=suggestion["sourceTable"],
                    source_column=suggestion["sourceColumn"]))
            return change


class OntologyChangeSetService(OntologyAnalysisService):
    EDITABLE = {"payload", "reviewStatus", "reviewNote"}

    def update_item(self, change_set_id, item_id, body, reviewer=None):
        change = self.require_mutable(change_set_id)
        unknown = set(body) - self.EDITABLE
        if unknown:
            raise BizException("不允许编辑字段: " + ", ".join(sorted(unknown)))
        item = self.items.select_by_id(item_id)
        if item is None or item.change_set_id != change_set_id:
            raise BizException("变更建议不存在: " + str(item_id))
        if "reviewStatus" in body:
            status = str(body["reviewStatus"]).upper()
            if status not in REVIEW_STATES:
                raise BizException("审核状态不合法: " + status)
            if status == "ACCEPTED" and item.operation in {"CONFLICT", "INSUFFICIENT_EVIDENCE"}:
                raise BizException("冲突或证据不足建议不能直接采纳")
            item.review_status = status
        if "payload" in body:
            if not isinstance(body["payload"], dict):
                raise BizException("payload 必须为对象")
            self.validate_payload(item.item_type, body["payload"])
            item.payload_json = stable_json(body["payload"])
            if "reviewStatus" not in body:
                item.review_status = "PENDING"
        if "reviewNote" in body:
            item.review_note = str(body["reviewNote"] or "")[:1024] or None
        item.updated_at = datetime.now()
        self.items.update_by_id(item)
        change.reviewed_by = reviewer
        change.status = "REVIEWED"
        change.updated_at = datetime.now()
        self.sets.update_by_id(change)
        return self.item_dto(item)

    def adopt(self, change_set_id, item_ids, reviewer=None):
        change = self.require_mutable(change_set_id)
        selected = {int(value) for value in item_ids or []}
        items = self.items.select_list(OntologyChangeItem.change_set_id == change_set_id)
        by_ref = {f"{item.item_type}:{item.target_key}": item for item in items}
        queue = [item for item in items if item.id in selected]
        if not queue:
            raise BizException("请选择要采纳的建议")
        accepted = set()
        while queue:
            item = queue.pop()
            if item.id in accepted:
                continue
            if item.operation in {"CONFLICT", "INSUFFICIENT_EVIDENCE"}:
                raise BizException("冲突或证据不足建议不能直接采纳: " + item.target_key)
            accepted.add(item.id)
            for dep in json_value(item.dependency_json, []):
                dependency = by_ref.get(dep)
                if dependency:
                    queue.append(dependency)
                elif not self.existing_dependency(dep):
                    raise BizException("建议依赖不存在: " + dep)
        for item in items:
            if item.id in accepted:
                item.review_status = "ACCEPTED"
                self.items.update_by_id(item)
        change.status = "ADOPTED"
        change.reviewed_by = reviewer
        change.updated_at = datetime.now()
        self.sets.update_by_id(change)
        return {"acceptedIds": sorted(accepted), "acceptedCount": len(accepted)}

    def publish(self, change_set_id, actor=None):
        change = self.sets.select_by_id(change_set_id)
        if change is None:
            raise BizException("变更集不存在: " + str(change_set_id))
        if change.status == "PUBLISHED":
            return self.detail(change_set_id)
        if change.status not in CHANGE_MUTABLE:
            raise BizException("当前变更集状态不允许发布: " + change.status)
        from .services import DatasourceService, MappingService
        DatasourceService(self.session).require(change.ds_code)
        fingerprint, version = self.current_baseline(change.ds_code)
        if fingerprint != change.scan_fingerprint or version != change.ontology_version:
            change.status = "STALE"
            self.sets.update_by_id(change)
            raise BizException("扫描结果或本体版本已变化，请重新分析")
        items = self.items.select_list(OntologyChangeItem.change_set_id == change_set_id,
                                       OntologyChangeItem.review_status == "ACCEPTED")
        if not items:
            raise BizException("没有已采纳建议可发布")
        order = {"CONCEPT": 0, "ATTRIBUTE": 1, "TERM": 1, "RELATION": 2,
                 "RULE": 3, "ACTION": 3, "METRIC": 3, "MAPPING": 4}
        results = []
        with transactional(self.session):
            accepted_refs = {f"{item.item_type}:{item.target_key}" for item in items}
            for item in items:
                missing_dependencies = [dep for dep in json_value(item.dependency_json, [])
                                        if dep not in accepted_refs and not self.existing_dependency(dep)]
                if missing_dependencies:
                    raise BizException("建议依赖未采纳: " + ", ".join(missing_dependencies))
            for item in sorted(items, key=lambda row: (order.get(row.item_type, 99), row.id)):
                payload = json_value(item.payload_json, {})
                self.validate_payload(item.item_type, payload)
                if item.item_type == "MAPPING" and payload["dsCode"] != change.ds_code:
                    raise BizException("候选映射数据源与变更集不一致")
                ref = self.materialize(item.item_type, payload, MappingService)
                item.result_ref_json = stable_json(ref)
                self.items.update_by_id(item)
                results.append(ref)
            change.status = "PUBLISHED"
            change.published_by = actor
            change.published_at = datetime.now()
            change.updated_at = datetime.now()
            self.sets.update_by_id(change)
        return {"changeSetId": change.id, "status": "PUBLISHED", "created": results}

    def require_mutable(self, change_set_id):
        change = self.sets.select_by_id(change_set_id)
        if change is None:
            raise BizException("变更集不存在: " + str(change_set_id))
        if change.status not in CHANGE_MUTABLE:
            raise BizException("当前变更集状态不允许修改: " + change.status)
        return change

    def existing_dependency(self, reference):
        kind, separator, key = str(reference).partition(":")
        if not separator or not key:
            return False
        if kind == "CONCEPT":
            return BaseDAO(self.session, Concept).select_count(Concept.code == key) > 0
        if kind == "ATTRIBUTE" and "." in key:
            concept_code, attr_code = key.split(".", 1)
            return BaseDAO(self.session, Attribute).select_count(
                Attribute.concept_code == concept_code, Attribute.attr_code == attr_code) > 0
        model_and_field = {
            "RULE": (Rule, Rule.rule_code), "ACTION": (Action, Action.action_code),
            "METRIC": (Metric, Metric.metric_code),
        }.get(kind)
        return bool(model_and_field and BaseDAO(self.session, model_and_field[0]).select_count(model_and_field[1] == key))

    @staticmethod
    def validate_payload(item_type, payload):
        required = {
            "CONCEPT": ("code", "name", "domainCode"), "ATTRIBUTE": ("conceptCode", "attrCode", "attrName", "dataType"),
            "TERM": ("term", "conceptCode"), "RELATION": ("fromConcept", "toConcept", "relationName"),
            "RULE": ("ruleCode", "name", "conceptCode"), "ACTION": ("actionCode", "name", "conceptCode"),
            "METRIC": ("metricCode", "name"),
            "MAPPING": ("dsCode", "tableName", "columnName", "conceptCode", "attrCode"),
        }
        if item_type not in required:
            raise BizException("不支持的建议类型: " + item_type)
        missing = [field for field in required[item_type] if payload.get(field) in (None, "")]
        if missing:
            raise BizException("建议缺少必填字段: " + ", ".join(missing))
        for field in ("code", "conceptCode", "ruleCode", "actionCode", "metricCode"):
            if payload.get(field) and not CODE.match(str(payload[field])):
                raise BizException("编码格式不合法: " + field)
        if contains_sql_key(payload):
            raise BizException("治理建议不允许包含 SQL")
        if len(stable_json(payload)) > 16384:
            raise BizException("建议载荷超过长度限制")

    def materialize(self, item_type, payload, mapping_service):
        if item_type == "CONCEPT":
            code = payload["code"]
            if BaseDAO(self.session, Concept).select_one(Concept.code == code):
                raise BizException("概念编码已存在: " + code)
            if not BaseDAO(self.session, Domain).select_one(Domain.code == payload["domainCode"]):
                raise BizException("领域不存在: " + payload["domainCode"])
            row = BaseDAO(self.session, Concept).insert({**payload, "status": "DRAFT", "version": 1})
            return {"type": item_type, "id": row.id, "key": code}
        model = {"ATTRIBUTE": Attribute, "TERM": Term, "RELATION": Relation,
                 "RULE": Rule, "ACTION": Action, "METRIC": Metric}.get(item_type)
        if model:
            data = dict(payload)
            concept_dao = BaseDAO(self.session, Concept)
            if item_type in {"ATTRIBUTE", "TERM", "RULE", "ACTION"} and not concept_dao.select_one(Concept.code == payload["conceptCode"]):
                raise BizException("引用概念不存在: " + payload["conceptCode"])
            if item_type == "RELATION":
                for code in (payload["fromConcept"], payload["toConcept"]):
                    if not concept_dao.select_one(Concept.code == code):
                        raise BizException("引用概念不存在: " + code)
            if item_type == "METRIC" and payload.get("conceptCode") and not concept_dao.select_one(Concept.code == payload["conceptCode"]):
                raise BizException("引用概念不存在: " + payload["conceptCode"])
            if item_type in {"RULE", "ACTION"}:
                data.update(status="DRAFT", version=1)
            row = BaseDAO(self.session, model).insert(data)
            key = payload.get("attrCode") or payload.get("term") or payload.get("relationName") or payload.get("ruleCode") or payload.get("actionCode") or payload.get("metricCode")
            return {"type": item_type, "id": row.id, "key": key}
        if item_type == "MAPPING":
            data = {**payload, "confirmed": 0, "source": "AI_GOVERNANCE"}
            existing = BaseDAO(self.session, Mapping).select_one(
                Mapping.ds_code == data["dsCode"], Mapping.table_name == data["tableName"],
                Mapping.column_name == data["columnName"])
            if existing:
                raise BizException(f'物理列已有映射，拒绝覆盖: {data["tableName"]}.{data["columnName"]}')
            if not BaseDAO(self.session, PhysicalColumn).select_one(
                PhysicalColumn.ds_code == data["dsCode"], PhysicalColumn.table_name == data["tableName"],
                PhysicalColumn.column_name == data["columnName"]):
                raise BizException(f'物理列不存在: {data["tableName"]}.{data["columnName"]}')
            if not BaseDAO(self.session, Attribute).select_one(
                Attribute.concept_code == data["conceptCode"], Attribute.attr_code == data["attrCode"]):
                raise BizException(f'本体属性不存在: {data["conceptCode"]}.{data["attrCode"]}')
            mapping_service(self.session).save_batch([data])
            row = mapping_service(self.session).select_one(Mapping.ds_code == data["dsCode"],
                Mapping.table_name == data["tableName"], Mapping.column_name == data["columnName"],
                Mapping.concept_code == data["conceptCode"], Mapping.attr_code == data["attrCode"])
            return {"type": item_type, "id": row.id if row else None,
                    "key": f'{data["tableName"]}.{data["columnName"]}'}
        raise BizException("不支持的建议类型: " + item_type)
