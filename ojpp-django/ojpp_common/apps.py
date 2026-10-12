from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig

from ojpp_common import jobs


class OjppCommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ojpp_common"

    def register_jobs(self, scheduler):
        scheduler.add_job(
            jobs.updatedata,
            trigger=IntervalTrigger(
                minutes=30,
            ),
            id="updatedata",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.ping,
            trigger=IntervalTrigger(
                hours=2,
            ),
            id="ping",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.update_prometheus_metrics,
            trigger=IntervalTrigger(
                minutes=5,
            ),
            id="update_prometheus_metrics",
            max_instances=1,
            replace_existing=False,
        )
