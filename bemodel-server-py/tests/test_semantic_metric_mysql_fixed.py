"""在 fixture 保护的 13317 MySQL 内使用连接级临时表，业务数据不落持久表。"""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from bemodel.config import settings
from bemodel.cs.semantic import SemanticQaService
from bemodel.ontology.entities import Metric


@pytest.mark.parametrize('zero,expected', [(False,3),(True,0)])
def test_fixed_mysql_metric_value_and_no_monitor_write(mysql_session,monkeypatch,zero,expected):
    monkeypatch.setattr(settings,'semantic_asset_enhance',True)
    monkeypatch.setattr(settings,'deepseek_api_key','')
    svc=SemanticQaService(mysql_session)
    metric=mysql_session.query(Metric).filter_by(metric_code='CANCEL_NOT_REFUND').one()
    before=(metric.last_val,metric.last_eval_at)
    with mysql_session.get_bind().connect() as conn:
        created=[]
        try:
            conn.execute(text('CREATE TEMPORARY TABLE medical_order(order_id VARCHAR(20),order_status VARCHAR(2),create_time DATE,dept VARCHAR(20))'))
            created.append('medical_order')
            conn.execute(text('CREATE TEMPORARY TABLE fee_detail(order_id VARCHAR(20),fee_status VARCHAR(2))'))
            created.append('fee_detail')
            conn.execute(text("INSERT INTO medical_order VALUES ('O1','2','2026-10-10','内科'),('O2','2','2026-10-09','内科'),('O3','2','2026-08-01','外科'),('O4','2','2026-10-10','外科'),('O5','1','2026-10-10','内科')"))
            conn.execute(text("INSERT INTO fee_detail VALUES ('O1','1'),('O2','1'),('O3','1'),('O4','2'),('O5','1')"))
            if zero:
                conn.execute(text("UPDATE fee_detail SET fee_status='2'"))
            rows_before=list(conn.execute(text('SELECT * FROM fee_detail ORDER BY order_id')))
            # 复用原 execute 的 MySQL 15 秒超时、fetchmany(100)，仅绑定临时表所在连接。
            monkeypatch.setattr(svc.ds,'jdbc',lambda ds:SimpleNamespace(connect=lambda:nullcontext(conn)))
            monkeypatch.setattr(svc.llm,'chat',lambda *args:pytest.fail('直查不应调用模型'))
            result,missed=svc.answer('取消未退费有多少笔')
            evidence={e['label']:e['value'] for e in result['evidence']}
            assert not missed and evidence['实测值']==f'{expected}笔'
            assert evidence['单位']=='笔' and evidence['统计范围']=='当前全量数据快照（不限发生日期）'
            assert evidence['执行SQL'].endswith('LIMIT 100')
            assert list(conn.execute(text('SELECT * FROM fee_detail ORDER BY order_id')))==rows_before
            mysql_session.refresh(metric)
            assert (metric.last_val,metric.last_eval_at)==before
        finally:
            for table in reversed(created):
                conn.execute(text('DROP TEMPORARY TABLE '+table))
