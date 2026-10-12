import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand

import logging

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)


class Command(BaseCommand):
    help = "Runs APScheduler."

    def handle(self, *args, **options):
        scheduler = AsyncIOScheduler(timezone=settings.TIME_ZONE)
        #scheduler.add_jobstore(DjangoJobStore(), "default")
        logger = logging.getLogger('task runner')
        logger.setLevel(logging.INFO)

        for app in apps.get_app_configs():

            if hasattr(app, 'register_jobs'):
                try:
                    app.register_jobs(scheduler)
                    logger.info("Added jobs from '" + app.name + "'")
                except Exception as e:
                    logger.error("Error adding jobs from '" + app.name + "': " + str(e))

        try:
            logger.info("Starting scheduler...")
            scheduler.start()
            asyncio.get_event_loop().run_forever()

        except KeyboardInterrupt:
            logger.info("Stopping scheduler...")
            scheduler.shutdown()
            logger.info("Scheduler shut down successfully!")
