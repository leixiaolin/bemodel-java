import pytest
from bemodel.cs.semantic import SemanticQaService
from bemodel.cs.sql_validation import validate_sql
from bemodel.core.exceptions import BizException
from bemodel.datasource.entities import Mapping

TABLES = {'fee_detail', 'medical_order', 'inpatient'}
COLUMNS = set('fee_id order_id inhos_no item_name amount fee_status order_status order_type create_time patient_name sex dept_code'.split())


@pytest.mark.parametrize('sql', [
    "SELECT item_name, amount FROM fee_detail WHERE fee_status = '1'",
    "SELECT item_name FROM fee_detail WHERE item_name = 'x; DROP TABLE fee_detail--'",
    'SELECT item_name FROM fee_detail -- WHERE 1=1; DELETE FROM fee_detail',
    "SELECT o.order_id, o.create_time FROM medical_order o WHERE o.order_status = '2'",
    'SELECT fee_status, COUNT(*) cnt, SUM(amount) total FROM fee_detail GROUP BY fee_status ORDER BY total DESC',
    "SELECT f.item_name, f.amount FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'",
    "SELECT `item_name` FROM `fee_detail` WHERE `fee_status` = '1'",
])
def test_java_valid_queries(sql):
    assert validate_sql(sql, TABLES, COLUMNS) == sql+' LIMIT 100'


@pytest.mark.parametrize('sql', [
    'DELETE FROM fee_detail', 'UPDATE fee_detail SET amount = 0',
    'SELECT amount FROM fee_detail; DROP TABLE fee_detail',
    "SELECT amount INTO OUTFILE '/tmp/x' FROM fee_detail", 'SELECT * FROM user_passwords',
    'SELECT secret_col FROM fee_detail', 'SELECT item_name, secret_col FROM fee_detail',
    "SELECT item_name FROM fee_detail WHERE secret_col = '1'", 'SELECT f.secret_col FROM fee_detail f',
])
def test_java_rejected_queries(sql):
    with pytest.raises(BizException):
        validate_sql(sql, TABLES, COLUMNS)


def test_java_limit_clamping():
    assert validate_sql('SELECT item_name FROM fee_detail LIMIT 500', TABLES, COLUMNS).endswith('LIMIT 100')
    assert validate_sql('SELECT item_name FROM fee_detail LIMIT 20', TABLES, COLUMNS).endswith('LIMIT 20')


def test_enum_literal_uses_current_table_value_map(session):
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_item_result', column_name='abnormal',
                        concept_code='CHECK_REPORT', attr_code='abnormal',
                        value_map='{"1":"异常","0":"正常"}', confirmed=1, source='MANUAL'))
    session.commit()

    sql = ("SELECT COUNT(DISTINCT r.exam_no) AS abn_exam_cnt FROM peis_item_result r "
           "WHERE r.abnormal = 'Y' LIMIT 100")

    assert SemanticQaService(session).normalize_enum_literals('DS_PEIS', sql) == (
        "SELECT COUNT(DISTINCT r.exam_no) AS abn_exam_cnt FROM peis_item_result r "
        "WHERE r.abnormal = '1' LIMIT 100"
    )


def test_enum_literal_accepts_chinese_label(session):
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_item_result', column_name='abnormal',
                        concept_code='CHECK_REPORT', attr_code='abnormal',
                        value_map='{"1":"异常","0":"正常"}', confirmed=1, source='MANUAL'))
    session.commit()

    sql = "SELECT exam_no FROM peis_item_result WHERE abnormal = '异常'"

    assert SemanticQaService(session).normalize_enum_literals('DS_PEIS', sql) == (
        "SELECT exam_no FROM peis_item_result WHERE abnormal = '1'"
    )
