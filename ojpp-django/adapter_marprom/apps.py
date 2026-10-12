from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig


class AdapterMarpromConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_marprom"

    def register_jobs(self, scheduler: BaseScheduler):
        from adapter_marprom import jobs
        scheduler.add_job(
            jobs.marprom_update_locations,
            trigger=IntervalTrigger(
                seconds=30,
            ),
            id="marprom_update_locations",
            max_instances=1,
            replace_existing=True,
        )
        scheduler.add_job(
            jobs.marprom_update_stops,
            trigger=CronTrigger(
                hour=1,
                day_of_week='mon'
            ),
            id="marprom_update_stops",
            max_instances=1,
            replace_existing=True,
        )
        # Never trigger, only register for manual run
        scheduler.add_job(
            jobs.marprom_update_stop_location_photos,
            trigger=DateTrigger(
                run_date='2021-01-01 00:00:00',
            ),
            id="marprom_update_stop_location_photos",
            max_instances=1,
            replace_existing=True,
        )
