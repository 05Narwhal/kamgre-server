from django.apps import AppConfig
from apscheduler.triggers.cron import CronTrigger
from exporter_gtfs import jobs


class ExporterIJPPConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exporter_gtfs"

    def register_jobs(self, scheduler):
        scheduler.add_job(
            jobs.export_gtfs,
            trigger=CronTrigger(
                minute=00,
                hour=3,
            ),
            id="exporter_gtfs_export_gtfs",
            max_instances=1,
            replace_existing=False,
        )