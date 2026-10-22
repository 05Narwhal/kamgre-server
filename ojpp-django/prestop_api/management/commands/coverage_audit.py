"""Every bus the app hides (spec 2026-10-22 D2): the live feeds and the timetable against what the API returns.

    manage.py coverage_audit                          # against the local server (localhost:8066)
    manage.py coverage_audit --against prod           # against api.kamgre.si (GETs only)
    manage.py coverage_audit --stops 'Kropa,IJPP:123' --minutes 90
    manage.py coverage_audit --replay-days 3          # trips the collector recorded on past days, through the boards
    manage.py coverage_audit --stops ... --save       # also keep the counts (no ids) for /health (the collector's sample, D6)

Checks, each a table by reason and by feed with up to coverage.EXAMPLES examples per reason:
- map: every entity of the combined GTFS-RT vehicle feed, every SŽ live report and every timetable train on its
  way, against the audited /vehicles (Slovenia's box); a dropped one has the reason this code left it out, at the
  file:line that did (the same pipeline, sources._load_vehicles, run here with drop notes);
- boards from live: each trip update's next 2 stops within --minutes, and each vehicle's next stop, against the
  audited board of that stop (departures, or arrivals at its last stop);
- boards from timetable: for the stops, OTP's `stoptimesForServiceDate` (every member of the stop group, yesterday's
  and today's service day) within --minutes against the audited board; also runs listed twice;
- replay: trips with a recorded vehicle (prestop_statistics.VehicleTrip) on the last recorded days, through this code's board
  of one of their stops at that time (timetable only; the past has no live times).
The reasons come from running this code here on the same upstream data at about the same moment; a run kept
here but absent on the target is "missing on target" (another version, a cache, or the moment between)."""
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from prestop_api import coverage, mapping, sources, supplement, sz, views
from prestop_api.upstream import UpstreamError, otp, session

TARGETS = {'local': 'http://localhost:8066/api/v1', 'prod': 'https://api.kamgre.si/api/v1'}
DEFAULT_STOPS = ['Kranj AP', 'Radovljica', 'Kropa', 'Trzin Ind. cona', 'Polhov Gradec', 'Bled', 'Jesenice', 'Škofja Loka', 'Ljubljana AP']
LOCAL = ZoneInfo('Europe/Ljubljana')
WORKERS = 4
LEAD = 300        # s: live runs are checked at stops at least this far ahead (the audit takes minutes)
MAX_PAGES = 12    # boards read per stop, going on as the app does
TARGET_LAG = 15   # s between reads of the target's vehicles
TARGET_READS = 5  # reads at most (a minute) while a vehicle built here is not yet in the target's
STOPTIMES_Q = '''query($id: String!, $date: String!) { stop(id: $id) {
  stoptimesForServiceDate(date: $date, omitNonPickups: false, omitCanceled: false) {
    pattern { route { gtfsId shortName longName mode } }
    stoptimes { serviceDay scheduledArrival scheduledDeparture stopPosition pickupType dropoffType
      trip { gtfsId departureStoptime { stopPosition stop { gtfsId } } arrivalStoptime { stopPosition stop { gtfsId } } } } } } }'''
TRIP_DAY_Q = '''query($id: String!, $date: String!) { trip(id: $id) { gtfsId route { gtfsId shortName longName mode }
  stoptimesForDate(serviceDate: $date) { serviceDay scheduledDeparture pickupType stop { gtfsId } } } }'''


class Command(BaseCommand):
    help = 'Lists every bus the app hides: live feeds and timetable against the map and the boards.'

    def add_arguments(self, parser):
        parser.add_argument('--against', choices=sorted(TARGETS), default='local')
        parser.add_argument('--minutes', type=int, default=60, help='how far ahead the board checks look')
        parser.add_argument('--stops', default='', help='comma-separated stop ids or names (default: the reported places + random ones)')
        parser.add_argument('--random', type=int, default=20, help='random stops added to the default set')
        parser.add_argument('--sample', type=int, default=100, help='live trips checked on boards besides those at the stops')
        parser.add_argument('--seed', type=int, default=22)
        parser.add_argument('--replay-days', type=int, default=0)
        parser.add_argument('--checks', default='map,live,timetable', help='any of map, live, timetable, replay')
        parser.add_argument('--save', action='store_true', help='keep the counts for /health (against local only)')

    def handle(self, *args, **opts):
        self.base = TARGETS[opts['against']]
        self.now = int(time.time())
        self.horizon = max(5, opts['minutes']) * 60
        self.read_at: dict = {}
        self.results: dict = {}
        checks = set(opts['checks'].split(',')) | ({'replay'} if opts['replay_days'] else set())
        if opts['save'] and opts['against'] != 'local':
            raise CommandError('--save keeps the counts of this server only (--against local)')
        try:
            self._get('/health')
        except Exception as e:
            raise CommandError(f'{self.base} does not answer: {e!r}')
        stops = sources.stops.get().value
        rng = random.Random(opts['seed'])
        picked = self._resolve(stops, opts['stops'], opts['random'], rng)
        members = {m for s in picked for m in s.get('memberIds') or [s['id']]}
        self.stdout.write(f'coverage audit against {opts["against"]} at {datetime.fromtimestamp(self.now, LOCAL):%Y-%m-%d %H:%M} '
                          f'(Ljubljana), {len(picked)} stops: ' + ', '.join(f'{s["name"]} ({s["id"]})' for s in picked))
        if 'map' in checks:
            self._map()
        if 'live' in checks:
            self._live(members, opts['sample'], rng)
        if 'timetable' in checks:
            self._timetable(picked)
        if 'replay' in checks:
            self._replay(stops, members, opts['replay_days'], rng)
        if opts['save']:
            boards = None if 'live' not in checks and 'timetable' not in checks else self.results.get('live', []) + self.results.get('timetable', [])
            block = coverage.health_block(self.results.get('map'), boards, self.results.get('twice'), len(picked), self.horizon // 60, self.now)
            coverage.save(block)
            self.stdout.write('saved for /health: ' + coverage.health_line(block))
        self.stdout.write(f'took {int(time.time()) - self.now} s')

    # ------------------------------------------------------------ helpers

    def _get(self, path: str, params=None):
        r = session().get(self.base + path, params=params, timeout=(5, 90))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get('data')

    def _print(self, title: str, rows: list[dict], ok=coverage.SHOWN):
        self.stdout.write('\n'.join(coverage.table(title, rows, ok)))

    def _resolve(self, snap: dict, raw: str, extra: int, rng: random.Random) -> list[dict]:
        merged = snap['list']
        by_member = {m: s for s in merged for m in s.get('memberIds') or [s['id']]}
        out, missing = [], []
        for q in [q.strip() for q in raw.split(',') if q.strip()] or DEFAULT_STOPS:
            if ':' in q:
                found = [by_member[q]] if q in by_member else []
            else:
                fq = mapping.fold(q)
                found = [s for s in merged if mapping.fold(s['name']) == fq] or [s for s in merged if mapping.fold(s['name']).startswith(fq)][:6]
            out += [s for s in found if s not in out]
            if not found:
                missing.append(q)
        if missing:
            self.stdout.write('not found: ' + ', '.join(missing))
        if not raw:
            by_feed: dict = {}
            for s in merged:
                if s not in out and s.get('modes'):
                    by_feed.setdefault(coverage.feed(s['id']), []).append(s)
            feeds = sorted(by_feed)
            rng.shuffle(feeds)
            while extra > 0 and any(by_feed.values()):
                for f in feeds:
                    if by_feed[f] and extra > 0:
                        out.append(by_feed[f].pop(rng.randrange(len(by_feed[f]))))
                        extra -= 1
        return out

    def _boards(self, keys: list[tuple[str, str]], start: Optional[int] = None) -> dict:
        """(stop id, kind) -> (target rows or None, rows built here, drop notes); each board from `start`, else from
        when it is read (self.read_at), so a run due while the audit runs is not taken for a miss. Full boards go on
        as the app's "Later" does (coverage.next_page) to the end of the audited window."""
        def pages(get, at: int) -> Optional[list]:
            rows: Optional[list] = None
            for _ in range(MAX_PAGES):
                page = get(at)
                if page is None:
                    return rows
                ids = {r['id'] for r in rows or []}
                rows = (rows or []) + [r for r in page if r['id'] not in ids]  # the last row shows again on the next
                at = coverage.next_page(page, sources.BOARD_MAX, at)
                if at is None or at >= self.now + self.horizon:
                    break
            return rows

        def one(key):
            stop_id, kind = key
            drops: list = []
            self.read_at[key] = at = start or int(time.time())

            def here(t):
                try:
                    return sources._board(stop_id, kind, t, 'sl', drops)
                except UpstreamError:
                    return None

            def target(t):
                data = self._get(f'/stops/{quote(stop_id, safe=":")}/board', {'kind': kind, 'at': mapping.iso(t)})
                return (data or {}).get('items') if data is not None else None
            return key, (pages(target, at), pages(here, at), drops)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            return dict(pool.map(one, keys))

    def _otp_reason(self, trip_id: str, stop_id: str, day: str) -> str:
        """Why OTP's board would not list a run: OTP lacks the trip that day, or does not call at this stop."""
        try:
            trip = otp().query(TRIP_DAY_Q, {'id': trip_id, 'date': day}).get('trip')
        except UpstreamError:
            return 'not returned by OTP for the board'
        if not trip:
            return 'trip not in OTP (upstream)'
        calls = trip.get('stoptimesForDate') or []
        if not calls:
            return 'trip not running that day in OTP (upstream)'
        if stop_id not in {(c.get('stop') or {}).get('gtfsId') for c in calls}:
            return 'OTP has the trip, not at this stop'
        return 'not returned by OTP for the board'

    # ------------------------------------------------------------ map

    def _map(self):
        drops: list = []
        box = {'bbox': ','.join(str(v) for v in views.SLOVENIA)}
        # A fresh feed (seconds old) that the build reads too: an old one is served while a background refresh runs,
        # and a refresh landing later would make its new vehicles look lost (the collector's runs, D6).
        feed = sources.positions._refresh(force=True)
        here = sources._load_vehicles(drops)
        entities = feed.value
        by_id = {mapping.entity_vehicle_id(e): e for e in entities}
        kept = set()
        for v in here:
            if v['quality'] == 'observed' and v['id'] in by_id and not views.inside(v, views.SLOVENIA):
                coverage.note(drops, 'outside the map area', by_id[v['id']])
            else:
                kept.add(v['id'])
        # The target refreshes on its own clock (its feed and vehicles each served up to ~35 s old while refreshing):
        # a vehicle new in the feed counts once it has caught up, read again until then, TARGET_READS reads at most.
        target = self._get('/vehicles', box) or []
        for _ in range(TARGET_READS - 1):
            if not (kept & set(by_id)) - {v['id'] for v in target}:
                break
            time.sleep(TARGET_LAG)
            target += self._get('/vehicles', box) or []
        target_ids = {v['id'] for v in target}
        rows = self.results['map'] = coverage.map_rows(entities, drops, kept, target_ids, mapping.entity_vehicle_id)
        self._print('Map: GTFS-RT vehicles', rows)
        # Timetable trains and replacement buses on their way, and SŽ's own reports (by train number).
        trains = [{'feed': coverage.feed(d['item']['id']), 'status': d['reason'], 'at': d['at'], 'example': d['item']['id']}
                  for d in drops if isinstance(d['item'], dict) and 'pattern' in d['item']]
        trains += [{'feed': coverage.feed(v['tripId']), 'status': 'shown' if v['id'] in target_ids else 'missing on target',
                    'at': '' if v['id'] in target_ids else 'target API', 'example': v['tripId']} for v in here if ':scheduled-' in v['id']]
        self._print('Map: timetable trains and replacement buses', trains, ok=coverage.SHOWN + coverage.REPLACED
                    + ('has a live vehicle', 'a bus runs this stretch', 'not on its way by its times'))
        if sz.live.url:
            sz.live._poll()
        drawn = {v.get('trainNumber') for v in target if v.get('mode') == 'rail'}
        reasons = {}
        for d in drops:
            if isinstance(d['item'], dict) and 'pattern' in d['item']:
                reasons.setdefault(sz.train_parts(mapping.route_name(d['item']['route']))[1], d)
        reports = sz.live.get()
        rows = []
        for number in sorted(reports):
            d = reasons.get(number)
            status, at = ('shown', '') if number in drawn else (d['reason'], d['at']) if d else ('not in the train timetable on its way', 'scheduled.vehicles')
            rows.append({'feed': 'SZ-live', 'status': status, 'at': at, 'example': number})
        self._print(f'Map: SŽ live reports ({sz.live.status()})', rows)

    # ------------------------------------------------------------ boards from live

    def _live(self, members: set, sample: int, rng: random.Random):
        updates = sources.trip_updates.get().value
        vehicles = sources.vehicles.get().value
        wanted = []
        filed = {u['oldId'] for u in updates.values() if u.get('oldId')}  # checked under OTP's run (sources._with_old_ids)
        for trip_id, u in updates.items():
            if trip_id in filed:
                continue
            for stop_id, at, delay in coverage.upcoming(u, self.now + LEAD, self.horizon):
                wanted.append({'tripId': trip_id, 'stopId': stop_id, 'at': at, 'scheduled': at - (delay or 0)})
        with_update = set(updates)
        for v in vehicles:
            if v['quality'] == 'observed' and v.get('tripId') and v['tripId'] not in with_update and v.get('nextStopId'):
                wanted.append({'tripId': v['tripId'], 'stopId': v['nextStopId'], 'at': None, 'scheduled': None})
        at_stops = [w for w in wanted if w['stopId'] in members]
        others = [w for w in wanted if w['stopId'] not in members]
        chosen = at_stops + rng.sample(others, min(sample, len(others)))
        infos = sources.trip_info.get_many([w['tripId'] for w in chosen if not supplement.owns(w['tripId'])])
        infos.update({w['tripId']: supplement.trip_info(w['tripId']) for w in chosen if supplement.owns(w['tripId'])})
        route_index = sources.routes.get().value
        names = sources.stop_names()
        for w in chosen:
            route = route_index.get((infos.get(w['tripId']) or {}).get('routeId')) or {}
            w['routeName'] = mapping.route_name(route) if route else None
        boards = self._boards(sorted({(w['stopId'], 'departure') for w in chosen if w['stopId'] in names}))
        for w in chosen:
            if w['stopId'] in names:
                w['status'] = coverage.board_status(w, *boards[(w['stopId'], 'departure')])
        # A run at its last stop is on the arrivals board.
        boards.update(self._boards(sorted({(w['stopId'], 'arrival') for w in chosen if w.get('status', ('',))[0] == 'ends here'})))
        day = (datetime.fromtimestamp(self.now, LOCAL) - timedelta(hours=sources.SERVICE_DAY_ENDS_HOUR)).strftime('%Y%m%d')
        # The feed moves on while the boards are read (minutes): a bus can pass early in between (Kranj 4, 2.5 min).
        latest = sources.trip_updates.get().value
        rows = []
        for w in chosen:
            if w['stopId'] not in names:
                status, at = 'stop not in our stop index', 'sources._load_stops'
            else:
                status, at = w['status']
                kind = 'departure'
                if status == 'ends here':  # read in a second pass, minutes later: by then the bus may have come
                    kind = 'arrival'
                    status, at = coverage.board_status(w, *boards[(w['stopId'], kind)])
                # Its live time (as last known) before the board was read: then, or by the board's own note (an early bus that went)
                when = coverage.time_at(latest.get(w['tripId']), w['stopId']) or w['at']
                if status == 'gone before the board starts' or (status not in coverage.SHOWN and when and when < self.read_at[(w['stopId'], kind)] + 60):
                    status, at = coverage.GONE, ''
                if status == 'not returned by OTP for the board':
                    status = w['otp'] = self._otp_reason(w['tripId'], w['stopId'], day) if (infos.get(w['tripId']) or {}).get('routeId') else 'trip not in OTP (upstream)'
            rows.append({'feed': coverage.feed(w['tripId']), 'status': status, 'at': at,
                         'example': f'{w["tripId"]}@{w["stopId"]}' + (f' {datetime.fromtimestamp(w["at"], LOCAL):%H:%M}' if w['at'] else '')})
        self.results['live'] = rows
        self._print(f'Boards from live: {len(at_stops)} at the stops + {len(chosen) - len(at_stops)} of {len(others)} elsewhere', rows, coverage.SHOWN + coverage.REPLACED + (coverage.GONE,))

    # ------------------------------------------------------------ boards from the timetable

    def _timetable(self, picked: list[dict]):
        start, end = self.now + 60, self.now + self.horizon
        service = datetime.fromtimestamp(self.now, LOCAL) - timedelta(hours=sources.SERVICE_DAY_ENDS_HOUR)
        days = [(service - timedelta(days=1)).strftime('%Y%m%d'), service.strftime('%Y%m%d')]
        updates = sources.trip_updates.get().value

        def expected(stop: dict) -> list[dict]:
            out = []
            for m in stop.get('memberIds') or [stop['id']]:
                if supplement.owns(m):
                    own = supplement.stoptimes(m, start, end - start, 10_000, updates) or []
                    patterns = [{'pattern': {'route': st['trip']['route']}, 'stoptimes': [st]} for st in own]
                else:
                    patterns = []
                    for d in days:
                        try:
                            patterns += (otp().query(STOPTIMES_Q, {'id': m, 'date': d}).get('stop') or {}).get('stoptimesForServiceDate') or []
                        except UpstreamError:
                            pass
                runs = coverage.timetable_departures(patterns, m, start, end)
                out += [{**r, 'stopId': m, 'scheduled': r['at'], 'day': days[1]} for r in runs]
            return out

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            wanted = dict(zip((s['id'] for s in picked), pool.map(expected, picked)))
        boards = self._boards([(s['id'], 'departure') for s in picked])
        rows, doubles = [], []
        for s in picked:
            target, here, drops = boards[(s['id'], 'departure')]
            seen = set()
            for w in wanted[s['id']]:
                if (w['tripId'], w['at']) in seen:
                    continue  # the same run at two members of the group
                seen.add((w['tripId'], w['at']))
                status, at = coverage.board_status(w, target, here, drops)
                if status not in coverage.SHOWN and w['at'] < self.read_at[(s['id'], 'departure')] + 60:
                    status, at = coverage.GONE, ''
                if status == 'not returned by OTP for the board':
                    status = self._otp_reason(w['tripId'], w['stopId'], w['day'])
                rows.append({'feed': coverage.feed(w['tripId']), 'status': status, 'at': at,
                             'example': f'{w["routeName"]} {datetime.fromtimestamp(w["at"], LOCAL):%H:%M} {w["tripId"]}@{s["name"]}'})
            for a, b in coverage.duplicates(target or []):
                doubles.append({'feed': coverage.feed(b.get('tripId')), 'status': 'listed twice', 'at': 'target API',
                                'example': f'{a.get("routeName")} {a.get("scheduledAt")} {a.get("tripId")} + {b.get("tripId")}@{s["name"]}'})
        self.results['timetable'], self.results['twice'] = rows, doubles
        self._print(f'Boards from timetable: next {self.horizon // 60} min at {len(picked)} stops', rows, coverage.SHOWN + coverage.REPLACED + (coverage.GONE,))
        self._print('Boards: the same run twice', doubles, ok=())

    # ------------------------------------------------------------ replay of recorded days

    def _replay(self, snap: dict, members: set, days: int, rng: random.Random):
        from prestop_statistics.models import VehicleTrip
        routes = {r for m in members for r in snap['routes'].get(m, ())}
        today = (datetime.fromtimestamp(self.now, LOCAL) - timedelta(hours=sources.SERVICE_DAY_ENDS_HOUR)).date()
        rows = []
        recorded_days = VehicleTrip.objects.filter(service_date__lt=today).values_list('service_date', flat=True).distinct().order_by('-service_date')[:days]
        for day in recorded_days:
            recorded = list(VehicleTrip.objects.filter(service_date=day).values_list('trip_id', 'route_id'))
            mine = [t for t in recorded if t[1] in routes]
            rest = [t for t in recorded if t[1] not in routes]
            chosen = rng.sample(mine, min(60, len(mine))) + rng.sample(rest, min(40, len(rest)))
            self.stdout.write(f'replay {day}: {len(recorded)} recorded trips, {len(mine)} on lines of the stops, checking {len(chosen)}')

            def one(trip):
                trip_id = trip[0]
                # The operator's file (supplement.py) is a rolling window from yesterday (Kranj: 21-30 Oct on the 22nd).
                if supplement.owns(trip_id) and not supplement.otp_trip(trip_id, day):
                    return {'feed': coverage.feed(trip_id), 'status': "operator's file no longer covers that day (replay artifact)", 'at': '', 'example': trip_id}
                try:
                    data = otp().query(TRIP_DAY_Q, {'id': trip_id, 'date': day.strftime('%Y%m%d')}).get('trip')
                except UpstreamError:
                    return {'feed': coverage.feed(trip_id), 'status': 'OTP unavailable', 'at': '', 'example': trip_id}
                calls = [c for c in (data or {}).get('stoptimesForDate') or [] if c.get('pickupType') != 'NONE'][:-1]
                if not calls:
                    return {'feed': coverage.feed(trip_id), 'status': 'trip id not in OTP now (newer feed, or upstream)' if not data else 'trip not running that day in OTP (upstream)', 'at': '', 'example': trip_id}
                call = next((c for c in calls if (c.get('stop') or {}).get('gtfsId') in members), calls[len(calls) // 2])
                stop_id, at = call['stop']['gtfsId'], call['serviceDay'] + call['scheduledDeparture']
                drops: list = []
                here = sources._board(stop_id, 'departure', at - 600, 'sl', drops)
                w = {'tripId': trip_id, 'routeName': mapping.route_name(data.get('route') or {}), 'scheduled': at}
                status, where = coverage.board_status(w, here, here, drops)
                return {'feed': coverage.feed(trip_id), 'status': status, 'at': where,
                        'example': f'{w["routeName"]} {datetime.fromtimestamp(at, LOCAL):%H:%M} {trip_id}@{stop_id}'}
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                rows += list(pool.map(one, chosen))
        self._print(f'Replay: recorded trips of the last {days} recorded days on this code\'s boards', rows, coverage.SHOWN + coverage.REPLACED)

