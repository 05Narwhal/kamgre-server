import logging
import time

from django.conf import settings
from django.core.management import BaseCommand

from prestop_api import analytics, detected, platforms
from prestop_api.upstream import UpstreamError, get_json
from prestop_statistics import blocks, dwell, learned, stays
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
        dwells = dwell.DwellTracker()
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
                # How long vehicles stand at stops (dwell.py); also read between polls, below.
                dwells.observe(schedules, positions)
                dwells.write()
                # Vehicles standing where the timetable doesn't wait: detected disruptions (prestop_api/detected.py).
                if settings.PRESTOP_DETECTED_ALERTS:
                    logger.info('vehicle halts: %s', detected.observe(schedules, positions))
            except Exception as e:  # never let the vehicle feed stop the delay collector
                logger.warning('vehicle trips failed: %r', e)
            try:
                # Bus station departure boards: which bay each departure leaves from (platforms.py).
                bays_seen = platforms.learn()
                if bays_seen:
                    logger.info('departure bays seen: %s', bays_seen)
            except Exception as e:  # never let the boards stop the delay collector
                logger.warning('departure boards failed: %r', e)
            try:
                # Once a night: check yesterday's stay-on predictions, then relearn them (stays.py).
                learned_stays = stays.nightly()
                if learned_stays:
                    logger.info('stays learned: %s', learned_stays)
                # Then running and dwell times (learned.py), in a low-priority process of its own.
                times = learned.nightly()
                if times:
                    logger.info('learned times: %s', times)
            except Exception as e:  # never let the learning stop the delay collector
                logger.warning('nightly learning failed: %r', e)
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
            # Until the next poll, read the vehicle positions every dwell.POLL s: a 20 s dwell needs more than one
            # look a minute. Only the positions (~60 kB), and a failure only skips that look.
            while (left := backoff - (time.monotonic() - started)) > 1:
                time.sleep(min(left, dwell.POLL))
                if backoff - (time.monotonic() - started) <= 1:
                    break
                try:
                    dwells.observe(schedules, get_json(settings.PRESTOP_RT_VEHICLES_URL, limit=16 * 1024 * 1024))
                except Exception as e:  # never let the dwell reading stop the delay collector
                    logger.warning('dwell reading failed: %r', e)
