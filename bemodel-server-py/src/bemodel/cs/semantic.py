from collections import defaultdict
from datetime import date
import json
import logging
import re
from urllib.parse import quote_plus
from sqlalchemy import or_, text
from bemodel.agents.critic import MAX_AGENT_FIXES, SqlCritic, describe_result, improved, suspicious_result
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.datasource.entities import Mapping, PhysicalTable
from bemodel.datasource.services import DatasourceService, parse_value_map
from bemodel.llm.services import DeepSeekClient
from bemodel.ontology.entities import Concept, Attribute, Relation, Term
from bemodel.ontology.miss_service import MissService
from bemodel.rca.services import dumps
from . import asset_context, metric_policy
from .prompts import SEMANTIC_PLAN_PROMPT
from .sql_validation import validate_sql

ENUM_TRUE_WORDS = {'异常', '阳性', '是', '有', '启用', '已发布', '通过'}
ENUM_FALSE_WORDS = {'正常', '阴性', '否', '无', '停用', '未发布', '不通过'}
ENUM_TRUE_CODES = {'1', 'Y', 'A', 'T', 'TRUE', 'YES'}
ENUM_FALSE_CODES = {'0', 'N', 'F', 'FALSE', 'NO'}
ID_CARD_NAME_HINTS = ('身份证', '证件号')
ID_CARD_CODE_NAMES = {'id_card', 'idcard', 'id_no', 'idcard_no', 'cert_no'}


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
        self.critic = SqlCritic(session)

    def rows(self, model, *conditions):
        return BaseDAO(self.session, model).select_list(*conditions)

    def base_context(self):
        """原有语义上下文：概念+属性、confirmed 物理映射、概念关系。"""
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

    def build_semantic_context(self, question=None):
        """完整语义上下文：基础段 + 资产段（开关开启且存在已发布资产时追加）。

        每次调用独立构建资产快照；无合格资产条目时输出与基础上下文逐字节一致。
        """
        result = self.base_context()
        if settings.semantic_asset_enhance:
            result += asset_context.build_asset_snapshot(self.session, question).text
        return result

    def _plan_query(self, q, insist=False, note=None):
        """规划并返回 (plan, snapshot)：snapshot 是本次实际送入模型的资产快照，
        供后续引用核验使用；重规划/纠错各自构建快照，不跨请求共享。"""
        snapshot = asset_context.build_asset_snapshot(self.session, q) if settings.semantic_asset_enhance else None
        prompt = self.base_context()+(snapshot.text if snapshot else '') \
            + SEMANTIC_PLAN_PROMPT.replace('__TODAY__', str(date.today())).replace('__QUESTION__', q)
        if snapshot is not None:
            # 资产文本是数据区，补充指令放在数据区之外（设计方案 4.1/4.5）
            prompt += asset_context.ASSET_PLAN_ADDENDUM
        if note:
            prompt += note
        if insist:
            prompt += '\n注意：该问题用词已命中上方本体概念/属性，请仔细核对【物理映射】段优先生成 QUERY 或 MODEL_ANSWER；确实无映射可用才允许 UNANSWERABLE。'
        for _ in range(2):
            # 同一问题偶发输出漂移（非法JSON/缺字段）时重试一次，避免直接落兜底菜单
            response = self.llm.chat('CS_SEMANTIC_PLAN', '你是医疗信息平台的本体语义查询规划器，把自然语言问题编译为只读 SQL。只返回JSON，不要多余文字。', prompt)
            if response is None:
                return None, snapshot
            try:
                start, end = response.find('{'), response.rfind('}')
                plan = json.loads(response[start:end+1] if start >= 0 and end > start else response)
                for key in ('ds', 'sql', 'conclusion', 'verifySql'):
                    plan[key] = (plan.get(key) or '').strip()
                plan.setdefault('semantics', '')
                if plan.get('mode') == 'UNANSWERABLE' or (plan.get('mode') == 'MODEL_ANSWER' and plan['conclusion']) or (plan.get('mode') == 'QUERY' and plan['ds'] and plan['sql']):
                    return plan, snapshot
            except (ValueError, AttributeError, TypeError):
                pass
        return None, snapshot

    def plan_query(self, q, insist=False):
        plan, _ = self._plan_query(q, insist=insist)
        return plan

    def metric_direct_answer(self, q):
        """合格指标直查：完整问法命中且资格核验通过时，直接执行标定探针并
        确定性模板作答——不调用规划/作答 LLM、不触发纠错（COUNT=0 是合法
        业务态）、不写监控最近值（不与巡检混淆）。任一环节失败记录原因后
        返回 None 回落语义规划（直查失败不记概念缺口）。"""
        code = metric_policy.match_question(q)
        if code is None:
            return None
        policy, metric, reason = metric_policy.verify_qualified(self.session, code)
        if reason or metric is None:
            logging.getLogger(__name__).warning('指标直查资格失效(%s)：%s，回落语义规划', code, reason)
            return None
        try:
            tables, columns = self.allowed(metric.ds_code)
            if not tables:
                logging.getLogger(__name__).warning('指标直查数据源无 confirmed 映射(%s)，回落语义规划', code)
                return None
            sql = validate_sql(self.normalize_enum_literals(metric.ds_code, metric.probe_sql), tables, columns)
            # 执行前再次确认资格内容未发生不允许的变化（设计方案 4.3）
            policy, metric, reason = metric_policy.verify_qualified(self.session, code)
            if reason or metric is None:
                logging.getLogger(__name__).warning('指标直查执行前资格复核失败(%s)：%s，回落语义规划', code, reason)
                return None
            rows = self.execute(metric.ds_code, sql)
        except Exception as exc:
            logging.getLogger(__name__).warning('指标直查校验/执行失败(%s, %s)，回落语义规划', code, type(exc).__name__)
            return None
        accepted, value, vreason = metric_policy.check_result_value(rows, policy)
        if not accepted:
            logging.getLogger(__name__).warning('指标直查结果形态不符(%s)：%s，回落语义规划', code, vreason)
            return None
        if value is None:
            answer = f"指标「{metric.name}」{policy['null_answer']}（{policy['scope']}）。口径：{metric.definition}"
        else:
            answer = (f"当前全量数据快照中，{policy['phrase']}共 {value} {policy['unit']}。"
                      f"口径：{metric.definition}该结果不限定发生日期。")
            if metric.warn_threshold is not None and value > metric.warn_threshold:
                answer += f"已超过预警阈值 {metric.warn_threshold}{policy['unit']}，需要关注。"
        used = self.tables_in_sql(sql, tables)
        codes = [m.concept_code for m in self.rows(Mapping, Mapping.ds_code == metric.ds_code, Mapping.confirmed == 1, Mapping.table_name.in_(used))] if used else []
        evidence = [
            dict(label='指标', value=f"{metric.name}（{code}）"),
            dict(label='指标口径', value=metric.definition),
            dict(label='统计范围', value=policy['scope']),
            dict(label='单位', value=policy['unit']),
            dict(label='执行SQL', value=sql),
            dict(label='数据源', value=metric.ds_code+(' / '+','.join(used) if used else '')),
            dict(label='实测值', value=('暂无可用实测值' if value is None else f"{value}{policy['unit']}")),
        ]
        result = dict(question=q, intent='指标实测', router='SEMANTIC', answer=answer, evidence=evidence,
            links=[dict(label='去统一口径页看该指标', route='/glossary?metric='+quote_plus(code))],
            semantics=metric.definition, rows=[],
            citations=asset_context.build_citations([], metric_citation=dict(
                code=code, name=metric.name, route='/glossary?metric='+quote_plus(code))))
        self.fill_parse(result, q+' '+metric.definition, codes)
        return result

    def insufficient_result(self, q, valid_entries=()):
        """依据不足的确定性结果：保留已有有效证据，不输出肯定业务结论。"""
        evidence = [dict(label='处理说明', value='规划引用的业务资产未通过核验或无有效依据，已按依据不足处理，未输出业务结论')]
        evidence += [dict(label=f'依据{asset_context.KIND_LABEL[e.kind]} {e.code}', value=e.evidence) for e in valid_entries]
        return dict(question=q, intent='语义查询', router='SEMANTIC',
            answer='当前已发布资产不足以确认该问题的结论。请到本体管理补充或核验业务资产（规则/公理/动作）后重试，或换个问法。',
            evidence=evidence, links=[])

    def _gate_query_citations(self, q, plan, snapshot):
        """QUERY 引用门控（设计方案 4.4）：未声明引用直接放行；声明了失效引用
        则重规划一次（新快照），仍失败转依据不足，不执行以无效依据生成的计划。

        返回 (plan, snapshot, valid_entries, outcome)：outcome 为 'ok'（继续
        执行）、'insufficient'（依据不足）、
        'model'（重规划改判 MODEL_ANSWER，plan 已替换）。"""
        declared = asset_context.declared_codes(plan)
        if plan.get('evidenceStatus') in ('INSUFFICIENT', 'CONFLICT'):
            valid, _, _ = asset_context.verify_citations(self.session, snapshot, plan)
            return plan, snapshot, valid, 'insufficient'
        bad_type = any(v is None for v in declared.values())
        if not bad_type and not any(declared[k] for k in ('rule', 'axiom', 'action')):
            return plan, snapshot, [], 'ok'
        valid, invalid, err = asset_context.verify_citations(self.session, snapshot, plan)
        if not err and not invalid:
            return plan, snapshot, valid, 'ok'
        pointed = ', '.join(invalid) if invalid else '引用字段类型错误'
        note = (f'\n注意：你上次规划中引用的资产编码未通过核验（{pointed}）。'
                '请基于本次上下文重新规划，只引用真实出现的编码；确无依据时返回 UNANSWERABLE，'
                '或改用 MODEL_ANSWER 并在 semantics 中说明依据不足。')
        retry_plan, retry_snapshot = self._plan_query(q, note=note)
        if retry_plan is None:
            return plan, snapshot, valid, 'insufficient'
        if retry_plan['mode'] == 'UNANSWERABLE':
            return retry_plan, retry_snapshot, valid, 'insufficient'
        if retry_plan['mode'] == 'MODEL_ANSWER':
            return retry_plan, retry_snapshot, [], 'model'
        valid2, invalid2, err2 = asset_context.verify_citations(self.session, retry_snapshot, retry_plan)
        if err2 or invalid2:
            return retry_plan, retry_snapshot, valid2, 'insufficient'
        return retry_plan, retry_snapshot, valid2, 'ok'

    def coverage_hit(self, q):
        """问题文本（按二字词元）是否命中已发布概念名/属性名——拒答前的确定性护栏。"""
        grams = {q[i:i+2] for i in range(len(q)-1)}
        if not grams:
            return False
        names = [c.name for c in self.rows(Concept, Concept.status == 'PUBLISHED') if c.name]
        names += [a.attr_name for a in self.rows(Attribute) if a.attr_name]
        return any(any(gram in name for name in names) for gram in grams)

    def allowed(self, ds):
        mappings = self.rows(Mapping, Mapping.ds_code == ds, Mapping.confirmed == 1)
        return list(dict.fromkeys(m.table_name for m in mappings)), {m.column_name for m in mappings}

    def enum_mappings(self, ds):
        mappings = self.rows(Mapping, Mapping.ds_code == ds, Mapping.confirmed == 1)
        by_column = {}
        for m in mappings:
            # 容忍历史裸字典文本（如「0在检 1完成 2作废」），解析不出则跳过该列
            value_map = parse_value_map(m.value_map)
            if value_map:
                by_column[(m.table_name.lower(), m.column_name.lower())] = value_map
        return by_column

    def canonical_enum_value(self, value_map, literal):
        if literal in value_map:
            return literal
        target = literal.strip()
        target_upper = target.upper()
        for code, label in value_map.items():
            if target == label:
                return code
        true_codes = {code for code, label in value_map.items() if label in ENUM_TRUE_WORDS or code.upper() in ENUM_TRUE_CODES}
        false_codes = {code for code, label in value_map.items() if label in ENUM_FALSE_WORDS or code.upper() in ENUM_FALSE_CODES}
        if len(true_codes) == 1 and target_upper in ENUM_TRUE_CODES:
            return next(iter(true_codes))
        if len(false_codes) == 1 and target_upper in ENUM_FALSE_CODES:
            return next(iter(false_codes))
        return literal

    def normalize_enum_literals(self, ds, sql):
        enum_maps = self.enum_mappings(ds)
        if not enum_maps:
            return sql
        table_aliases = {}
        for match in re.finditer(r'\b(?:from|join)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?(?:\s+(?:as\s+)?`?([a-zA-Z_][a-zA-Z0-9_]*)`?)?', sql, re.I):
            table, alias = match.groups()
            table_aliases[table.lower()] = table.lower()
            if alias and alias.lower() not in {'where', 'join', 'left', 'right', 'inner', 'outer', 'cross', 'on', 'group', 'order', 'having', 'limit'}:
                table_aliases[alias.lower()] = table.lower()

        def replace(match):
            qualifier, column, quote, literal = match.groups()
            qualifier = qualifier.strip('`').lower() if qualifier else None
            column = column.strip('`')
            column_key = column.lower()
            candidates = []
            if qualifier:
                table = table_aliases.get(qualifier, qualifier)
                candidates.append((table, column_key))
            else:
                candidates.extend(key for key in enum_maps if key[1] == column_key)
            candidates = [key for key in candidates if key in enum_maps]
            if len(candidates) != 1:
                return match.group(0)
            canonical = self.canonical_enum_value(enum_maps[candidates[0]], literal)
            if canonical == literal:
                return match.group(0)
            escaped = canonical.replace('\\', '\\\\').replace(quote, '\\' + quote)
            prefix = (qualifier + '.' if qualifier else '') + column
            return f"{prefix} = {quote}{escaped}{quote}"

        pattern = re.compile(r'\b(?:(`?[a-zA-Z_][a-zA-Z0-9_]*`?)\.)?`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*=\s*([\'"])([^\'"]*)\3', re.I)
        return pattern.sub(replace, sql)

    def id_card_columns(self, ds):
        """识别数据源里的身份证号物理列：属性名含「身份证/证件号」，或属性/列名为常见证件命名。"""
        attr_names = {(a.concept_code, a.attr_code): a.attr_name or '' for a in self.rows(Attribute)}
        columns = set()
        for m in self.rows(Mapping, Mapping.ds_code == ds, Mapping.confirmed == 1):
            attr_name = attr_names.get((m.concept_code, m.attr_code), '')
            if (any(hint in attr_name for hint in ID_CARD_NAME_HINTS)
                    or m.attr_code.lower() in ID_CARD_CODE_NAMES
                    or m.column_name.lower() in ID_CARD_CODE_NAMES):
                columns.add(m.column_name.lower())
        return columns

    def fix_id_card_year_prefix(self, ds, sql):
        """LLM 偶发把出生年份译成身份证前缀匹配（LIKE '1988%'）的确定性护栏：
        证号开头是6位地区码，出生年份在第7-14位，前缀匹配永远查不到，改写为包含匹配。"""
        columns = self.id_card_columns(ds)
        if not columns:
            return sql

        def replace(match):
            ref, quote, year = match.groups()
            column = ref.strip('`').rsplit('.', 1)[-1].strip('`').lower()
            if column not in columns:
                return match.group(0)
            return f"{ref} LIKE {quote}%{year}%{quote}"

        pattern = re.compile(r'(`?[a-zA-Z_][\w.`]*`?)\s+LIKE\s+([\'"])((?:19|20)\d{2})%\2', re.I)
        return pattern.sub(replace, sql)

    def execute(self, ds, sql):
        with self.ds.jdbc(ds).connect() as conn:
            # MySQL enforces the statement timeout; fetchmany caps response rows even
            # when the source's LIMIT syntax uses an offset or appears in a comment.
            conn.execute(text('SET SESSION max_execution_time=15000'))
            cursor = conn.execute(text(sql))
            return [dict(row) for row in cursor.mappings().fetchmany(100)]

    def tables_in_sql(self, sql, tables):
        return [t for t in tables if re.search(r'\b'+re.escape(t)+r'\b', sql, re.I)]

    def sample_rows(self, ds, tables):
        """每张涉及表取 3 行真实样例作智能体判定证据（仅触发路径执行，JSON 截断防提示词膨胀）。"""
        parts = []
        for t in tables[:3]:
            try:
                sample = dumps(self.execute(ds, f'SELECT * FROM `{t}` LIMIT 3'))
                parts.append(f'{t}：{sample[:500]}'+('…' if len(sample) > 500 else ''))
            except Exception:
                continue
        return '\n'.join(parts) or '无'

    def agent_correct(self, q, plan, sql, rows, tables, columns):
        """校验纠错智能体：执行结果可疑（0行/计0）时由 MAF 智能体诊断修正。

        触发门控与接受条件是不依赖 LLM 自律的客观护栏（见方案实验③的误纠实证）：
        修正 SQL 重走确定性改写+白名单校验+执行，仅当结果确有改善（0→N）
        才采用；任何失败（LLM 降级/校验拒绝/无改善）都保留原结果，不阻断主流程。
        """
        corrections = []
        for _ in range(MAX_AGENT_FIXES):
            if not suspicious_result(rows):
                break
            verdict = self.critic.judge(q, self.build_semantic_context(q), sql,
                                        describe_result(rows),
                                        self.sample_rows(plan['ds'], self.tables_in_sql(sql, tables)))
            if not verdict or verdict.get('verdict') != 'FIX' or not verdict.get('correctedSql'):
                break
            try:
                fixed = validate_sql(self.fix_id_card_year_prefix(plan['ds'], self.normalize_enum_literals(plan['ds'], verdict['correctedSql'])), tables, columns)
                new_rows = self.execute(plan['ds'], fixed)
            except Exception:
                logging.getLogger(__name__).warning('智能体修正SQL未通过校验/执行，保留原结果', exc_info=True)
                break
            if not improved(rows, new_rows):
                break
            corrections.append(dict(before=sql, after=fixed, reason=verdict['reason']))
            sql, rows = fixed, new_rows
        return sql, rows, corrections

    def links(self, codes):
        return [dict(label='去本体页看概念 '+c, route='/ontology?concept='+c) for c in list(dict.fromkeys(codes))[:2]]

    def fill_parse(self, result, query, used_concepts=()):
        """填充语义解析面板：概念匹配 + 关联概念关系。

        概念匹配三层归一（同一概念只保留最高优先级命中）：
        ① 概念名/编码原样命中问题文本；② bm_term 术语别名命中（业务
        方言→标准概念，如 客户→患者）；③ 兜底计入本次 SQL 实际用到
        表所映射的概念（match='映射'）。问「体检」而概念叫「检查报告」
        时，LLM 仍可按物理映射生成 SQL，面板靠②③层补齐展示。
        关系展示的是命中概念在本体中的邻域，不是本次 SQL 的实际路径；
        仅当关系两端都在 used_concepts 中时标 used=True（前端区分
        「本次查询/本体相邻」）。
        """
        try:
            concepts = self.rows(Concept, Concept.status == 'PUBLISHED')
            names = {c.code: c.name for c in concepts}
            hits, matched = [], set()

            def record(code, how):
                # 未发布概念不进面板；面板最多展示 6 个概念
                if code and code in names and code not in matched and len(hits) < 6:
                    hits.append(dict(code=code, name=names.get(code) or code, match=how))
                    matched.add(code)

            for c in concepts:
                how = '名称' if c.name and len(c.name) >= 2 and c.name in query else '编码' if c.code and len(c.code) >= 2 and c.code.lower() in query.lower() else None
                if how:
                    record(c.code, how)
                if len(hits) >= 6:
                    break
            for t in self.rows(Term):
                if t.term and len(t.term) >= 2 and t.term in query:
                    record(t.concept_code, '术语')
            for code in used_concepts:
                record(code, '映射')
            codes = [h['code'] for h in hits]
            rels = self.rows(Relation, or_(Relation.from_concept.in_(codes), Relation.to_concept.in_(codes)))[:8] if codes else []
            result['matchedConcepts'] = hits
            used = set(used_concepts)
            result['relations'] = [{'from': r.from_concept, 'fromName': names.get(r.from_concept, r.from_concept), 'relation': r.relation_name, 'to': r.to_concept, 'toName': names.get(r.to_concept, r.to_concept), 'used': r.from_concept in used and r.to_concept in used} for r in rels]
        except Exception:
            result.update(matchedConcepts=[], relations=[])

    def answer(self, q, analytics=False):
        if settings.semantic_asset_enhance:
            direct = self.metric_direct_answer(q)
            if direct is not None:
                return direct, False
        plan, snapshot = self._plan_query(q)
        if plan is None:
            return None, False
        def miss():
            MissService(self.session).record_miss(q, 'QUESTION', 'QA_ASK' if analytics else 'CS_ASK')
            return None, True
        if plan['mode'] == 'UNANSWERABLE' and self.coverage_hit(q):
            # 用词命中语义层却拒答，多为采样抖动：带提示再规划一次
            retry_plan, retry_snapshot = self._plan_query(q, insist=True)
            if retry_plan is not None and retry_plan['mode'] != 'UNANSWERABLE':
                plan, snapshot = retry_plan, retry_snapshot
        if plan['mode'] == 'UNANSWERABLE':
            return miss()
        if plan['mode'] == 'MODEL_ANSWER':
            return self.model_answer(q, plan, snapshot), False
        valid_entries = []
        if snapshot is not None:
            plan, snapshot, valid_entries, outcome = self._gate_query_citations(q, plan, snapshot)
            if outcome == 'insufficient':
                return self.insufficient_result(q, valid_entries), False
            if outcome == 'model':
                return self.model_answer(q, plan, snapshot, allow_retry=False), False
        tables, columns = self.allowed(plan['ds'])
        if not tables:
            return miss()
        try:
            rewritten = self.fix_id_card_year_prefix(plan['ds'], self.normalize_enum_literals(plan['ds'], plan['sql']))
            sql = validate_sql(rewritten, tables, columns)
            rows = self.execute(plan['ds'], sql)
        except Exception:
            logging.getLogger(__name__).warning('语义查询失败，降级能力菜单', exc_info=True)
            return miss()
        sql, rows, corrections = self.agent_correct(q, plan, sql, rows, tables, columns)
        if corrections and settings.semantic_asset_enhance:
            plan = dict(plan, semantics='按纠错后的最终 SQL 查询；原规划的业务资产引用已清除。')
        if valid_entries and not corrections:
            valid_entries, invalid, error = asset_context.verify_citations(self.session, snapshot, plan)
            if invalid or error:
                return self.insufficient_result(q, valid_entries), False
        total, view = len(rows), rows[:20]
        rows_json = dumps(view)
        if len(rows_json) > 3000:
            rows_json = rows_json[:3000]+'…'
        answer_prompt = f"用户问题：{q}\n查询语义：{plan['semantics']}\n执行SQL：{sql}\n结果行数：{total}"+('（仅展示前20行）' if total > 20 else '')+'\n结果JSON：'+rows_json
        if valid_entries:
            if corrections:
                valid_entries = []
            else:
                answer_prompt += ''.join(f'\n依据{asset_context.KIND_LABEL[e.kind]} {e.code}：{e.evidence}' for e in valid_entries)
                answer_prompt += asset_context.ASSET_ANSWER_ADDENDUM
        answer = self.llm.chat('CS_SEMANTIC_ANSWER', '你是医院信息平台的数据问答助手。严格基于给定查询结果用中文回答，先给结论再给关键数字，口语化，不超过200字。结果里没有的信息不要编造，结果为0条就如实说没有。', answer_prompt)
        if answer is None:
            answer = f"按本体映射到 {plan['ds']} 查询，没有符合条件的记录。（{plan['semantics']}）" if total == 0 else f"按本体映射查询到 {total} 条记录（{plan['semantics']}）。首条明细：{java_value(view[0])}"
        used = self.tables_in_sql(sql, tables)
        codes = [m.concept_code for m in self.rows(Mapping, Mapping.ds_code == plan['ds'], Mapping.table_name.in_(used))] if used else []
        result = dict(question=q, intent='语义查询', router='SEMANTIC', answer=answer,
            evidence=[dict(label='执行SQL', value=sql), dict(label='数据源', value=plan['ds']+' / '+','.join(used)), dict(label='结果行数', value=str(total)+('（展示前20行）' if total > 20 else ''))],
            links=self.links(codes), semantics=plan['semantics'], rows=view, corrections=corrections)
        if valid_entries and not corrections:
            # 纠错采纳新 SQL 后原规划引用不继承：清空该查询的资产引用（设计方案 4.4）
            result['citations'] = asset_context.build_citations(valid_entries)
            result['evidence'] += [dict(label=f'依据{asset_context.KIND_LABEL[e.kind]} {e.code}', value=e.evidence) for e in valid_entries]
        self.fill_parse(result, q+' '+plan['semantics'], codes)
        return result, False

    def model_answer(self, q, plan, snapshot=None, allow_retry=True):
        if not plan['conclusion']:
            return None
        valid_entries = []
        if settings.semantic_asset_enhance:
            if plan.get('evidenceStatus') in ('INSUFFICIENT', 'CONFLICT'):
                valid, _, _ = asset_context.verify_citations(self.session, snapshot, plan)
                return self.insufficient_result(q, valid)
            # 空快照也必须核验：没有可引用资产不能成为绕过依据不足保护的理由。
            declared = asset_context.declared_codes(plan)
            if any(v is None for v in declared.values()):
                valid_entries, invalid, err = [], [], '引用字段类型错误'
            elif any(declared[k] for k in ('rule', 'axiom', 'action')):
                valid_entries, invalid, err = asset_context.verify_citations(self.session, snapshot, plan)
            else:
                valid_entries, invalid, err = [], [], None
            if err or invalid:
                if not allow_retry:
                    return self.insufficient_result(q, valid_entries)
                # 出现无效引用：重规划一次并明确指出失效项；不得仅删引用后保留原结论
                pointed = ', '.join(invalid) if invalid else '引用字段类型错误'
                note = (f'\n注意：你上次 MODEL_ANSWER 引用的资产编码未通过核验（{pointed}）。'
                        '请基于本次上下文重新作答，只引用真实出现的编码；确无有效依据时在 semantics 中说明依据不足。')
                retry_plan, retry_snapshot = self._plan_query(q, note=note)
                if retry_plan is not None and retry_plan['mode'] == 'MODEL_ANSWER' and retry_plan['conclusion']:
                    valid_entries, invalid, err = asset_context.verify_citations(self.session, retry_snapshot, retry_plan)
                    if err or invalid or not valid_entries or retry_plan.get('evidenceStatus') in ('INSUFFICIENT', 'CONFLICT'):
                        return self.insufficient_result(q, valid_entries)
                    plan, snapshot = retry_plan, retry_snapshot
                else:
                    return self.insufficient_result(q, valid_entries)
            elif not valid_entries:
                # 未声明任何有效引用：保守返回依据不足，不输出无依据的结构判断
                return self.insufficient_result(q, [])
        sql, rows = None, None
        tables, columns = self.allowed(plan['ds']) if plan['ds'] else ([], set())
        if plan['verifySql'] and tables:
            try:
                sql = validate_sql(self.fix_id_card_year_prefix(plan['ds'], plan['verifySql']), tables, columns)
                rows = self.execute(plan['ds'], sql)
            except Exception:
                sql, rows = None, None
        probe = '无（纯结构判断）' if sql is None else sql+' → '+dumps(rows)
        if valid_entries:
            valid_entries, invalid, error = asset_context.verify_citations(self.session, snapshot, plan)
            if invalid or error:
                return self.insufficient_result(q, valid_entries)
        grounding = ''.join(f"\n依据{asset_context.KIND_LABEL[e.kind]} {e.code}：{e.evidence}" for e in valid_entries)
        answer = self.llm.chat('CS_SEMANTIC_ANSWER', '你是医院信息平台的业务规则解答助手。基于给定的本体结构判断与验证探针结果用中文回答，先给「可以/不可以」的结论，再给依据（结构口径+探针数字），口语化，不超过200字。不要编造探针没有的数字。', f"用户问题：{q}\n本体结构判断：{plan['semantics']}\n初步结论：{plan['conclusion']}"+grounding+f"\n验证探针：{probe}"+(asset_context.ASSET_ANSWER_ADDENDUM if valid_entries else ''))
        if answer is None:
            answer = plan['conclusion']+'（结构依据：'+plan['semantics']+'）'
            if valid_entries:
                answer += '（依据：'+'；'.join(e.code for e in valid_entries)+'）'
            if rows is not None:
                answer += ' 验证探针返回：'+(java_value(rows[0]) if rows else '无记录')
        evidence = [dict(label='结构依据', value=plan['semantics'])]
        if sql is not None:
            evidence += [dict(label='执行SQL', value=sql), dict(label='结果行数', value=str(len(rows))+('，首行 '+java_value(rows[0]) if rows else ''))]
        evidence += [dict(label=f'依据{asset_context.KIND_LABEL[e.kind]} {e.code}', value=e.evidence) for e in valid_entries]
        if valid_entries:
            evidence.append(dict(label='处理说明', value='引用编码已按本次上下文快照与当前发布状态核验'))
        description = plan['semantics']+' '+plan['conclusion']
        codes = [c.code for c in self.rows(Concept, Concept.status == 'PUBLISHED') if c.code in description or (c.name is not None and c.name in description)]
        result = dict(question=q, intent='语义查询', router='SEMANTIC', answer=answer, evidence=evidence, links=self.links(codes))
        if valid_entries:
            result['citations'] = asset_context.build_citations(valid_entries)
        return result
