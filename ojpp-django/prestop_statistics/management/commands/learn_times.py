import json
import logging
import resource
from datetime import date, datetime

from django.core.management import BaseCommand

from prestop_statistics import learned
from prestop_statistics.collector import LJUBLJANA

logger = logging.getLogger('prestop learn_times')


class Command(BaseCommand):
    help = "Learn running and dwell times per route, kind of day and hour band (learned.py); the collector runs it nightly."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=learned.DAYS, help='Days to learn from (default %(default)s)')
        parser.add_argument('--today', help='Learn as of this day (YYYY-MM-DD; default today)')
        parser.add_argument('--exclude', default='', help='Days to leave out, comma separated (YYYY-MM-DD)')
        parser.add_argument('--evaluate', action='store_true', help='Only compare the medians on held-out days; writes nothing')

    def handle(self, days, today, exclude, evaluate, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        day = date.fromisoformat(today) if today else datetime.now(LJUBLJANA).date()
        if evaluate:
            result = learned.evaluate(day, days)
        else:
            result = learned.learn(day, days, exclude=[date.fromisoformat(d) for d in exclude.split(',') if d])
        # Peak memory (kB on Linux), so the nightly bound can be checked in the journal.
        result['maxRssMb'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        logger.info('learned times: %s', json.dumps(result))
        self.stdout.write(json.dumps(result))
