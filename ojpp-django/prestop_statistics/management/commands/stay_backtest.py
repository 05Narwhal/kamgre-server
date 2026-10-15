"""manage.py stay_backtest: how right staying on the same vehicle would have been on the recorded days.

For each recorded day D, the levels are learned from the days before D only and compared with what the vehicles did
on D. Precision = right / predicted, recall = right / the departures that did continue. Days before a feed's
7-full-days gate get no prediction. Also prints the gate per feed and the `min_days` the nightly tuning picked.
"""
from django.core.management import BaseCommand

from prestop_api import trips
from prestop_statistics import stays


def pct(a: int, b: int) -> str:
    return f'{100 * a / b:5.1f} %' if b else '    -  '


class Command(BaseCommand):
    help = 'Backtest the stay-on-the-same-vehicle levels on the recorded days.'

    def handle(self, **options):
        today = trips.service_day()
        days, opens, groups = stays.gather(today)
        for feed in sorted(days):
            opened = opens.get(feed)
            self.stdout.write(f'{feed}: {len(days[feed])} complete days, gate {"opens " + opened.isoformat() if opened else "closed"}')
        min_days = stays.tune(groups)
        self.stdout.write(f'min_days for sure: {min_days or "(no cases yet)"}')
        table = stays.backtest(groups, opens, min_days)
        if not table:
            self.stdout.write('No predictions to check yet (no feed has an open gate with days after it).')
            return
        self.stdout.write(f'\n{"level":<7} {"feed":<10} {"kind":<9} {"predicted":>9} {"right":>6} {"precision":>9} {"recall":>8}')
        for (level, feed, kind), c in sorted(table.items()):
            self.stdout.write(f'{level:<7} {feed:<10} {kind:<9} {c["predicted"]:>9} {c["hits"]:>6} {pct(c["hits"], c["predicted"]):>9} {pct(c["hits"], c["continued"]):>8}')
