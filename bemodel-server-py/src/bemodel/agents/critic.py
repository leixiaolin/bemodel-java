"""校验纠错智能体（SQL Critic）：问数执行结果可疑时诊断并修正 SQL。

判定逻辑（提示词构建、JSON 解析、触发/接受纯函数）不依赖智能体框架，
LLM 执行经 runtime 的 MAF 适配层，审计/降级语义与 DeepSeekClient 一致。
"""

import json

# 触发门控 + 接受条件 + 轮次上限是三道不依赖 LLM 自律的客观护栏（见方案实验③）：
# 结果正常时智能体不运行；修正 SQL 重走完整校验管线；仅结果确有改善才采用。
MAX_AGENT_FIXES = 2

CRITIC_SYSTEM_PROMPT = (
    '你是语义问数的SQL校验纠错智能体。输入：用户问题、本体物理映射、生成的SQL、'
    '该SQL在业务库的真实执行结果、真实样例数据。\n'
    '逐步检查：1) 列语义是否被误用（身份证号/编码列/枚举码/日期的匹配方式）；'
    '2) 枚举条件是否用了中文而库里存码值；'
    '3) 执行结果是否与问题和样例数据矛盾（如返回0行但样例明显存在该数据）。\n'
    '只在高置信认为有错时纠正；无法确定时判OK。'
    '纠错后的SQL仍必须只使用映射中列出的表和列，保留LIMIT。\n'
    '只输出JSON：{"verdict":"OK"} 或 {"verdict":"FIX","correctedSql":"...","reason":"一句话原因"}'
)


def _single_zero_count(rows):
    """单行单列且数值为 0 的聚合结果（如 COUNT(*)=0）：可疑信号之一。"""
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    value = next(iter(rows[0].values()))
    return isinstance(value, (int, float)) and value == 0


def suspicious_result(rows):
    """执行结果可疑：明细 0 行，或 COUNT 类聚合为 0。结果正常时智能体不运行。"""
    return not rows or _single_zero_count(rows)


def improved(old_rows, new_rows):
    """接受条件：原结果可疑且修正后有数据（0行/计0 → 非空），否则保留原结果。"""
    return suspicious_result(old_rows) and not suspicious_result(new_rows)


def describe_result(rows):
    """把执行结果文本化为智能体证据，如「返回 1 行：n=0」或「3 行，首行：…」。"""
    if not rows:
        return '0 行（没有任何记录）'
    if len(rows) == 1 and len(rows[0]) == 1:
        key, value = next(iter(rows[0].items()))
        return f'返回 1 行：{key}={value}'
    head = '; '.join(f'{k}={v}' for k, v in list(rows[0].items())[:6])
    return f'{len(rows)} 行，首行：{head}'


def parse_verdict(response):
    """解析智能体输出；LLM 不可用时 response 为 None，非法输出归一为 PARSE_FAIL。"""
    if not response:
        return None
    start, end = response.find('{'), response.rfind('}')
    if start < 0 or end <= start:
        return {'verdict': 'PARSE_FAIL'}
    try:
        verdict = json.loads(response[start:end + 1])
    except ValueError:
        return {'verdict': 'PARSE_FAIL'}
    if not isinstance(verdict, dict):
        return {'verdict': 'PARSE_FAIL'}
    verdict['verdict'] = str(verdict.get('verdict') or '').strip().upper()
    verdict['correctedSql'] = str(verdict.get('correctedSql') or '').strip()
    verdict['reason'] = str(verdict.get('reason') or '').strip()
    return verdict


class SqlCritic:
    """问数纠错智能体。judge 失败/降级返回 None 或 PARSE_FAIL，编排层据此保留原结果。"""

    def __init__(self, session):
        self.session = session

    def judge(self, question, context, sql, result_desc, samples):
        from .runtime import critic_chat
        user_prompt = (f'用户问题：{question}\n\n{context}\n\n生成的SQL：{sql}\n\n'
                       f'真实执行结果：{result_desc}\n\n真实样例数据：{samples}')
        return parse_verdict(critic_chat(self.session, CRITIC_SYSTEM_PROMPT, user_prompt))
