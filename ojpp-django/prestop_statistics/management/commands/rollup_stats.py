"""SŽ train and station rollups for one day (rollup.py), then every other line and its stops (bus_rollup.py), plus a
backfill of earlier days while time allows (days without train rows, days without line rows).

    manage.py rollup_stats                                 # yesterday
    manage.py rollup_stats --day 2026-10-25
    manage.py rollup_stats --backfill 90 --until 02:50     # then earlier days without rows, newest first, until 02:50
    manage.py rollup_stats --since 2026-10-20              # re-roll every day since then TripDelay still holds (new fields)

The night window (systemd prestop-nightly.service, 02:05) runs both; a re-run replaces a day's rows."""
import json
import logging
import resource
from datetime import date, datetime, time, timedelta

from django.core.management import BaseCommand, CommandError

from prestop_api.upstream import UpstreamError
from prestop_statistics import bus_rollup, rollup
from prestop_statistics.collector import LJUBLJANA

logger = logging.getLogger('prestop rollup_stats')


class Command(BaseCommand):
    help = "Roll up SŽ train and station delays per day (TrainDay, StationDay) from TripDelay."

    def add_arguments(self, parser):
        parser.add_argument('--day', help='The service day (YYYY-MM-DD; default yesterday)')
        parser.add_argument('--backfill', type=int, default=0, help='Also earlier days without rows, this many days back')
        parser.add_argument('--until', default='', help='Stop the backfill at this local time (HH:MM)')
        parser.add_argument('--since', default='', help='Also re-roll every earlier day from this one (YYYY-MM-DD) with delays')

    def handle(self, day, backfill, until, since, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        now = datetime.now(LJUBLJANA)
        first = date.fromisoformat(day) if day else now.date() - timedelta(days=1)
        try:
            deadline = datetime.combine(now.date(), time.fromisoformat(until), LJUBLJANA) if until else None
        except ValueError as e:
            raise CommandError(f'--until must be HH:MM: {e}') from e
        try:
            since_day = date.fromisoformat(since) if since else None
        except ValueError as e:
            raise CommandError(f'--since must be YYYY-MM-DD: {e}') from e
        memo: dict = {}
        self.routes = bus_rollup.route_info()
        done = [self.one(first, memo) | self.buses(first)]
        older_days = rollup.days_since(since_day, first) if since_day else []
        older_days += [d for d in (rollup.days_to_backfill(first, backfill) if backfill else []) if d not in older_days]
        # Lines and bus stops (bus_rollup.py) of days that have none yet; a --since re-roll redoes them too.
        bus_days = set(older_days if since_day else []) | set(bus_rollup.days_to_backfill(first, backfill) if backfill else [])
        for older in sorted(set(older_days) | bus_days, reverse=True):
            if deadline and datetime.now(LJUBLJANA) >= deadline:
                logger.info('backfill stopped at %s: the night window ends', deadline.strftime('%H:%M'))
                break
            row = self.one(older, memo) if older in older_days else {'day': older.isoformat()}
            done.append(row | (self.buses(older) if older in bus_days else {}))
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

    def buses(self, day: date) -> dict:
        """The day's lines and bus stops (bus_rollup.py); the database only, so it cannot be left half done by OTP."""
        lines, stops, counts = bus_rollup.build(day, self.routes)
        bus_rollup.write(day, lines, stops)
        return counts
