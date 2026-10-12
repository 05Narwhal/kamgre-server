from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig


class AdapterNapConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_nap"

    def register_jobs(self, scheduler: BaseScheduler):
        from adapter_nap import jobs
        scheduler.add_job(
           jobs.nap_update_locations,
           trigger=IntervalTrigger(
               seconds=10,
           ),
           id="nap_update_locations",
           max_instances=1,
           replace_existing=True,
        )
