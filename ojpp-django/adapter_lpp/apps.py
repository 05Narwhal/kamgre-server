from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig


class AdapterIjppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_lpp"

    def register_jobs(self, scheduler: BaseScheduler):
        from adapter_lpp import jobs
        scheduler.add_job(
            jobs.lpp_update_locations,
            trigger=IntervalTrigger(
                seconds=10,
            ),
            id="lpp_update_locations",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.lpp_update_mestnipromet,
            trigger=CronTrigger(
                minute=0,
                hour=0,
            ),
            id="lpp_update_mestnipromet",
            max_instances=1,
            replace_existing=False,
        )
        # Never trigger, only register for manual run
        scheduler.add_job(
            jobs.lpp_update_mestnipromet,
            trigger=DateTrigger(
                run_date='2021-01-01 00:00:00',
            ),
            id="lpp_update_mestnipromet",
            max_instances=1,
            replace_existing=True,
        )
