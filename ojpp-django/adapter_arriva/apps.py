from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.date import DateTrigger
from django.apps import AppConfig


class AdapterArrivaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_arriva"

    def register_jobs(self, scheduler: BaseScheduler):
        from adapter_arriva import jobs
        # Never trigger, only register for manual run
        scheduler.add_job(
            jobs.arriva_update_matcher_data,
            trigger=DateTrigger(
                run_date='2021-01-01 00:00:00',
            ),
            id="arriva_update_matcher_data",
            max_instances=1,
            replace_existing=True,
        )
