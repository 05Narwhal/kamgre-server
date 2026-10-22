"""manage.py stays_report: an overview of the stay-on and depot learning (stays.py), read-only.

Per feed: complete days recorded, the 7-full-days gate (open since, or the day it opens if every day from today on
counts), and what the nightly job learned (sure / likely stays, departures from the depot). With --lines, the lines
of each open feed with their learned departures; `vehicle_blocks <line>` then shows one line departure by departure.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.management import BaseCommand

from prestop_api import sources, trips
from prestop_statistics import stays
from prestop_statistics.models import StayDeparture


class Command(BaseCommand):
    help = 'Overview of the stay-on and depot learning: gate per feed, what was learned, and (--lines) per line.'

    def add_arguments(self, parser):
        parser.add_argument('--lines', action='store_true', help='List the lines of each open feed')
        parser.add_argument('--feed', help='Only this feed (e.g. IJPP, LPP)')

    def handle(self, lines, feed, **options):
        today = trips.service_day()
        since, until = stays.window(today)
        days = stays.complete_days(since, until)
        learned = stays.learned_on()
        rows = list(StayDeparture.objects.values('feed', 'route_id', 'kind', 'origin', 'level'))
        counts: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            counts[r['feed']][r['level'] or r['origin']] += 1
        feeds = sorted(set(days) | set(counts))
        if feed:
            feeds = [f for f in feeds if f.lower() == feed.lower()]
        self.stdout.write(f'Today {today}. Last nightly learning: {learned or "not yet"}. '
                          f'A feed opens after {stays.GATE_DAYS} complete days in a row; the night after, its departures are learned.')
        if not feeds:
            self.stdout.write('No feeds recorded yet.')
            return
        self.stdout.write(f'\n{"feed":<10} {"days":>4} {"run":>5}  {"gate":<30} {"sure":>5} {"likely":>6} {"depot":>6}')
        for f in feeds:
            got = days.get(f, set())
            run, d = 0, until
            while d in got:
                run, d = run + 1, d - timedelta(days=1)
            opened = stays.gate_opens(got)
            gate = f'open since {opened}' if opened else f'opens {today + timedelta(days=stays.GATE_DAYS - run)} if all count'
            c = counts.get(f, Counter())
            self.stdout.write(f'{f:<10} {len(got):>4} {run:>2}/{stays.GATE_DAYS}  {gate:<30} {c["sure"]:>5} {c["likely"]:>6} {c["depot"]:>6}')
        self.stdout.write(f'\n"sure" needs at least {stays.SURE_DAYS} observed days of the same kind (workday, Saturday, Sunday), '
                          'so weekends take a few weeks longer than workdays. Live check: manage.py stay_accuracy.')
        if not lines:
            return
        try:
            routes = sources.routes.get().value
        except Exception:  # noqa: BLE001 - names are a nicety
            routes = {}
        per_route: dict[tuple, Counter] = defaultdict(Counter)
        for r in rows:
            if r['feed'] in feeds:
                per_route[(r['feed'], r['route_id'])][r['level'] or r['origin']] += 1
        if not per_route:
            self.stdout.write('\nNo lines learned yet.')
            return
        name = lambda r: (routes.get(r) or {}).get('shortName') or r
        for f in feeds:
            mine = sorted((key for key in per_route if key[0] == f), key=lambda key: (name(key[1]).zfill(6), key[1]))
            if not mine:
                continue
            self.stdout.write(f'\n{f}: {len(mine)} lines   {"sure":>5} {"likely":>6} {"depot":>6}')
            for key in mine:
                c = per_route[key]
                self.stdout.write(f'  {name(key[1]):<8} {key[1]:<24} {c["sure"]:>5} {c["likely"]:>6} {c["depot"]:>6}')
        self.stdout.write('\nOne line departure by departure: manage.py vehicle_blocks <line> [--kind workday|saturday|sunday]')
