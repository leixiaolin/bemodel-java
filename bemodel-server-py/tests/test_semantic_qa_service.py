import pytest
from bemodel.cs.sql_validation import validate_sql
from bemodel.core.exceptions import BizException

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
