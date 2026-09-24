from types import SimpleNamespace

from bemodel.auth.jwt_service import JwtService
from bemodel.cs.semantic import SemanticQaService
from bemodel.datasource.entities import Mapping
from bemodel.datasource.services import DatasourceService


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


def test_value_map_round_trip_via_api(client, session):
    """页面入口链路：保存映射携带 valueMap -> 列表接口回显驼峰 valueMap。"""
    create_datasource(session)
    headers = auth_headers()

    saved = client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST",
        "tableName": "demo_table",
        "columnName": "status",
        "conceptCode": "ORDER",
        "attrCode": "status",
        "valueMap": '{"1":"异常","0":"正常"}',
        "confirmed": 1,
        "source": "MANUAL",
    }], headers=headers)
    assert saved.status_code == 200 and saved.json()["code"] == 0

    listed = client.get("/api/mapping/list", params={"dsCode": "DS_TEST", "tableName": "demo_table"},
                        headers=headers).json()["data"]
    assert len(listed) == 1
    assert listed[0]["columnName"] == "status"
    assert listed[0]["valueMap"] == '{"1":"异常","0":"正常"}'


def test_value_map_can_be_updated(client, session):
    """编辑映射入口：再次保存同列映射可更新 valueMap。"""
    create_datasource(session)
    headers = auth_headers()

    for value in ('{"1":"异常","0":"正常"}', '{"2":"已取消","1":"有效"}'):
        client.post("/api/mapping/batch", json=[{
            "dsCode": "DS_TEST",
            "tableName": "demo_table",
            "columnName": "status",
            "conceptCode": "ORDER",
            "attrCode": "status",
            "valueMap": value,
            "confirmed": 1,
            "source": "MANUAL",
        }], headers=headers)

    listed = client.get("/api/mapping/list", params={"dsCode": "DS_TEST", "tableName": "demo_table"},
                        headers=headers).json()["data"]
    assert len(listed) == 1
    assert listed[0]["valueMap"] == '{"2":"已取消","1":"有效"}'


def test_clearing_value_map_with_explicit_null(client, session):
    """显式传 valueMap=null 清空值映射（Python 端增强，绕过非空更新语义）。"""
    create_datasource(session)
    headers = auth_headers()

    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "valueMap": '{"1":"异常","0":"正常"}', "confirmed": 1, "source": "MANUAL",
    }], headers=headers)
    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "valueMap": None, "confirmed": 1, "source": "MANUAL",
    }], headers=headers)

    listed = client.get("/api/mapping/list", params={"dsCode": "DS_TEST", "tableName": "demo_table"},
                        headers=headers).json()["data"]
    assert listed[0]["valueMap"] is None


def test_clearing_value_map_with_blank_string(client, session):
    """纯空白字符串同样视为清空。"""
    create_datasource(session)
    headers = auth_headers()

    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "valueMap": '{"1":"异常","0":"正常"}', "confirmed": 1, "source": "MANUAL",
    }], headers=headers)
    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "valueMap": "   ", "confirmed": 1, "source": "MANUAL",
    }], headers=headers)

    listed = client.get("/api/mapping/list", params={"dsCode": "DS_TEST", "tableName": "demo_table"},
                        headers=headers).json()["data"]
    assert listed[0]["valueMap"] is None


def test_update_without_value_map_key_keeps_existing(client, session):
    """AI 批量采纳等不带 valueMap 键的更新不触碰已有值映射。"""
    create_datasource(session)
    headers = auth_headers()

    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "valueMap": '{"1":"异常","0":"正常"}', "confirmed": 1, "source": "MANUAL",
    }], headers=headers)
    client.post("/api/mapping/batch", json=[{
        "dsCode": "DS_TEST", "tableName": "demo_table", "columnName": "status",
        "conceptCode": "ORDER", "attrCode": "status",
        "confirmed": 1, "source": "AI",
    }], headers=headers)

    listed = client.get("/api/mapping/list", params={"dsCode": "DS_TEST", "tableName": "demo_table"},
                        headers=headers).json()["data"]
    assert listed[0]["valueMap"] == '{"1":"异常","0":"正常"}'
    assert listed[0]["source"] == "AI"


def test_semantic_qa_reads_value_map(session):
    """消费端：语义问数通过 value_map 把中文字面量规范回物理编码。"""
    from bemodel.cs.semantic import SemanticQaService

    create_datasource(session)
    session.add(Mapping(ds_code="DS_TEST", table_name="demo_table", column_name="status",
                        concept_code="ORDER", attr_code="status",
                        value_map='{"1":"异常","0":"正常"}', confirmed=1, source="MANUAL"))
    session.commit()

    qa = SemanticQaService(session)
    assert qa.enum_mappings("DS_TEST") == {("demo_table", "status"): {"1": "异常", "0": "正常"}}
    assert qa.normalize_enum_literals(
        "DS_TEST", "SELECT count(*) FROM demo_table WHERE status = '异常'"
    ) == "SELECT count(*) FROM demo_table WHERE status = '1'"
