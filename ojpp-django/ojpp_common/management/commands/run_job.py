import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand

import logging

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)


class FakeScheduler:
    jobs = {}

    def add_job(self, func, id=None, **job):
        self.jobs[id] = func


class Command(BaseCommand):
    help = "Run a scheduled job synchronously"

    def add_arguments(self, parser):
        parser.add_argument('job_name', type=str, help='The name of the job to run (omit to list jobs)', nargs='?')

    def handle(self, job_name, *args, **options):
        scheduler = FakeScheduler()

        for app in apps.get_app_configs():
            if hasattr(app, 'register_jobs'):
                app.register_jobs(scheduler)

        if job_name:
            res = scheduler.jobs[job_name]()
            if asyncio.iscoroutine(res):
                asyncio.get_event_loop().run_until_complete(res)
        else:
            for job in scheduler.jobs:
                print(' -', job)
