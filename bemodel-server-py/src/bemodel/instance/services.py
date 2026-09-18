from collections import defaultdict
from datetime import datetime
import json
from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.services import ConceptService
from bemodel.ontology.entities import Attribute
from bemodel.datasource.entities import Mapping
from bemodel.datasource.services import DatasourceService


class InstanceService:
    def __init__(self, session):
        self.session = session

    def instances(self, code, table_name=None, page_num=1, page_size=10):
        concept = ConceptService(self.session).require(code)
        attrs = BaseDAO(self.session, Attribute).select_list(Attribute.concept_code == code, order=(Attribute.sort,))
        names = {}
        for a in attrs:
            names.setdefault(a.attr_code, a.attr_name)
        grouped = defaultdict(list)
        for m in BaseDAO(self.session, Mapping).select_list(Mapping.concept_code == code):
            grouped[(m.ds_code, m.table_name)].append(m)
        sources, ds = [], DatasourceService(self.session)
        for (source, table), cols in sorted(grouped.items(), key=lambda item: -len(item[1])):
            quote = lambda s: "`" + s.replace("`", "``") + "`"
            selected = ", ".join(quote(c) for c in dict.fromkeys(m.column_name for m in cols))
            offset = (page_num - 1) * page_size if not table_name or not table_name.strip() or table_name == table else 0
            rows = ds.query(source, f"SELECT {selected} FROM {quote(table)} LIMIT :size OFFSET :offset", {"size": page_size, "offset": offset})
            total = ds.query(source, f"SELECT COUNT(*) AS n FROM {quote(table)}")[0]["n"]
            projected = []
            for row in rows:
                values = {}
                for m in cols:
                    raw = row.get(m.column_name)
                    value = "-" if raw is None else (raw.isoformat(timespec="microseconds" if raw.microsecond else "seconds" if raw.second else "minutes") if isinstance(raw, datetime) else str(raw))
                    if raw is not None and m.value_map is not None:
                        try:
                            value = str(json.loads(m.value_map).get(value, value))
                        except (ValueError, AttributeError):
                            pass
                    values[names.get(m.attr_code, m.attr_code)] = value
                projected.append(values)
            sources.append({"dsCode": source, "tableName": table, "totalRows": total or 0, "instances": projected})
        return {"conceptCode": concept.code, "conceptName": concept.name, "definition": concept.definition,
                "sourceCount": len(sources), "sources": sources}
