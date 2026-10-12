from datetime import date

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import AppConfig



class AdapterIjppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adapter_ijpp"


    def register_jobs(self, scheduler: BaseScheduler):
        from adapter_ijpp import jobs
        # scheduler.add_job(
        #     jobs.ijpp_update_locations,
        #     trigger=IntervalTrigger(
        #         seconds=10,
        #     ),
        #     id="ijpp_update_locations",
        #     max_instances=1,
        #     replace_existing=True,
        # )
        scheduler.add_job(
            jobs.ijpp_update_vozni_redi,
            trigger=CronTrigger(
                minute=0,
                hour=2,
            ),
            id="ijpp_update_vozni_redi",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.ijpp_update_nvr_names,
            trigger=CronTrigger(
                minute=0,
                hour=6,
                day_of_week=1,
            ),
            id="ijpp_update_nvr_names",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.get_polylines,
            trigger=CronTrigger(
                minute=30,
                hour=2,
            ),
            id="ijpp_get_polylines",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.ijpp_update_stops,
            trigger=CronTrigger(
                minute=0,
                hour=1,
            ),
            id="ijpp_update_stops",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.ijpp_update_prevozniki,
            trigger=CronTrigger(
                minute=0,
                hour=23,
                day_of_week=1,
            ),
            id="ijpp_update_prevozniki",
            max_instances=1,
            replace_existing=False,
        )
        scheduler.add_job(
            jobs.update_rezimi,
            trigger=CronTrigger(
                minute=45,
                hour=1,
            ),
            id="ijpp_update_rezimi",
            max_instances=1,
            replace_existing=False,
        )
