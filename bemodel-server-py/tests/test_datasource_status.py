from types import SimpleNamespace

import pytest

from bemodel.auth.jwt_service import JwtService
from bemodel.core.exceptions import BizException
from bemodel.datasource.entities import Datasource, Mapping, PhysicalColumn, PhysicalTable
from bemodel.datasource.services import DatasourceService, MappingService, SchemaScanService


def auth_headers(role="ADMIN"):
    token = JwtService().issue(SimpleNamespace(username="admin", display_name=None, role=role))
    return {"Authorization": "Bearer " + token}


def create_datasource(session, code="DS_TEST"):
    return DatasourceService(session).create({
        "dsCode": code,
        "dsName": "测试数据源",
        "productName": "TEST",
        "dbType": "MYSQL",
        "host": "127.0.0.1",
        "port": 3306,
        "dbName": "demo",
        "username": "root",
        "password": "secret",
    })


def test_datasource_status_and_soft_delete_api(client, session):
    create_datasource(session)
    headers = auth_headers()

    assert client.get("/api/datasource/list", headers=headers).json()["data"][0]["status"] == "ACTIVE"

    # VIEWER 只读：状态变更与删除均被 403 拦截
    assert client.patch("/api/datasource/DS_TEST/status", json={"status": "DISABLED"},
                        headers=auth_headers("VIEWER")).status_code == 403
    assert client.delete("/api/datasource/DS_TEST", headers=auth_headers("VIEWER")).status_code == 403

    disabled = client.patch("/api/datasource/DS_TEST/status", json={"status": "DISABLED"}, headers=headers).json()
    assert disabled["code"] == 0
    assert disabled["data"]["status"] == "DISABLED"

    listed = client.get("/api/datasource/list", headers=headers).json()["data"]
    assert len(listed) == 1 and listed[0]["dsCode"] == "DS_TEST"

    deleted = client.delete("/api/datasource/DS_TEST", headers=headers).json()
    assert deleted["code"] == 0
    assert client.get("/api/datasource/list", headers=headers).json()["data"] == []


def test_disabled_datasource_is_blocked_from_business_flows(session):
    create_datasource(session)
    ds = DatasourceService(session)
    ds.update_status("DS_TEST", "DISABLED")

    with pytest.raises(BizException, match="已失效"):
        ds.require("DS_TEST")
    with pytest.raises(BizException, match="已失效"):
        SchemaScanService(session).tables("DS_TEST")
    with pytest.raises(BizException, match="已失效"):
        SchemaScanService(session).columns("DS_TEST", "demo_table")
    with pytest.raises(BizException, match="已失效"):
        SchemaScanService(session).scan("DS_TEST")
    with pytest.raises(BizException, match="已失效"):
        MappingService(session).list("DS_TEST", "demo_table")
    with pytest.raises(BizException, match="已失效"):
        MappingService(session).save_batch([{
            "dsCode": "DS_TEST",
            "tableName": "demo_table",
            "columnName": "id",
            "conceptCode": "PATIENT",
            "attrCode": "id",
        }])

    ds.update_status("DS_TEST", "ACTIVE")
    assert ds.require("DS_TEST").ds_code == "DS_TEST"


def test_soft_deleted_datasource_is_hidden_and_blocked(session):
    create_datasource(session)
    session.add(PhysicalTable(ds_code="DS_TEST", table_name="demo_table"))
    session.add(PhysicalColumn(ds_code="DS_TEST", table_name="demo_table", column_name="id"))
    session.add(Mapping(ds_code="DS_TEST", table_name="demo_table", column_name="id", concept_code="PATIENT", attr_code="id"))
    session.commit()

    ds = DatasourceService(session)
    ds.soft_delete("DS_TEST")

    assert ds.list_all() == []
    with pytest.raises(BizException, match="不存在"):
        ds.require("DS_TEST")
    with pytest.raises(BizException, match="不存在"):
        SchemaScanService(session).tables("DS_TEST")
