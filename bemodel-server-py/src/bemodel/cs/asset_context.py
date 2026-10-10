"""资产上下文（规则/动作/公理）：选择、预算、请求内快照与引用核验。

- 快照随每次规划/重规划/纠错请求独立构建（含实际送入模型的资产条目），
  不跨请求共享；引用核验以「本次快照 + 当前库内状态」为准，被裁剪的
  资产不可引用，内容变化的资产视为失效。
- 资产文本作为数据区拼入语义上下文；补充指令（ASSET_PLAN_ADDENDUM/
  ASSET_ANSWER_ADDENDUM）放在数据区之外，资产自由文本不覆盖 SQL 护栏。
- 全部确定性实现（排序/裁剪/核验不依赖 LLM）。
"""

from dataclasses import dataclass, field

from bemodel.core.base_dao import BaseDAO
from bemodel.modeling.entities import Action, Axiom, Rule

MAX_ENTRIES = 30           # 每类资产条目上限
ENTRY_CHAR_BUDGET = 2000   # 单条字符预算：超限整条省略，不截断关键约束
TOTAL_CHAR_BUDGET = 12000  # 新增资产文本总预算
MAX_CITED_CODES = 10       # 规划 JSON 每类引用编码数上限

KIND_LABEL = {'rule': '规则', 'axiom': '公理', 'action': '动作'}

# 规划补充指令：编号顺接 cs/prompts.py 基础模板的 1-9（设计方案 4.5）。
ASSET_PLAN_ADDENDUM = '''
补充规则（上下文中【业务规则】【概念公理】【状态动作】段的使用约定）：
10. 规则是业务条件依据：先区分「正常状态口径」「违例筛选条件」与问题实际意图（如问违例存量就不能把合规条件加进 WHERE），再决定是否以及如何使用规则口径翻译条件。
11. 物理枚举码一律以【物理映射】段的码表为准；【状态动作】的描述不能覆盖映射。前置状态只是动作约束之一，空前置状态不等于无限制。
12. 【概念公理】只提供概念间语义约束（依赖/互斥/因果/继承），JOIN 路径必须以【物理映射】中的实际键为准，公理不能替代物理键证据。
13. 只能引用本次上下文中真实出现的资产编码：QUERY 可附 "ruleCodes":["RULE-XXX"]，MODEL_ANSWER 可附 "axiomCodes":["AX-XXX"]/"ruleCodes":["RULE-XXX"]/"actionCodes":["ACT-XXX"]，结论必须与所引条目一致（含条件与例外）；依据不足、条目冲突或统计范围不明时明确说明，不编造编码，用不上就不输出这些字段。
'''

# 作答补充指令：结论须覆盖所依据资产的条件与例外。
ASSET_ANSWER_ADDENDUM = '\n注意：回答结论须覆盖所依据资产的条件与例外；引用编码与提供的证据条目保持一致，不得引入证据之外的业务断言。'


@dataclass
class AssetEntry:
    kind: str        # 'rule' | 'axiom' | 'action'
    code: str
    label: str       # 引用徽章/证据用名称
    line: str        # 送入模型的一行文本
    evidence: str    # 证据条目正文
    route: str


@dataclass
class AssetSnapshot:
    entries: list = field(default_factory=list)
    text: str = ''
    omitted: dict = field(default_factory=dict)

    @property
    def by_code(self):
        return {e.code: e for e in self.entries}


def _two_grams(text):
    return {text[i:i+2] for i in range(len(text)-1)} if text and len(text) > 1 else set()


def _score(question_grams, text):
    grams = _two_grams(text)
    return len(question_grams & grams) if grams else 0


def _rule_line(r):
    line = f"- {r.rule_code}「{r.name}」[{r.concept_code}|{r.rule_type}]: {r.expression}"
    if (r.metric_code or '').strip():
        line += f"（指标:{r.metric_code}）"
    return line


def _axiom_line(a):
    return f"- {a.axiom_code}[{a.axiom_type}] {a.subject}—{a.predicate}→{a.object}: {a.description}"


def _action_line(a):
    return (f"- {a.action_code}「{a.name}」[{a.concept_code}] "
            f"{a.from_status or '无前置'}→{a.to_status}（触发:{a.trigger_desc}）: {a.description}")


def _collect(session, question):
    """挑选本次送入模型的资产条目：PUBLISHED → 相关性排序 → 条目/总预算裁剪。

    相关性 = 问题二字元组与条目检索文本的元组重合数（降序），平分按编码
    升序，纯确定性。超预算条目整体省略并计数，不截断关键约束。
    """
    grams = _two_grams(question or '')
    candidates = {
        'rule': [(_score(grams, ' '.join(filter(None, (r.name, r.expression, r.concept_code)))), r.rule_code, r, _rule_line)
                 for r in BaseDAO(session, Rule).select_list(Rule.status == 'PUBLISHED')],
        'axiom': [(_score(grams, ' '.join(filter(None, (a.subject, a.predicate, a.object, a.description, a.axiom_code)))), a.axiom_code, a, _axiom_line)
                  for a in BaseDAO(session, Axiom).select_list(Axiom.status == 'PUBLISHED')],
        'action': [(_score(grams, ' '.join(filter(None, (a.name, a.description, a.trigger_desc, a.concept_code)))), a.action_code, a, _action_line)
                   for a in BaseDAO(session, Action).select_list(Action.status == 'PUBLISHED')],
    }
    sections = {
        'rule': '【业务规则】（已发布业务口径：业务条件的翻译基准与违例筛选依据，答案可引用编码）',
        'axiom': '【概念公理】（概念间结构约束：依赖/互斥/因果/继承；不替代物理 JOIN 键）',
        'action': '【状态动作】（概念状态机：前置状态→目标状态与触发说明；「能不能做某操作」按前置状态判断）',
    }
    entries, omitted, texts, used = [], {}, [], 0
    for kind in ('rule', 'axiom', 'action'):
        ranked = sorted(candidates[kind], key=lambda item: (-item[0], item[1]))
        kept = []
        for item in ranked[:MAX_ENTRIES]:
            line = item[3](item[2])
            if len(line) > ENTRY_CHAR_BUDGET or used + len(line) + 1 > TOTAL_CHAR_BUDGET:
                continue
            used += len(line) + 1
            kept.append((item, line))
        omitted[kind] = len(ranked) - len(kept)
        if not kept:
            continue
        texts.append('\n' + sections[kind])
        for item, line in kept:
            texts.append(line)
            row, code = item[2], item[1]
            if kind == 'rule':
                entries.append(AssetEntry(kind, code, row.name, line, f"{row.name}：{row.expression}",
                                          '/ontology?tab=rules&assetCode=' + code))
            elif kind == 'axiom':
                entries.append(AssetEntry(kind, code, f"{row.subject}—{row.predicate}→{row.object}", line,
                                          f"{row.subject} {row.predicate} {row.object}：{row.description}",
                                          '/ontology?tab=axioms&assetCode=' + code))
            else:
                entries.append(AssetEntry(kind, code, row.name, line,
                                          f"{row.from_status or '无前置'}→{row.to_status}（触发:{row.trigger_desc}）：{row.description}",
                                          '/ontology?tab=actions&assetCode=' + code))
    return AssetSnapshot(entries=entries, text=(''.join(texts) if texts else ''), omitted=omitted)


def build_asset_snapshot(session, question):
    """构建请求内资产快照；无合格条目时 text 为空串（上下文逐字节不变）。"""
    return _collect(session, question)


def declared_codes(plan):
    """读取规划 JSON 声明的引用编码；类型非法的类别返回 None（视为核验失败）。"""
    out = {}
    for key, kind in (('ruleCodes', 'rule'), ('axiomCodes', 'axiom'), ('actionCodes', 'action')):
        value = plan.get(key) if isinstance(plan, dict) else None
        if value is None:
            out[kind] = []
        elif isinstance(value, list) and all(isinstance(c, str) and c.strip() for c in value):
            out[kind] = list(dict.fromkeys(c.strip() for c in value))
        else:
            out[kind] = None
    return out


def _fresh_line(session, kind, code):
    """按当前库内容重建条目行；资产被删/未发布/内容变化时返回 None。"""
    if kind == 'rule':
        row = BaseDAO(session, Rule).select_one(Rule.rule_code == code, Rule.status == 'PUBLISHED')
        return _rule_line(row) if row else None
    if kind == 'axiom':
        row = BaseDAO(session, Axiom).select_one(Axiom.axiom_code == code, Axiom.status == 'PUBLISHED')
        return _axiom_line(row) if row else None
    row = BaseDAO(session, Action).select_one(Action.action_code == code, Action.status == 'PUBLISHED')
    return _action_line(row) if row else None


def verify_citations(session, snapshot, plan):
    """引用核验：编码必须属于本次快照（被裁剪不可引用），且当前库内仍为
    PUBLISHED、内容与快照一致。展示的引用/证据/链接全部由服务端从快照生成，
    不采信模型提供的名称、正文或 URL。

    返回 (valid_entries, invalid_codes, error)；invalid/error 非空时调用方
    按设计方案 4.4 重规划或转「依据不足」。
    """
    declared = declared_codes(plan)
    invalid, error = [], None
    if any(v is None for v in declared.values()):
        return [], [], '引用编码字段类型错误（须为字符串数组）'
    if any(len(v) > MAX_CITED_CODES for v in declared.values()):
        return [], [], f'引用编码数量超过上限{MAX_CITED_CODES}'
    valid = []
    for kind in ('rule', 'axiom', 'action'):
        for code in declared[kind]:
            entry = snapshot.by_code.get(code) if snapshot else None
            if entry is None or entry.kind != kind:
                invalid.append(code)
                continue
            if _fresh_line(session, kind, code) != entry.line:
                invalid.append(code)
                continue
            valid.append(entry)
    return valid, invalid, error


def build_citations(valid_entries, metric_citation=None):
    """组装响应 citations 字段（服务端生成，含资产级深链）。"""
    citations = {}
    if metric_citation:
        citations['metric'] = metric_citation
    for kind, key in (('rule', 'rules'), ('axiom', 'axioms'), ('action', 'actions')):
        items = [dict(code=e.code, name=e.label, route=e.route) for e in valid_entries if e.kind == kind]
        if items:
            citations[key] = items
    return citations
