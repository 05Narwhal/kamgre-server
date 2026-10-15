import asyncio
import functools
import logging

from asgiref.sync import sync_to_async
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django.apps import apps
from django.conf import settings
from django.core.management import BaseCommand
from django.db import close_old_connections

logger = logging.getLogger('prestop ingestion')


class FilteredScheduler:
    """Passes through only the upstream jobs listed in PRESTOP_INGESTION_JOBS."""

    def __init__(self, scheduler, allowed):
        self.scheduler = scheduler
        self.allowed = set(allowed)
        self.added = []

    def add_job(self, func, id=None, **kwargs):
        if id in self.allowed:
            self.scheduler.add_job(fresh_connection(func), id=id, **kwargs)
            self.added.append(id)


def fresh_connection(func):
    """The job with Django's database connection checked before and after each run, as a request would have it. A
    long-running scheduler otherwise keeps a connection PostgreSQL closed (a restart on deploy) and every run fails
    with "connection already closed" until the service restarts (1980 times on 2026-10-15)."""
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def run_async(*args, **kwargs):
            await sync_to_async(close_old_connections)()
            try:
                return await func(*args, **kwargs)
            finally:
                await sync_to_async(close_old_connections)()
        return run_async

    @functools.wraps(func)
    def run(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()
    return run


class Command(BaseCommand):
    help = "Run the configured, credential-free subset of OJPP ingestion jobs."

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run each configured interval job once and exit')

    def handle(self, once, **options):
        logging.basicConfig(level=logging.INFO)
        allowed = settings.PRESTOP_INGESTION_JOBS
        scheduler = AsyncIOScheduler(timezone=settings.TIME_ZONE)
        filtered = FilteredScheduler(scheduler, allowed)
        for app in apps.get_app_configs():
            if hasattr(app, 'register_jobs'):
                try:
                    app.register_jobs(filtered)
                except Exception as e:
                    logger.warning("Skipping jobs from '%s': %r", app.name, e)
        missing = set(allowed) - set(filtered.added)
        if missing:
            logger.warning('Configured jobs not found: %s', ', '.join(sorted(missing)))
        logger.info('Ingestion jobs: %s', ', '.join(filtered.added) or 'none')

        if once:
            async def run_once():
                for job in scheduler.get_jobs():
                    if not isinstance(job.trigger, IntervalTrigger):
                        continue
                    if asyncio.iscoroutinefunction(job.func):
                        await job.func()
                    else:
                        await asyncio.to_thread(job.func)
            asyncio.run(run_once())
            return

        async def run_forever():
            scheduler.start()  # needs the running loop
            try:
                await asyncio.Event().wait()
            finally:
                scheduler.shutdown(wait=False)

        try:
            asyncio.run(run_forever())
        except KeyboardInterrupt:
            pass
