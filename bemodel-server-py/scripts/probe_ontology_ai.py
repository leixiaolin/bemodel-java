"""Run the real configured model against isolated governance metadata."""
import json
import argparse
import time
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bemodel.main import create_app  # Registers ORM entities without running startup.
from bemodel.config import settings
from bemodel.core.database import Base
from bemodel.datasource.entities import Datasource, PhysicalTable, PhysicalColumn
from bemodel.datasource.governance import OntologyAnalysisService
from bemodel.datasource.governance_entities import OntologyAnalysisTask, OntologyChangeItem
from bemodel.llm.entities import LlmLog
from bemodel.ontology.entities import Domain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=int, default=1, choices=range(1, 9))
    parser.add_argument("--workflow", action="store_true", help="Also verify task and change-set persistence")
    args = parser.parse_args()
    print(json.dumps({"model": settings.deepseek_model,
                      "host": urlsplit(settings.deepseek_base_url).hostname,
                      "key_configured": bool(settings.deepseek_api_key.strip()),
                      "timeout": settings.ontology_analysis_timeout_seconds}), flush=True)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Datasource(ds_code="PROBE", ds_name="Isolated probe", db_type="MYSQL",
                               host="127.0.0.1", port=1, db_name="probe", username="unused",
                               password="unused", status="ACTIVE", deleted=0))
        session.add(Domain(code="IMPORT", name="Import", sort=99))
        for table_index in range(args.tables):
            table_name = "exam" if table_index == 0 else f"exam_{table_index}"
            session.add(PhysicalTable(ds_code="PROBE", table_name=table_name, table_comment="体检记录"))
            for index, (name, label) in enumerate((("exam_id", "体检编号"),
                                                ("exam_status", "体检状态"),
                                                ("exam_time", "体检时间")), 1):
                session.add(PhysicalColumn(ds_code="PROBE", table_name=table_name, column_name=name,
                                       column_comment=label, data_type="varchar", ordinal_position=index,
                                       is_pk=int(index == 1)))
        session.commit()
        started = time.monotonic()
        service = OntologyAnalysisService(session)
        if args.workflow:
            # No physical database is needed: exercise the scanned-schema workflow.
            settings.ontology_stats_max_columns = 0
            task = service.enqueue("PROBE", created_by="isolated-probe")
            service.run_next("isolated-probe")
            session.expire_all()
            task = session.get(OntologyAnalysisTask, task.id)
            suggestions = session.query(OntologyChangeItem).filter_by(change_set_id=task.change_set_id).all()
            error = task.error_message
            print(json.dumps({"task_status": task.status, "progress": task.progress,
                              "change_set_id": task.change_set_id}), flush=True)
            if task.status != "SUCCEEDED" or task.change_set_id is None:
                error = error or "Task did not succeed"
        else:
            suggestions, error = service.ai_analysis("PROBE", [])
        logs = session.query(LlmLog).all()
        print(json.dumps({"seconds": round(time.monotonic() - started, 2),
                          "suggestions": len(suggestions), "error": error,
                          "audit_success": [row.success for row in logs],
                          "response_digest": [row.response_digest for row in logs]}, ensure_ascii=True), flush=True)
        if error or not suggestions:
            raise SystemExit(1)
    engine.dispose()


if __name__ == "__main__":
    main()
