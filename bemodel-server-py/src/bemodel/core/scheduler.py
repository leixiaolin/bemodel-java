import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from bemodel.config import settings
from bemodel.core.database import engine


def cron_trigger(expression):
    second, minute, hour, day, month, weekday = expression.split()
    # Spring Sunday=0/7, APScheduler Monday=0. Expand numeric lists/ranges before conversion.
    if weekday not in {"*", "?"}:
        weekdays = set()
        names = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
        for term in weekday.upper().split(","):
            for name, number in names.items():
                term = term.replace(name, str(number))
            interval, _, step = term.partition("/")
            if interval == "*":
                start, end = 0, 7
            elif "-" in interval:
                start, end = map(int, interval.split("-"))
            else:
                start = int(interval)
                end = 7 if step else start
            weekdays.update((n - 1) % 7 for n in range(start, end + 1, int(step or 1)))
        weekday = ",".join(map(str, sorted(weekdays)))
    return CronTrigger(second=second, minute=minute, hour=hour, day="*" if day == "?" else day,
                       month=month, day_of_week="*" if weekday == "?" else weekday, timezone="Asia/Shanghai")


def start_scheduler():
    if settings.disable_scheduler:
        return None
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    def inspect():
        from bemodel.notice.services import InspectService
        try:
            with Session(engine, expire_on_commit=False) as session:
                InspectService(session).run_all()
        except Exception:
            logging.getLogger(__name__).exception("定时巡检失败（下个周期重试）")
    scheduler.add_job(inspect, cron_trigger(settings.inspect_cron))
    scheduler.start()
    return scheduler
