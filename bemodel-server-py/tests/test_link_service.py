from uuid import uuid4
from bemodel.link.services import LinkService
from bemodel.link.entities import LinkNode, LinkRel
from bemodel.core.base_dao import BaseDAO


def test_duplicate_relation_recovers_and_preserves_mysql_sequence(mysql_session):
    service = LinkService(mysql_session)
    prefix = 'TEST-LINK-' + uuid4().hex[:10]
    refs = [prefix + str(i) for i in range(3)]
    edges = BaseDAO(mysql_session, LinkRel)
    try:
        for ref in refs:
            service.insert(dict(nodeType='EVENT', refNo=ref, title='验收合成事件', conceptCode='MEDICAL_ORDER'))
        first = service.add_rel(refs[0], refs[1], 'CAUSES', 'original')
        duplicate = service.add_rel(refs[0], refs[1], 'CAUSES', 'ignored')
        assert duplicate.id == first.id and duplicate.remark == 'original'
        following = service.add_rel(refs[1], refs[2], 'CAUSES', 'next')
        assert following.id > first.id + 1
        assert len(service.trace(refs[0])['edges']) == 2
    finally:
        edges.delete(LinkRel.from_ref_no.in_(refs))
        service.delete(LinkNode.ref_no.in_(refs))
