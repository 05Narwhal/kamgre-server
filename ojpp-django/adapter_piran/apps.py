from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig


class AdapterPiranConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_piran"

    def register_jobs(self, scheduler: BaseScheduler):
        from . import jobs
        scheduler.add_job(
            jobs.piran_update_locations,
            trigger=IntervalTrigger(
                seconds=20,
            ),
            id="piran_update_locations",
            max_instances=1,
            replace_existing=True,
        )
