from collections import defaultdict
from datetime import date
import json
import logging
import re
from sqlalchemy import or_, text
from bemodel.core.base_dao import BaseDAO
from bemodel.datasource.entities import Mapping, PhysicalTable
from bemodel.datasource.services import DatasourceService
from bemodel.llm.services import DeepSeekClient
from bemodel.ontology.entities import Concept, Attribute, Relation
from bemodel.ontology.miss_service import MissService
from bemodel.rca.services import dumps
from .prompts import SEMANTIC_PLAN_PROMPT
from .sql_validation import validate_sql


def java_value(value):
    if value is None:
        return 'null'
    if isinstance(value, dict):
        return '{'+', '.join(str(k)+'='+java_value(v) for k, v in value.items())+'}'
    if isinstance(value, list):
        return '['+', '.join(map(java_value, value))+']'
    return str(value)


class SemanticQaService:
    def __init__(self, session):
        self.session = session
        self.llm = DeepSeekClient(session)
        self.ds = DatasourceService(session)

    def rows(self, model, *conditions):
        return BaseDAO(self.session, model).select_list(*conditions)

    def build_semantic_context(self):
        concepts = self.rows(Concept, Concept.status == 'PUBLISHED')
        names = {c.code: c.name for c in concepts}
        attrs = self.rows(Attribute)
        attr_names = {(a.concept_code, a.attr_code): a.attr_name for a in attrs}
        result = '【本体概念】\n'
        for c in concepts:
            attributes = [f'{a.attr_name}/{a.data_type}' for a in attrs if a.concept_code == c.code]
            result += f'{c.code}({c.name})'+(': '+', '.join(attributes) if attributes else '')+'\n'
        comments = {(t.ds_code, t.table_name): t.table_comment or '' for t in self.rows(PhysicalTable)}
        groups = defaultdict(lambda: defaultdict(list))
        for m in self.rows(Mapping, Mapping.confirmed == 1):
            groups[m.ds_code][m.table_name].append(m)
        result += '\n【物理映射】（概念.属性 = 数据源.表.列，枚举列为原始码=中文）\n'
        for ds, tables in sorted(groups.items()):
            result += ds+':\n'
            for table, mappings in sorted(tables.items()):
                comment = comments.get((ds, table))
                result += '  '+table+('（'+comment+'）' if comment else '')+': '
                cols = []
                for m in mappings:
                    col = f'{m.column_name}={m.concept_code}.{attr_names.get((m.concept_code, m.attr_code), m.attr_code)}'
                    if m.value_map and m.value_map.strip():
                        col += '{'+m.value_map.replace('{', '').replace('}', '').replace('"', '')+'}'
                    cols.append(col)
                result += ', '.join(cols)+'\n'
        relations = self.rows(Relation)
        if relations:
            result += '\n【概念关系】\n'
            for r in relations:
                result += f'{r.from_concept}({names.get(r.from_concept, "")})—{r.relation_name}→{r.to_concept}({names.get(r.to_concept, "")})\n'
        return result

    def plan_query(self, q):
        prompt = self.build_semantic_context()+SEMANTIC_PLAN_PROMPT.replace('__TODAY__', str(date.today())).replace('__QUESTION__', q)
        response = self.llm.chat('CS_SEMANTIC_PLAN', '你是医疗信息平台的本体语义查询规划器，把自然语言问题编译为只读 SQL。只返回JSON，不要多余文字。', prompt)
        if response is None:
            return None
        try:
            start, end = response.find('{'), response.rfind('}')
            plan = json.loads(response[start:end+1] if start >= 0 and end > start else response)
            for key in ('ds', 'sql', 'conclusion', 'verifySql'):
                plan[key] = (plan.get(key) or '').strip()
            plan.setdefault('semantics', '')
            if plan.get('mode') == 'UNANSWERABLE' or (plan.get('mode') == 'MODEL_ANSWER' and plan['conclusion']) or (plan.get('mode') == 'QUERY' and plan['ds'] and plan['sql']):
                return plan
        except (ValueError, AttributeError, TypeError):
            pass
        return None

    def allowed(self, ds):
        mappings = self.rows(Mapping, Mapping.ds_code == ds, Mapping.confirmed == 1)
        return list(dict.fromkeys(m.table_name for m in mappings)), {m.column_name for m in mappings}

    def execute(self, ds, sql):
        with self.ds.jdbc(ds).connect() as conn:
            # MySQL enforces the statement timeout; fetchmany caps response rows even
            # when the source's LIMIT syntax uses an offset or appears in a comment.
            conn.execute(text('SET SESSION max_execution_time=15000'))
            cursor = conn.execute(text(sql))
            return [dict(row) for row in cursor.mappings().fetchmany(100)]

    def links(self, codes):
        return [dict(label='去本体页看概念 '+c, route='/ontology?concept='+c) for c in list(dict.fromkeys(codes))[:2]]

    def fill_parse(self, result, query):
        try:
            concepts = self.rows(Concept, Concept.status == 'PUBLISHED')
            hits = []
            for c in concepts:
                how = '名称' if c.name and len(c.name) >= 2 and c.name in query else '编码' if c.code and len(c.code) >= 2 and c.code.lower() in query.lower() else None
                if how:
                    hits.append(dict(code=c.code, name=c.name if c.name is not None else c.code, match=how))
                if len(hits) >= 6:
                    break
            codes = [h['code'] for h in hits]
            names = {c.code: c.name for c in concepts}
            rels = self.rows(Relation, or_(Relation.from_concept.in_(codes), Relation.to_concept.in_(codes)))[:8] if codes else []
            result['matchedConcepts'] = hits
            result['relations'] = [{'from': r.from_concept, 'fromName': names.get(r.from_concept, r.from_concept), 'relation': r.relation_name, 'to': r.to_concept, 'toName': names.get(r.to_concept, r.to_concept)} for r in rels]
        except Exception:
            result.update(matchedConcepts=[], relations=[])

    def answer(self, q, analytics=False):
        plan = self.plan_query(q)
        if plan is None:
            return None, False
        def miss():
            MissService(self.session).record_miss(q, 'QUESTION', 'QA_ASK' if analytics else 'CS_ASK')
            return None, True
        if plan['mode'] == 'UNANSWERABLE':
            return miss()
        if plan['mode'] == 'MODEL_ANSWER':
            return self.model_answer(q, plan), False
        tables, columns = self.allowed(plan['ds'])
        if not tables:
            return miss()
        try:
            sql = validate_sql(plan['sql'], tables, columns)
            rows = self.execute(plan['ds'], sql)
        except Exception:
            logging.getLogger(__name__).warning('语义查询失败，降级能力菜单', exc_info=True)
            return miss()
        total, view = len(rows), rows[:20]
        rows_json = dumps(view)
        if len(rows_json) > 3000:
            rows_json = rows_json[:3000]+'…'
        answer = self.llm.chat('CS_SEMANTIC_ANSWER', '你是医院信息平台的数据问答助手。严格基于给定查询结果用中文回答，先给结论再给关键数字，口语化，不超过200字。结果里没有的信息不要编造，结果为0条就如实说没有。', f"用户问题：{q}\n查询语义：{plan['semantics']}\n执行SQL：{sql}\n结果行数：{total}"+('（仅展示前20行）' if total > 20 else '')+'\n结果JSON：'+rows_json)
        if answer is None:
            answer = f"按本体映射到 {plan['ds']} 查询，没有符合条件的记录。（{plan['semantics']}）" if total == 0 else f"按本体映射查询到 {total} 条记录（{plan['semantics']}）。首条明细：{java_value(view[0])}"
        used = [t for t in tables if re.search(r'\b'+re.escape(t)+r'\b', sql, re.I)]
        codes = [m.concept_code for m in self.rows(Mapping, Mapping.ds_code == plan['ds'], Mapping.table_name.in_(used))] if used else []
        result = dict(question=q, intent='语义查询', router='SEMANTIC', answer=answer,
            evidence=[dict(label='执行SQL', value=sql), dict(label='数据源', value=plan['ds']+' / '+','.join(used)), dict(label='结果行数', value=str(total)+('（展示前20行）' if total > 20 else ''))],
            links=self.links(codes), semantics=plan['semantics'], rows=view)
        self.fill_parse(result, q+' '+plan['semantics'])
        return result, False

    def model_answer(self, q, plan):
        if not plan['conclusion']:
            return None
        sql, rows = None, None
        tables, columns = self.allowed(plan['ds']) if plan['ds'] else ([], set())
        if plan['verifySql'] and tables:
            try:
                sql = validate_sql(plan['verifySql'], tables, columns)
                rows = self.execute(plan['ds'], sql)
            except Exception:
                sql, rows = None, None
        probe = '无（纯结构判断）' if sql is None else sql+' → '+dumps(rows)
        answer = self.llm.chat('CS_SEMANTIC_ANSWER', '你是医院信息平台的业务规则解答助手。基于给定的本体结构判断与验证探针结果用中文回答，先给「可以/不可以」的结论，再给依据（结构口径+探针数字），口语化，不超过200字。不要编造探针没有的数字。', f"用户问题：{q}\n本体结构判断：{plan['semantics']}\n初步结论：{plan['conclusion']}\n验证探针：{probe}")
        if answer is None:
            answer = plan['conclusion']+'（结构依据：'+plan['semantics']+'）'
            if rows is not None:
                answer += ' 验证探针返回：'+java_value(rows[0])
        evidence = [dict(label='结构依据', value=plan['semantics'])]
        if sql is not None:
            evidence += [dict(label='执行SQL', value=sql), dict(label='结果行数', value=str(len(rows))+('，首行 '+java_value(rows[0]) if rows else ''))]
        description = plan['semantics']+' '+plan['conclusion']
        codes = [c.code for c in self.rows(Concept, Concept.status == 'PUBLISHED') if c.code in description or (c.name is not None and c.name in description)]
        return dict(question=q, intent='语义查询', router='SEMANTIC', answer=answer, evidence=evidence, links=self.links(codes))
