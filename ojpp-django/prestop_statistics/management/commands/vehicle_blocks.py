"""manage.py vehicle_blocks <route>: what blocks.py learned about a route's departures.

For each departure on today's kind of day (or --kind): how many days were seen, and whether the
vehicle usually comes off another departure (which one, on what share of days, with how much layover)
or starts fresh from the depot.
"""
from datetime import date

from django.core.management import BaseCommand, CommandError

from prestop_api import sources, trips
from prestop_statistics import blocks
from prestop_statistics.aggregation import day_kind
from prestop_statistics.models import VehicleTrip


def hhmm(seconds: int) -> str:
    return f'{seconds // 3600 % 24:02d}:{seconds % 3600 // 60:02d}'


class Command(BaseCommand):
    help = 'Show which departures of a route continue a vehicle\'s previous trip (learned from the vehicle feed).'

    def add_arguments(self, parser):
        parser.add_argument('route', help='Route id (IJPP:123) or line name (e.g. "1", "I6")')
        parser.add_argument('--kind', choices=['workday', 'saturday', 'sunday'])
        parser.add_argument('--date', type=date.fromisoformat, help='Service day (default today)')

    def handle(self, route, kind, date, **options):
        today = date or trips.service_day()
        kind = kind or day_kind(today)
        try:
            routes = sources.routes.get().value
        except Exception:  # noqa: BLE001 - names are a nicety
            routes = {}
        ids = [route] if ':' in route else [r for r, v in routes.items() if (v.get('shortName') or '').lower() == route.lower()]
        if not ids:
            raise CommandError(f'No route {route!r}')
        name = lambda r: (routes.get(r) or {}).get('shortName') or r
        days = blocks.recorded_days()
        self.stdout.write(f'{VehicleTrip.objects.count()} vehicle trips on {days} days recorded; blocks need {blocks.MIN_DAYS}.')
        for route_id in ids:
            model = blocks.learn(route_id, today, kind)
            self.stdout.write(f'\n{name(route_id)} ({route_id}), {kind}: {len(model)} departures')
            for start, m in sorted(model.items()):
                if m['previous']:
                    p = m['previous']
                    what = f"continues {name(p['routeId'])} {hhmm(p['start'])} (ends {hhmm(p['end'])}, layover {m['slack'] // 60} min)"
                else:
                    what = 'fresh from the depot'
                self.stdout.write(f"  {hhmm(start)}  {m['samples']:>2} days  {round(m['share'] * 100):>3} %  {what}")
