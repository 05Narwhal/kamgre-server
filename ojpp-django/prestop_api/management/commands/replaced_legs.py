"""Plan every stretch a bus replaces trains on, through the running API, and fail if a journey still rides the train.

    manage.py replaced_legs                                   # the local API, today and the next 2 days
    manage.py replaced_legs --api https://api.kamgre.si/api/v1 --date 2026-10-20 --max 10

For each service day the day's plan (scheduled.day_plan, the line view's source) gives the replaced stretches; each
distinct relation (first and last station of a stretch) is asked once leaving just before its train and once
arriving just after it. Every train leg that comes back is checked against the same plan
(replacement.stretches): a leg crossing a stretch a bus runs instead that day is a failure.
"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from prestop_api import closures, journey_legs, replacement, scheduled, sz


def replaced_leg(leg: dict) -> str:
    """'' or why this journey leg rides a train a bus replaces there that day."""
    if leg.get('mode') != 'rail' or leg.get('replacement') or not leg.get('tripId'):
        return ''
    when = datetime.fromisoformat(leg['scheduledDeparture']).timestamp()
    train, stretches = replacement.stretches(scheduled.plan_at(when, wait=30, cold=True), leg['tripId'], when)
    if not stretches:
        return ''
    start = journey_legs._index(train['stops'], leg['origin'])
    end = journey_legs._index(train['stops'], leg['destination'], start if start is not None else -1)
    for a, b, s in stretches:
        if start is not None and end is not None and a < end and b > start:
            return (f'{leg["routeName"]} {leg["origin"]["name"]} → {leg["destination"]["name"]} '
                    f'{leg["scheduledDeparture"][11:16]}: {train["stops"][a]["name"]} – {train["stops"][b]["name"]} is {s["busTripId"]}')
    return ''


class Command(BaseCommand):
    help = 'Plan each replaced train stretch (depart + arrive) through the API; fail when a journey rides the replaced train.'

    def add_arguments(self, parser):
        parser.add_argument('--api', default='http://127.0.0.1:8066/api/v1')
        parser.add_argument('--date', action='append', help='YYYY-MM-DD (repeatable); default today and the next 2 days')
        parser.add_argument('--max', type=int, default=40, help='relations per day at most')
        parser.add_argument('--workers', type=int, default=3)

    def relations(self, day: date, limit: int) -> list[tuple]:
        """(from stop, to stop, departure, arrival) per distinct replaced relation of the day, still ahead."""
        plan = scheduled.day_plan(day, wait=90)
        if not plan:
            raise CommandError(f'no plan for {day}')
        now, out, seen = datetime.now().timestamp(), [], set()
        for trip_id in plan['sections']:
            for run in (plan.get('trips') or {}).get(trip_id) or []:
                if closures.service_date(run) != day.strftime('%Y%m%d'):
                    continue
                train, stretches = replacement.stretches(plan, trip_id, run['departures'][0])
                for a, b, _ in stretches if train is run else []:
                    stops = run['stops']
                    key = (sz.station_key(stops[a]['name']), sz.station_key(stops[b]['name']))
                    if key in seen or run['departures'][a] < now + 600:
                        continue
                    seen.add(key)
                    out.append((stops[a], stops[b], run['departures'][a], run['arrivals'][b]))
        return sorted(out, key=lambda r: r[2])[:limit]

    def plan(self, api: str, origin: dict, destination: dict, mode: str, when: float) -> dict:
        place = lambda s: {'name': s['name'], 'latitude': s['lat'], 'longitude': s['lon']}
        body = {'origin': place(origin), 'destination': place(destination), 'via': [], 'timeMode': mode,
                'dateTime': datetime.fromtimestamp(when, closures.LOCAL).isoformat(), 'modes': ['walk', 'bus', 'rail'],
                'riskMode': 'normal', 'minTransferSeconds': 180}
        request = urllib.request.Request(f'{api}/journeys', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            return json.load(e)

    def ask(self, api: str, relation: tuple) -> tuple[str, int, list[str]]:
        origin, destination, dep, arr = relation
        found, bad = 0, []
        for mode, when in (('departAt', dep - 600), ('arriveBy', arr + 600)):
            result = self.plan(api, origin, destination, mode, when)
            if 'error' in result:
                bad.append(f'{mode} ERROR {result["error"].get("code")}')
                continue
            found += len(result['data'])
            bad += [f'{mode}: {why}' for j in result['data'] for leg in j['legs'] if (why := replaced_leg(leg))]
        label = f'{origin["name"]} → {destination["name"]} {datetime.fromtimestamp(dep, closures.LOCAL):%H:%M}'
        return label, found, bad

    def handle(self, *args, **opts):
        today = scheduled.service_day()
        days = [date.fromisoformat(d) for d in opts['date']] if opts['date'] else [today + timedelta(days=i) for i in range(3)]
        relations = failures = 0
        for day in days:
            asked = self.relations(day, opts['max'])
            relations += len(asked)
            with ThreadPoolExecutor(opts['workers']) as pool:
                for label, found, bad in pool.map(lambda r: self.ask(opts['api'], r), asked):
                    failures += len(bad)
                    self.stdout.write(f'{day} {label}: {found} journeys' + ''.join(f'\n    REPLACED {b}' for b in bad))
        self.stdout.write(f'{relations} relations, {failures} replaced train legs or errors')
        if failures:
            raise CommandError(f'{failures} journeys ride a train a bus replaces (or failed)')
        self.stdout.write(self.style.SUCCESS('no journey rides a replaced train'))
