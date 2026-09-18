from collections import defaultdict
import json
from bemodel.core.base_dao import BaseDAO
from bemodel.modeling.entities import Release
from .entities import Concept, Term


class DriftService:
    def __init__(self, session):
        self.session = session

    def scan(self):
        terms = BaseDAO(self.session, Term).select_list()
        names = {c.code: c.name for c in BaseDAO(self.session, Concept).select_list()}
        grouped = defaultdict(lambda: defaultdict(list))
        for t in terms:
            if t.term is not None and t.concept_code is not None:
                grouped[t.term][t.concept_code].append(dict(conceptCode=t.concept_code,
                    conceptName=names.get(t.concept_code, t.concept_code), sourceProduct=t.source_product if t.source_product is not None else "-",
                    termType=t.term_type if t.term_type is not None else "-", codeSystem=t.code_system or ""))
        conflicts = [dict(term=term, conceptCount=len(groups), usages=[u for values in groups.values() for u in values])
                     for term, groups in grouped.items() if len(groups) > 1]
        conflicts.sort(key=lambda c: -c["conceptCount"])
        releases = BaseDAO(self.session, Release).select_list(order=(Release.id,))
        changes = []
        def index(release, key, id_field):
            try:
                return {row[id_field]: row for row in json.loads(release.snapshot_json or "{}").get(key, []) if row.get(id_field)}
            except (ValueError, TypeError, AttributeError):
                return {}
        for previous, current in zip(releases, releases[1:]):
            for key, id_field, kind, fields in [("concepts", "code", "概念", [("definition", "口径定义")]),
                ("metrics", "metricCode", "指标", [("definition", "口径定义"), ("formula", "计算公式")])]:
                before, after = index(previous, key, id_field), index(current, key, id_field)
                for code, row in after.items():
                    if code not in before:
                        continue
                    for field, label in fields:
                        old, new = before[code].get(field) or "", row.get(field) or ""
                        if old != new:
                            changes.append(dict(toReleaseId=current.id, versionTag=current.version_tag,
                                releasedAt=current.created_at.isoformat() if current.created_at else "", kind=kind,
                                code=code, name=row.get("name") or code, field=label, oldVal=old, newVal=new))
        changes.sort(key=lambda c: -c["toReleaseId"])
        return dict(termConflicts=conflicts, calibreChanges=changes, stats=dict(termConflictCount=len(conflicts),
            calibreChangeCount=len(changes), scannedTerms=len(terms), scannedReleases=len(releases)))
