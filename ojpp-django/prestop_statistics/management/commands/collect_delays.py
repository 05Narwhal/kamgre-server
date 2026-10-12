import logging
import time

from django.core.management import BaseCommand

from prestop_api import platforms
from prestop_api.upstream import UpstreamError
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
                # Bus station departure boards: which bay each departure leaves from (platforms.py).
                learned = platforms.learn()
                if learned:
                    logger.info('departure bays seen: %s', learned)
            except Exception as e:  # never let the boards stop the delay collector
                logger.warning('departure boards failed: %r', e)
            if once:
                return
            time.sleep(max(1.0, backoff - (time.monotonic() - started)))
