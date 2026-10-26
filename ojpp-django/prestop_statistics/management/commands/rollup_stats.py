"""SŽ train and station rollups for one day (rollup.py), plus a backfill of earlier days while time allows.

    manage.py rollup_stats                                 # yesterday
    manage.py rollup_stats --day 2026-10-25
    manage.py rollup_stats --backfill 90 --until 02:50     # then earlier days without rows, newest first, until 02:50

The night window (systemd prestop-nightly.service, 02:05) runs both; a re-run replaces a day's rows."""
import json
import logging
import resource
from datetime import date, datetime, time, timedelta

from django.core.management import BaseCommand, CommandError

from prestop_api.upstream import UpstreamError
from prestop_statistics import rollup
from prestop_statistics.collector import LJUBLJANA

logger = logging.getLogger('prestop rollup_stats')


class Command(BaseCommand):
    help = "Roll up SŽ train and station delays per day (TrainDay, StationDay) from TripDelay."

    def add_arguments(self, parser):
        parser.add_argument('--day', help='The service day (YYYY-MM-DD; default yesterday)')
        parser.add_argument('--backfill', type=int, default=0, help='Also earlier days without rows, this many days back')
        parser.add_argument('--until', default='', help='Stop the backfill at this local time (HH:MM)')

    def handle(self, day, backfill, until, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        now = datetime.now(LJUBLJANA)
        first = date.fromisoformat(day) if day else now.date() - timedelta(days=1)
        try:
            deadline = datetime.combine(now.date(), time.fromisoformat(until), LJUBLJANA) if until else None
        except ValueError as e:
            raise CommandError(f'--until must be HH:MM: {e}') from e
        memo: dict = {}
        done = [self.one(first, memo)]
        for older in rollup.days_to_backfill(first, backfill) if backfill else []:
            if deadline and datetime.now(LJUBLJANA) >= deadline:
                logger.info('backfill stopped at %s: the night window ends', deadline.strftime('%H:%M'))
                break
            done.append(self.one(older, memo))
        result = {'days': done, 'maxRssMb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
        logger.info('rollup: %s', json.dumps(result, default=str))
        self.stdout.write(json.dumps(result, default=str))

    def one(self, day: date, memo: dict) -> dict:
        try:
            trains, stations, counts = rollup.build(day, memo=memo)
        except UpstreamError as e:  # OTP down: the day is left as it was and tried again next night
            logger.warning('rollup of %s failed: %r', day, e)
            return {'day': day.isoformat(), 'error': str(e)}
        rollup.write(day, trains, stations)
        return {'day': day.isoformat(), 'stations': len(stations), **counts}
