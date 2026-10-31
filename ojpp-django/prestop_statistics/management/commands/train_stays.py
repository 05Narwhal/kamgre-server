"""manage.py train_stays [--date YYYY-MM-DD]: the learned train stays (TrainStay), the coverage behind the gate, and
with --date that day's outcomes and joined trains (spec 2026-10-31 H6). Read-only."""
import json
from datetime import date

from django.core.management import BaseCommand

from prestop_statistics import train_stays as ts


class Command(BaseCommand):
    help = 'List the learned train stays (and one day with --date).'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat, default=None)

    def handle(self, date=None, **options):
        out = ts.report(date)
        if date:
            out['joined'] = ts.notice_links(date, ts.timetable(date))
        self.stdout.write(json.dumps(out, ensure_ascii=False, indent=1, default=str))
