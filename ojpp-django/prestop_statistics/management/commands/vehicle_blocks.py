"""manage.py vehicle_blocks <route>: what stays.py learned about a route's departures.

For each departure on today's kind of day (or --kind): where its vehicle comes from (continues after another
departure, which one, how sure, with how much of a delay the layover takes up; or the depot) and on how many days.
"""
from django.core.management import BaseCommand, CommandError

from prestop_api import sources, trips
from prestop_statistics import stays
from prestop_statistics.aggregation import day_kind, hhmm
from prestop_statistics.models import StayDeparture


class Command(BaseCommand):
    help = 'Show which departures of a route continue a vehicle\'s previous trip (learned from the vehicle feed).'

    def add_arguments(self, parser):
        parser.add_argument('route', help='Route id (IJPP:123) or line name (e.g. "1", "I6")')
        parser.add_argument('--kind', choices=['workday', 'saturday', 'sunday'])

    def handle(self, route, kind, **options):
        kind = kind or day_kind(trips.service_day())
        try:
            routes = sources.routes.get().value
        except Exception:  # noqa: BLE001 - names are a nicety
            routes = {}
        ids = [route] if ':' in route else [r for r, v in routes.items() if (v.get('shortName') or '').lower() == route.lower()]
        if not ids:
            raise CommandError(f'No route {route!r}')
        name = lambda r: (routes.get(r) or {}).get('shortName') or r
        learned = stays.learned_on()
        self.stdout.write(f'{StayDeparture.objects.count()} departures learned on {learned or "(not yet: no feed has 7 full days)"}.')
        for route_id in ids:
            model = stays.departures(route_id, kind)
            self.stdout.write(f'\n{name(route_id)} ({route_id}), {kind}: {len(model)} departures')
            for start, m in sorted(model.items()):
                if m['origin'] == 'continues':
                    absorb = f", layover takes up {m['absorb'] // 60} min" if m['absorb'] is not None else ''
                    what = f"{m['level']}: continues {name(m['prev_route_id'])} {hhmm(m['prev_start'])} (ends {hhmm(m['prev_end'])}{absorb})"
                elif m['origin'] == 'depot':
                    delay = f", usually starts {m['depot_delay'] // 60} min late" if m['depot_delay'] is not None else ''
                    what = f'from the depot{delay}'
                else:
                    what = 'unknown'
                self.stdout.write(f'  {hhmm(start)}  {what}')
