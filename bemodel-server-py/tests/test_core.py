from datetime import datetime
from pathlib import Path
import pytest
from bemodel.core.crypto_service import CryptoService
from bemodel.core.java_compat import java_string_hash
from bemodel.core.migration import checksum, split_sql
from bemodel.core.result import to_camel_dict
from bemodel.core.state_machine import check
from bemodel.core.exceptions import BizException
from bemodel.core.database import transactional
from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.entities import Concept


def test_java_hash_utf16():
    assert java_string_hash("abc") == 96354
    assert java_string_hash("😀") == 1772899


def test_crypto():
    crypto = CryptoService("test")
    encrypted = crypto.encrypt("医疗💡")
    assert crypto.decrypt(encrypted) == "医疗💡"
    assert crypto.encrypt(encrypted) == encrypted
    assert crypto.decrypt("plain") == "plain"
    assert crypto.decrypt(None) is None
    with pytest.raises(ValueError):
        CryptoService("wrong").decrypt(encrypted)


def test_checksum_and_sql_quotes():
    assert checksum(" a\r\nb\r\n") == checksum(" a\nb\n")
    assert checksum(" a\nb") != checksum("a\nb")
    assert split_sql("-- hi;\nINSERT INTO t VALUES('a;b', 'it''s'); /* ; */ SELECT 1;") == ["INSERT INTO t VALUES('a;b', 'it''s')", "SELECT 1"]


def test_original_resources_identical():
    root = Path(__file__).resolve().parents[2]
    for source in (root / "bemodel-server/src/main/resources/db/migration").glob("*.sql"):
        assert source.read_bytes() == (root / "bemodel-server-py/src/bemodel/db/migration" / source.name).read_bytes()
    assert (root / "bemodel-server/src/main/resources/shacl/clinical-shapes.ttl").read_bytes() == (root / "bemodel-server-py/src/bemodel/resources/shacl/clinical-shapes.ttl").read_bytes()


@pytest.mark.parametrize("current,target", [("DRAFT", "REVIEW"), ("REVIEW", "DRAFT"), ("REVIEW", "PUBLISHED"), ("PUBLISHED", "DEPRECATED"), ("DEPRECATED", "DRAFT")])
def test_transitions(current, target):
    check(current, target)


def test_invalid_transition():
    with pytest.raises(BizException, match="不允许"):
        check("DRAFT", "PUBLISHED")


def test_dao_partial_update_and_rollback(session):
    dao = BaseDAO(session, Concept)
    row = dao.insert(dict(code="A", name="original", status="DRAFT"))
    assert row.id is not None
    dao.update_by_id(dict(id=row.id, name=None, status="REVIEW"))
    assert dao.select_by_id(row.id).name == "original"
    with pytest.raises(RuntimeError):
        with transactional(session):
            dao.insert(dict(code="B", name="rollback"))
            raise RuntimeError()
    assert dao.select_count(Concept.code == "B") == 0


def test_serialization():
    row = Concept(code="A", created_at=datetime(2026, 1, 1))
    result = to_camel_dict(row)
    assert result["createdAt"] == "2026-01-01T00:00:00"
    assert result["name"] is None
    assert to_camel_dict({"sql_column": 1}) == {"sql_column": 1}
def test_loaded_entity_null_update_uses_mybatis_not_null(session):
    from bemodel.core.base_dao import BaseDAO
    from bemodel.ontology.entities import Concept
    dao = BaseDAO(session, Concept)
    inserted = dao.insert(dict(code='NULL_UPDATE', name='original', definition='keep'))
    loaded = dao.select_by_id(inserted.id)
    loaded.name = 'changed'
    loaded.definition = None
    returned = dao.update_by_id(loaded)
    assert returned.definition is None
    session.expire_all()
    stored = dao.select_by_id(inserted.id)
    assert stored.name == 'changed' and stored.definition == 'keep'
