"""Plan across learned "stay on the bus" changes through the API, each twice, and compare the answers.

    manage.py stay_consistency                       # the local API, 40 learned sure stays from the local database
    manage.py stay_consistency --n 20 --seed 3
    yarn server:stays --pairs 40 > pairs.txt         # the server's learned stays (read-only), then:
    manage.py stay_consistency --pairs-file pairs.txt --api https://api.kamgre.si/api/v1

Each pair is a learned `sure` stay (route, start, previous route and start). Its two trips are found in OTP on the
next day of the same kind, and two searches are made around the change: `short` (the stop before it to the stop
after it) and `long` (the previous trip's first stop to this trip's last: the stay is one part of a longer way, like
Kropa -> Ljubljana). The journey that rides both trips one after the other is looked for in the answer of each of
the two identical calls. Acceptance: the first call shows the same stay level as the second, and every journey
without one has a reason that is right by design (another timetable, another vehicle seen today, a different
journey chosen). Run it right after the server started to see the cold first call.
"""
import json
import random
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

LOCAL = ZoneInfo('Europe/Ljubljana')
ROUTE_Q = '''query($id: String!, $date: String!) { route(id: $id) { patterns { tripsForDate(serviceDate: $date) { gtfsId
  departureStoptime(serviceDate: $date) { scheduledDeparture }
  stoptimes { scheduledDeparture stop { gtfsId name lat lon } } } } } }'''


def trip_at(route_id: str, start: int, day: date) -> dict | None:
    """The trip of a route that starts `start` s after midnight on `day`, with its stops, from OTP."""
    from prestop_api.upstream import otp
    data = otp().query(ROUTE_Q, {'id': route_id, 'date': day.isoformat()})
    for pattern in (data.get('route') or {}).get('patterns') or []:
        for t in pattern.get('tripsForDate') or []:
            if (t.get('departureStoptime') or {}).get('scheduledDeparture') == start:
                return t
    return None


def next_day_of_kind(kind: str, after: date) -> date:
    from prestop_statistics.aggregation import day_kind
    return next(after + timedelta(days=i) for i in range(1, 15) if day_kind(after + timedelta(days=i)) == kind)


class Command(BaseCommand):
    help = 'Plan across learned stay-on changes twice each; fail when the first answer differs from the second.'

    def add_arguments(self, parser):
        parser.add_argument('--api', default='http://127.0.0.1:8066/api/v1')
        parser.add_argument('--against', choices=['local', 'prod'], default='local')
        parser.add_argument('--n', type=int, default=40)
        parser.add_argument('--seed', type=int, default=1)
        parser.add_argument('--pairs-file', help='PAIR lines from `yarn server:stays --pairs N` (else the local StayDeparture table)')

    def plan(self, api: str, origin: dict, destination: dict, when: datetime) -> list[dict]:
        place = lambda p: {'name': p['name'], 'latitude': p['lat'], 'longitude': p['lon']}
        body = {'origin': place(origin), 'destination': place(destination), 'via': [], 'dateTime': when.isoformat(), 'timeMode': 'departAt',
                'modes': ['walk', 'bus', 'rail'], 'riskMode': 'normal', 'minTransferSeconds': 180}
        request = urllib.request.Request(f'{api}/journeys', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'kamgre-stay-consistency/1'})  # the public API refuses urllib's own
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.load(resp).get('data') or []
        except urllib.error.HTTPError:
            return []

    @staticmethod
    def find(journeys: list[dict], first_trip: str, second_trip: str) -> dict:
        """The first journey that rides the two trips one after the other: its stay level, the stops of the change and
        the seconds walked between; {'found': False} when none does."""
        for j in journeys:
            legs = j['legs']
            rides = [(n, l) for n, l in enumerate(legs) if l['mode'] != 'walk']
            for (a, before), (b, after) in zip(rides, rides[1:]):
                if before.get('tripId') == first_trip and after.get('tripId') == second_trip:
                    walked = sum((datetime.fromisoformat(w['scheduledArrival']) - datetime.fromisoformat(w['scheduledDeparture'])).total_seconds()
                                 for w in legs[a + 1:b])
                    return {'found': True, 'level': after.get('stayLevel'), 'end': before['destination'].get('stopId'),
                            'begin': after['origin'].get('stopId'), 'walked': walked}
        return {'found': False}

    def pairs(self, opts) -> list[dict]:
        if opts['pairs_file']:
            with open(opts['pairs_file'], encoding='utf-8') as f:
                return [json.loads(line[5:]) for line in f if line.startswith('PAIR ')]
        from prestop_statistics.management.commands.stays_report import sample_sure
        rows = sample_sure(opts['n'], opts['seed'])
        if not rows:
            self.stdout.write(self.style.WARNING('the local database has no learned "sure" stays: take them from the server '
                                                 '(yarn server:stays --pairs 40 > pairs.txt, then --pairs-file)'))
        return rows

    def reason(self, row: dict, first: dict, second: dict, day: date, hit: dict) -> str:
        """Why a stay can rightly be missing for this pair (what predictions.stay_level refuses on); '' when nothing explains it."""
        from prestop_api import predictions, sources
        from prestop_statistics import blocks
        pattern = lambda t: blocks.hash_stops([(s.get('stop') or {}).get('gtfsId') or '' for s in t['stoptimes']])
        if pattern(second) != row['pattern'] or pattern(first) != row['prev_pattern']:
            return 'pattern-changed'
        if hit['walked'] > predictions.STAY_WALK:
            return 'walk-between'
        end, begin = hit['end'], hit['begin']
        if not end or (end != begin and begin not in sources.stop_group(end)):
            return 'stop-group'
        if day == date.today():
            try:
                if blocks.vehicle_on(first['gtfsId'], day) != blocks.vehicle_on(second['gtfsId'], day):
                    return 'vehicle-today'
            except Exception:  # noqa: BLE001 - no recorder data here
                return ''
        return ''

    def handle(self, *args, **opts):
        api = 'https://api.kamgre.si/api/v1' if opts['against'] == 'prod' and opts['api'].startswith('http://127.') else opts['api']
        rows = self.pairs(opts)
        random.Random(opts['seed']).shuffle(rows)
        today = date.today()
        bad = checked = absent = 0
        for row in rows:
            day = next_day_of_kind(row['kind'], today)
            name = f'{row["route_id"]}@{row["start"] // 3600:02d}:{row["start"] % 3600 // 60:02d} after {row["prev_route_id"]}'
            try:
                first, second = trip_at(row['prev_route_id'], row['prev_start'], day), trip_at(row['route_id'], row['start'], day)
            except Exception as e:  # noqa: BLE001
                self.stdout.write(f'{day} {name}: OTP unavailable ({e!r})')
                continue
            if not first or not second or len(first['stoptimes']) < 2 or len(second['stoptimes']) < 2:
                self.stdout.write(f'{day} {name}: a trip is not in the timetable of that day')
                continue
            midnight = datetime.combine(day, time(0), tzinfo=LOCAL)
            stop = lambda t, i: {**t['stoptimes'][i]['stop'], 'at': t['stoptimes'][i]['scheduledDeparture']}
            ahead = min(3, len(second['stoptimes']) - 1)
            variants = {'short': (stop(first, -2), stop(second, ahead)), 'long': (stop(first, 0), stop(second, -1))}
            for variant, (origin, destination) in variants.items():
                if origin['gtfsId'] == destination['gtfsId']:
                    continue  # a loop: from and to the same stop
                when = midnight + timedelta(seconds=origin['at'] - 60)
                first_call, second_call = (self.find(self.plan(api, origin, destination, when), first['gtfsId'], second['gtfsId']) for _ in range(2))
                checked += 1
                if not first_call['found'] and not second_call['found']:
                    absent += 1
                    verdict = 'not offered (the planner chose other rides)'
                elif first_call.get('level') != second_call.get('level') or first_call['found'] != second_call['found']:
                    bad += 1
                    verdict = f'INCONSISTENT first={first_call.get("level")} second={second_call.get("level")}'
                elif first_call['level']:
                    verdict = f'ok {first_call["level"]}'
                else:
                    why = self.reason(row, first, second, day, first_call)
                    if not why:
                        bad += 1
                    verdict = f'no stay, by design: {why}' if why else f'UNEXPLAINED no stay ({first_call})'
                self.stdout.write(f'{day} {variant:<5} {name}: {verdict}')
        self.stdout.write(f'{checked} searches over {len(rows)} stays: {absent} not offered, {bad} inconsistent or unexplained')
        if bad:
            raise CommandError(f'{bad} searches differ between the first and the second call or lack a reason')
        if not rows:
            raise CommandError('no learned stays to try')
