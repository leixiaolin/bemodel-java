"""指标直查资格清单：问数主路直接执行指标探针的准入策略。

首期仅纳入经人工核对的 CANCEL_NOT_REFUND（探针=「医嘱已取消且费用仍正常」
的明细笔数，与指标定义一致，见种子 V3/V4）。其余种子指标不开放直查：
DISCHARGE_COUNT 探针无统计周期、LAB_CANCEL_RATE 探针是绝对量而非比例、
AVG_INP_FEE 精度/分母口径未核定——一律走语义规划。

资格不是指标编码本身，而是「指标资产当前内容与核对基准一致 + 相关枚举
映射含义不变」的运行时断言；任何不匹配使资格失效，问数回落语义规划并
记录原因。扩展准入必须更新本清单、核对依据与配套测试（策略版本+1）。
"""

import hashlib
import math
import re
from decimal import Decimal

from bemodel.core.base_dao import BaseDAO
from bemodel.datasource.entities import Mapping
from bemodel.datasource.services import parse_value_map
from bemodel.ontology.entities import Metric

POLICY_VERSION = 1

# 归一化只处理空白、标点和明确列出的礼貌/快照词（设计方案 4.2）；
# 「现在/当前/目前」仅允许解释为指标的当前数据快照，不代表当天发生量。
_STRIP_WORDS = ('请问', '麻烦', '帮我查一下', '帮我查', '帮查', '查一下', '告诉我',
                '现在', '当前', '目前', '究竟', '到底')
_PUNCT_RE = re.compile(r'[\s，。？！、；：,.?!;:（）()【】\[\]“”‘’"\']+')

# 合格指标的唯一批准别名（核心词，须出现在问句开头）与允许的问句尾。
# 归一化后问句必须恰好是「别名 + 允许尾」，残留任何未解释业务内容
# （时间/科室/患者/分组/比较/多指标/解释类问法）即不命中。
_METRIC_ALIASES = ('取消未退费',)
_QUESTION_TAILS = frozenset((
    '有多少笔', '多少笔', '笔数是多少', '笔数多少', '笔数有多少', '笔数有几笔', '有几笔',
    '有多少', '的费用有多少笔', '费用有多少笔', '费用多少', '的费用有多少', '笔数是多少呀',
))

# 核对基准：指标资产内容（definition/formula/ds_code/probe_sql）与相关枚举
# 映射的预期含义。任一字段变化即资格失效，需人工重核后更新本清单。
_QUALIFIED = {
    'CANCEL_NOT_REFUND': {
        'aliases': _METRIC_ALIASES,
        'phrase': '取消未退费',
        'unit': '笔',
        'scope': '当前全量数据快照（不限发生日期）',
        'numeric_type': 'non_negative_integer',
        'null_answer': '暂无可用实测值',
        'verified_basis': 'V3/V4 种子人工核对：探针=取消且未退费明细笔数，与定义一致',
        'expect': {
            'definition': '医嘱已取消但费用状态仍为正常的明细笔数，计费一致性核心监控指标，正常应为0。',
            'formula': 'COUNT(医嘱状态=已取消 AND 费用状态=正常)',
            'ds_code': 'DS_HIS',
            'probe_sql': "SELECT COUNT(*) FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id "
                         "WHERE o.order_status = '2' AND f.fee_status = '1'",
            # (数据源, 表, 列, 原始码, 标签须含关键词)：探针物理码的语义锚点
            'enums': (
                ('DS_HIS', 'medical_order', 'order_status', '2', '取消'),
                ('DS_HIS', 'fee_detail', 'fee_status', '1', '正常'),
            ),
        },
    },
}


def fingerprint(row):
    """指标资产内容的稳定摘要（sha256，固定编码），供评测报告与排查使用。"""
    payload = '|'.join((row.definition or '', row.formula or '', row.ds_code or '', row.probe_sql or ''))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def normalize_question(q):
    """归一化问句：去空白/标点、剥离明确列出的礼貌与快照词，其余内容原样保留。"""
    text = _PUNCT_RE.sub('', q or '')
    for word in _STRIP_WORDS:
        text = text.replace(word, '')
    return text


def match_question(q):
    """完整问法匹配：归一化后必须恰好是「批准别名 + 允许问句尾」。

    命中返回指标编码；别名须在句首（剥离快照词后），剩余部分必须完整
    等于某个允许尾，从而拒绝时间/科室/患者/分组/比较/多指标等未解释内容。
    禁止用 name_match 互含、LCS 或 def_match 之类模糊匹配触发直查。
    """
    text = normalize_question(q)
    if not text:
        return None
    for alias in sorted(_METRIC_ALIASES, key=len, reverse=True):
        if text.startswith(alias):
            rest = text[len(alias):]
            if rest in _QUESTION_TAILS:
                return 'CANCEL_NOT_REFUND'
    return None


def verify_qualified(session, code):
    """运行时核对资格：指标资产内容与核对基准逐项一致、枚举映射含义不变。

    返回 (policy, metric_row, fail_reason)；全部通过时 fail_reason 为 None，
    否则 metric_row 为 None 且 fail_reason 说明失效原因（回落规划时记录）。
    """
    policy = _QUALIFIED.get(code)
    if policy is None:
        return None, None, '指标不在直查资格清单中'
    row = BaseDAO(session, Metric).select_one(Metric.metric_code == code)
    if row is None:
        return policy, None, '指标不存在'
    if not (row.name or '').strip() or not (row.probe_sql or '').strip() or not (row.ds_code or '').strip():
        return policy, row, '指标必填字段缺失（name/probe_sql/ds_code）'
    expect = policy['expect']
    mismatches = [f'{field}与核对基准不一致'
                  for field in ('definition', 'formula', 'ds_code', 'probe_sql')
                  if (getattr(row, field) or '') != expect[field]]
    if mismatches:
        return policy, row, '；'.join(mismatches)
    for ds, table, column, code_value, keyword in expect['enums']:
        mappings = BaseDAO(session, Mapping).select_list(
            Mapping.ds_code == ds, Mapping.table_name == table, Mapping.column_name == column)
        value_map = {}
        for m in mappings:
            parsed = parse_value_map(m.value_map)
            if parsed:
                value_map.update(parsed)
        label = value_map.get(code_value)
        if label is None or keyword not in label:
            return policy, row, f'枚举映射含义变化：{ds}.{table}.{column}[{code_value}]≠{keyword}'
    return policy, row, None


def qualified_codes():
    return tuple(_QUALIFIED)


def check_result_value(rows, policy):
    """直查结果形态与类型校验（设计方案 4.3）：只接受恰好一行一列的有限数值。

    返回 (accepted, value, fail_reason)。NULL/空结果按资格记录处理（accepted=True，
    value=None，由调用方输出「暂无可用实测值」）；bool、字符串、NaN/Infinity、
    负数、非整数、多行、多列均拒绝，禁止取首行冒充整体指标。
    """
    if rows is None or len(rows) == 0:
        return True, None, None
    if len(rows) > 1:
        return False, None, f'返回{len(rows)}行，只接受单行单值'
    row = rows[0]
    if not isinstance(row, dict) or len(row) != 1:
        return False, None, f'返回{len(row) if isinstance(row, dict) else 0}列，只接受单行单值'
    value = next(iter(row.values()))
    if value is None:
        return True, None, None
    if isinstance(value, bool):
        return False, None, '布尔值不是可接受的指标数值'
    if isinstance(value, str):
        return False, None, '字符串不是可接受的指标数值'
    if isinstance(value, Decimal):
        if not value.is_finite():
            return False, None, '结果非有限数值'
        if value != value.to_integral_value():
            return False, None, f'结果{value}不是整数（口径要求非负整数）'
        value = int(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return False, None, '结果非有限数值'
        if not value.is_integer():
            return False, None, f'结果{value}不是整数（口径要求非负整数）'
        value = int(value)
    elif not isinstance(value, int):
        return False, None, f'不支持的数值类型{type(value).__name__}'
    if value < 0:
        return False, None, f'结果{value}为负数（口径要求非负整数）'
    return True, value, None
