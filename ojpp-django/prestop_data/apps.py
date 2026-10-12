from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from django.apps import AppConfig


class PrestopDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "prestop_data"

    def ready(self):
        # Upstream caches active schedules per date for the life of the process, so a
        # long-running API worker never sees a newer timetable import. Re-key the cache
        # on the latest successful import, which the ingestion process records.
        from functools import lru_cache

        from django.db.models import Max

        from ojpp_common import util
        from prestop_data.models import GtfsImport

        compute = getattr(util.get_schedules_for_date, '__wrapped__', util.get_schedules_for_date)

        @lru_cache(maxsize=64)
        def cached(d, import_marker):
            return compute(d)

        def get_schedules_for_date(d):
            marker = GtfsImport.objects.filter(succeeded=True).aggregate(m=Max('finished'))['m']
            return cached(d, marker)

        util.get_schedules_for_date = get_schedules_for_date

    def register_jobs(self, scheduler: BaseScheduler):
        from prestop_data import jobs
        scheduler.add_job(
            jobs.refresh_gtfs,
            trigger=CronTrigger(
                minute=30,
                hour=4,
            ),
            id="prestop_refresh_gtfs",
            max_instances=1,
            replace_existing=True,
        )
