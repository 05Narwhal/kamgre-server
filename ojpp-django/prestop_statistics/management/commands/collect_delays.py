import logging
import time

from django.conf import settings
from django.core.management import BaseCommand

from prestop_api import analytics, detected, platforms
from prestop_api.upstream import UpstreamError, get_json
from prestop_statistics import blocks, stays
from prestop_statistics.collector import ScheduleCache, collect_once

logger = logging.getLogger('prestop collector')


class Command(BaseCommand):
    help = "Record observed delays from the combined GTFS-RT trip updates (runs continuously)."

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Collect one snapshot and exit')
        parser.add_argument('--interval', type=int, default=60, help='Seconds between polls (default 60)')

    def handle(self, once, interval, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        schedules = ScheduleCache()
        backoff = interval
        while True:
            started = time.monotonic()
            try:
                logger.info('collected %s', collect_once(schedules))
                backoff = interval
            except UpstreamError as e:
                backoff = min(backoff * 2, 15 * 60)
                logger.warning('trip updates unavailable (%s); retrying in %ss', e, backoff)
            try:
                # Which vehicle serves which trip (blocks.py): vehicle positions with this poll's trip updates.
                positions = get_json(settings.PRESTOP_RT_VEHICLES_URL, limit=16 * 1024 * 1024)
                logger.info('vehicles on trips: %s', blocks.record(schedules, positions, schedules.updates))
                # Vehicles standing where the timetable doesn't wait: detected disruptions (prestop_api/detected.py).
                if settings.PRESTOP_DETECTED_ALERTS:
                    logger.info('vehicle halts: %s', detected.observe(schedules, positions))
            except Exception as e:  # never let the vehicle feed stop the delay collector
                logger.warning('vehicle trips failed: %r', e)
            try:
                # Bus station departure boards: which bay each departure leaves from (platforms.py).
                learned = platforms.learn()
                if learned:
                    logger.info('departure bays seen: %s', learned)
            except Exception as e:  # never let the boards stop the delay collector
                logger.warning('departure boards failed: %r', e)
            try:
                # Once a night: check yesterday's stay-on predictions, then relearn them (stays.py).
                learned = stays.nightly()
                if learned:
                    logger.info('stays learned: %s', learned)
            except Exception as e:  # never let the learning stop the delay collector
                logger.warning('stay learning failed: %r', e)
            try:
                # API usage counts: Redis -> AnalyticsHour every poll, and the finished day's visitors each night.
                analytics.flush()
                saved = analytics.nightly()
                if saved:
                    logger.info('usage days saved: %s', saved)
            except Exception as e:  # never let the counts stop the delay collector
                logger.warning('usage counts failed: %r', e)
            if once:
                return
            time.sleep(max(1.0, backoff - (time.monotonic() - started)))
