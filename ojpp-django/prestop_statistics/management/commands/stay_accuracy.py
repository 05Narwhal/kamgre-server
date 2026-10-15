"""manage.py stay_accuracy: the nightly live check of the last 14 days (StayCheck), per feed and level."""
from datetime import timedelta

from django.core.management import BaseCommand

from prestop_api import trips
from prestop_statistics import stays
from prestop_statistics.models import StayCheck


class Command(BaseCommand):
    help = "Show how yesterday's stay-on predictions matched what the vehicles did, for the last 14 days."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=14)

    def handle(self, days, **options):
        today = trips.service_day()
        rows = StayCheck.objects.filter(day__gte=today - timedelta(days=days)).order_by('day', 'feed', 'level')
        if not rows:
            self.stdout.write('No live checks yet: they start the night after the first feed opens its gate.')
        for r in rows:
            total = r.hits + r.misses
            self.stdout.write(f'{r.day}  {r.feed:<10} {r.level:<7} {r.hits:>5}/{total:<5} {100 * r.hits / total:5.1f} %')
        capped = stays.demoted(today)
        if capped:
            self.stdout.write(f'At most "likely" this week (a wrong "sure"): {", ".join(sorted(capped))}')
