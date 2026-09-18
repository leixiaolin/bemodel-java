from bemodel.core.base_dao import BaseDAO
from bemodel.ontology.services import MetricService
from .entities import AlertNotice, InspectRun


class NoticeService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, AlertNotice)

    def unread_count(self):
        return self.select_count(AlertNotice.status == "未读")

    def mark_read(self, id):
        row = self.select_by_id(id)
        if row:
            row.status = "已读"
            self.update_by_id(row)

    def mark_all_read(self):
        rows = self.select_list(AlertNotice.status == "未读")
        for row in rows:
            row.status = "已读"
            self.update_by_id(row)
        return len(rows)

    def create_if_absent(self, code, name, value, threshold, message):
        if self.select_count(AlertNotice.metric_code == code, AlertNotice.status == "未读"):
            return False
        self.insert(AlertNotice(metric_code=code, metric_name=name, actual_value=value,
                                threshold=threshold, message=message, status="未读"))
        return True


class InspectService:
    def __init__(self, session):
        self.session = session

    def run_all(self):
        results = MetricService(self.session).evaluate_all()
        alarmed, created = 0, 0
        for row in results:
            if row.get("alarm") is not True:
                continue
            alarmed += 1
            message = (f"指标「{row['name']}」探针执行失败: {row['error']}" if row.get("error") is not None
                       else f"指标「{row['name']}」实测 {row.get('value')} 超阈值 {row.get('warnThreshold')}")
            created += NoticeService(self.session).create_if_absent(row["metricCode"], row["name"], row.get("value"), row.get("warnThreshold"), message)
        run = BaseDAO(self.session, InspectRun).insert(InspectRun(evaluated=len(results), alarmed=alarmed, notices_created=created))
        return {"evaluated": len(results), "alarmed": alarmed, "noticesCreated": created, "runId": run.id, "results": results}
