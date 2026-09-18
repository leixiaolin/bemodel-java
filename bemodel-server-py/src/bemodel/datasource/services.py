from datetime import datetime
from sqlalchemy import text
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.crypto_service import CryptoService
from bemodel.core.database import transactional
from bemodel.core.dynamic_ds import get_engine, make_engine
from bemodel.core.exceptions import BizException
from bemodel.core.result import to_camel_dict
from .entities import Datasource, PhysicalTable, PhysicalColumn, Mapping


class DatasourceService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Datasource)
        self.crypto = CryptoService(settings.app_secret_key)

    def get_by_code(self, code):
        return self.select_one(Datasource.ds_code == code)

    def require(self, code):
        ds = self.get_by_code(code)
        if ds is None:
            raise BizException("数据源不存在: " + code)
        return ds

    def jdbc(self, code):
        return get_engine(code, lambda: self.require(code), self.crypto)

    def query(self, code, sql, params=None):
        with self.jdbc(code).connect() as conn:
            return [dict(r) for r in conn.execute(text(sql), params or {}).mappings()]

    def create(self, data):
        row = self.entity(data)
        row.password = self.crypto.encrypt(row.password)
        result = to_camel_dict(self.insert(row))
        result["password"] = "****"
        return result

    def list_all(self):
        result = to_camel_dict(self.select_list(order=(Datasource.ds_code,)))
        for row in result:
            row["password"] = "****"
        return result

    def test_connection(self, data):
        engine = None
        try:
            engine = make_engine(self.entity(data), self.crypto, timeout=5)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar_one()
            return True
        except Exception:
            return False
        finally:
            if engine:
                engine.dispose()

    def migrate_secrets(self):
        for row in self.select_list():
            if row.password is not None and not row.password.startswith("ENC:"):
                row.password = self.crypto.encrypt(row.password)
                self.update_by_id(row)


class SchemaScanService:
    def __init__(self, session):
        self.session = session
        self.ds = DatasourceService(session)

    def tables(self, code):
        return BaseDAO(self.session, PhysicalTable).select_list(PhysicalTable.ds_code == code, order=(PhysicalTable.table_name,))

    def columns(self, code, table=None):
        return BaseDAO(self.session, PhysicalColumn).select_list(PhysicalColumn.ds_code == code,
            *([PhysicalColumn.table_name == table] if table and table.strip() else []), order=(PhysicalColumn.ordinal_position,))

    def scan(self, code):
        with transactional(self.session):
            ds = self.ds.require(code)
            tables = self.ds.query(code, "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db", {"db": ds.db_name})
            columns = self.ds.query(code, "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_COMMENT,COLUMN_KEY,ORDINAL_POSITION FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:db ORDER BY TABLE_NAME,ORDINAL_POSITION", {"db": ds.db_name})
            td, cd = BaseDAO(self.session, PhysicalTable), BaseDAO(self.session, PhysicalColumn)
            td.delete(PhysicalTable.ds_code == code)
            cd.delete(PhysicalColumn.ds_code == code)
            now = datetime.now()
            for row in tables:
                td.insert(PhysicalTable(ds_code=code, table_name=row["TABLE_NAME"], table_comment=row.get("TABLE_COMMENT", ""), scanned_at=now))
            for row in columns:
                cd.insert(PhysicalColumn(ds_code=code, table_name=row["TABLE_NAME"], column_name=row["COLUMN_NAME"],
                    data_type=row["DATA_TYPE"], column_comment=row.get("COLUMN_COMMENT", ""), is_pk=int(row["COLUMN_KEY"] == "PRI"), ordinal_position=row["ORDINAL_POSITION"]))
            return len(tables)


class MappingService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, Mapping)

    def list(self, code=None, table=None):
        return self.select_list(*([Mapping.ds_code == code] if code and code.strip() else []),
                                *([Mapping.table_name == table] if table and table.strip() else []))

    def save_batch(self, rows):
        for data in rows:
            row = self.entity(data)
            existing = self.select_one(Mapping.ds_code == row.ds_code, Mapping.table_name == row.table_name, Mapping.column_name == row.column_name)
            if existing:
                row.id = existing.id
                self.update_by_id(row)
            else:
                self.insert(row)

    def ai_suggest(self, ds_code, table):
        import json
        from bemodel.ontology.entities import Concept, Attribute
        from bemodel.ontology.miss_service import MissService
        from bemodel.llm.services import DeepSeekClient
        columns = SchemaScanService(self.session).columns(ds_code, table)
        if not columns:
            raise BizException(f"未找到物理表，请先扫描数据源: {ds_code}.{table}")
        concepts = BaseDAO(self.session, Concept).select_list(Concept.status == "PUBLISHED")
        attributes = BaseDAO(self.session, Attribute).select_list()
        prompt = "物理表 " + table + " 的字段：\n"
        for c in columns:
            prompt += f'- {c.column_name} ({c.data_type}) 注释: {c.column_comment or ""}\n'
        prompt += "\n可选标准概念及属性：\n"
        for c in concepts:
            attrs = ", ".join(f"{a.attr_code}({a.attr_name})" for a in attributes if a.concept_code == c.code)
            prompt += f"概念 {c.code}({c.name}): {attrs}\n"
        prompt += '\n请为每个物理字段推荐映射，返回JSON数组，元素格式：{"column":"字段名","conceptCode":"概念编码","attrCode":"属性编码","confidence":0.0-1.0,"reason":"理由"}。无合适映射时 attrCode 填 null。只返回JSON。'
        response = DeepSeekClient(self.session).chat("MAPPING_SUGGEST", "你是医疗信息化本体映射专家。只返回JSON数组，不要多余文字。", prompt)
        suggestions = []
        if response:
            try:
                parsed = json.loads(response[response.index("["):response.rindex("]")+1])
                for row in parsed:
                    if row.get("column") in {c.column_name for c in columns}:
                        suggestions.append({"column": row["column"], "conceptCode": row.get("conceptCode") or "",
                            "attrCode": row.get("attrCode") or "", "confidence": float(row.get("confidence", .5)), "reason": row.get("reason") or ""})
            except (ValueError, TypeError, AttributeError):
                suggestions = []
        llm_used = bool(suggestions)
        if not suggestions:
            codes = {c.code for c in concepts}
            for c in columns:
                best = next((a for a in attributes if a.concept_code in codes and
                    (a.attr_code.lower() in c.column_name.lower() or c.column_comment and a.attr_name in c.column_comment)), None)
                suggestions.append({"column": c.column_name, "conceptCode": best.concept_code if best else "",
                    "attrCode": best.attr_code if best else "", "confidence": .6 if best else 0.,
                    "reason": "规则匹配：列名/注释与属性相似" if best else "未匹配，请人工指定"})
        for c in columns:
            if not any(s["column"] == c.column_name and s["conceptCode"].strip() for s in suggestions):
                MissService(self.session).record_miss(c.column_comment if c.column_comment and c.column_comment.strip() else c.column_name, "ATTRIBUTE", "MAPPING_AI")
        return {"llmUsed": llm_used, "model": settings.deepseek_model, "suggestions": suggestions}
