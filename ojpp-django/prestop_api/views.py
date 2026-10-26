"""/api/v1: the Prestop facade the React app's live mode talks to.

Responses use the `{data, meta}` envelope from `src/contracts/transit.ts`; errors are
`{error: {code, message, retryable}, requestId}`. Upstream failures become 503 with
`retryable: true`; a cached value is served as `stale` while it is recent enough.
"""
import json
import logging
import math
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Optional
from functools import wraps

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import journeys as planner
from . import citytt, coverage, geometry, mapping, maplinks, operator_notices, sources, stopservice, supplement, trips, variants, warm
from . import operators as companies
from .upstream import Cached, UpstreamError, otp

logger = logging.getLogger(__name__)
STOPS_PAGE = 4000
ALERT_HORIZON = 3 * 86400
# Planning waits seconds on OTP; with gunicorn's few threads per worker, unbounded plans could take them all and
# stall every other request. At most PLAN_SLOTS plans per worker at once; one waits PLAN_WAIT s for a slot, then
# gets a retryable 503 (spec 2026-10-18 A6). Expanding a pasted short link (up to a few hops) gets one slot.
PLAN_SLOTS = 2
PLAN_WAIT = 5.0
_plan_slots = threading.BoundedSemaphore(PLAN_SLOTS)
_expand_slots = threading.BoundedSemaphore(1)
SLOVENIA = (13.3, 45.38, 16.65, 46.9)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def error_response(status, code, message, retryable=False):
    return JsonResponse({'error': {'code': code, 'message': message, 'retryable': retryable}, 'requestId': uuid.uuid4().hex[:12]}, status=status)


def bounded(slots: threading.BoundedSemaphore):
    """Runs the view only when one of `slots` is free within PLAN_WAIT s; else a retryable 503."""
    def wrap(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not slots.acquire(timeout=PLAN_WAIT):
                raise ApiError(503, 'BUSY', 'Many trips are being planned right now. Please try again in a moment.', True)
            try:
                return view(request, *args, **kwargs)
            finally:
                slots.release()
        return inner
    return wrap


def api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.PRESTOP_WARM:
            warm.touch()
        try:
            return view(request, *args, **kwargs)
        except ApiError as e:
            return error_response(e.status, e.code, e.message, e.retryable)
        except planner.RequestError as e:
            return error_response(422, e.code, str(e))
        except UpstreamError as e:
            logger.warning('%s: upstream failed: %s', request.path, e)
            return error_response(503, 'UPSTREAM_UNAVAILABLE', 'A transit data source is temporarily unavailable. Please retry.', True)
    return wrapper


# ---------------------------------------------------------------- envelope

def _source(id_, name, cache: Cached, capabilities, live_age: float):
    snap = cache.peek()
    if not snap:
        status, updated = 'unavailable', None
    else:
        status = 'stale' if snap.error or snap.age > live_age else 'live'
        updated = mapping.iso(snap.fetched_at)
    return {'id': id_, 'name': name, 'status': status, 'updatedAt': updated, 'capabilities': capabilities}


def _collector_source():
    from prestop_statistics.models import CollectorState
    from prestop_statistics.collector import SOURCE
    state = CollectorState.objects.filter(source=SOURCE).first()
    if not state or not state.last_success:
        return {'id': 'prestop:statistics', 'name': 'KamGre delay collector', 'status': 'unavailable', 'updatedAt': None, 'capabilities': ['statistics']}
    age = time.time() - state.last_success.timestamp()
    return {'id': 'prestop:statistics', 'name': 'KamGre delay collector', 'status': 'live' if age < 300 else 'stale',
            'updatedAt': state.last_success.isoformat().replace('+00:00', 'Z'), 'capabilities': ['statistics']}


def all_sources():
    return [
        _source('otp:timetables', 'OpenTripPlanner (OJPP gateway): timetables with realtime, journeys', sources.routes, ['stops', 'boards', 'journeys'], 2 * 3600),
        _source('gtfs-rt:vehicles', 'Combined GTFS-Realtime vehicle positions', sources.positions, ['vehicles'], 60),
        _source('gtfs-rt:trip-updates', 'Combined GTFS-Realtime trip updates', sources.trip_updates, ['vehicles', 'boards'], 120),
        _source('otp:alerts', 'Provider service alerts (incl. SŽ disruptions)', sources.alerts_raw, ['alerts'], 300),
        _source('otp:rentals', 'Bike and scooter sharing (GBFS via OTP)', sources.rentals, ['rentals'], 300),
        _sz_source(),
        _sz_delays_source(),
        _sz_notices_source(),
        _sz_news_source(),
        # Arriva's site notices: the server can be shut out of the site (ConnectTimeout from Oracle on 2026-10-15),
        # so /health says when they are missing instead of the disruptions list just lacking them.
        _source('operator-site:arriva', "Arriva's website notices", operator_notices.arriva, ['alerts'], 3600),
        *_gbfs_sources(),
        # City bus timetables built from the operators' pages on a PC (citytt): a failed build or one near its end.
        *citytt.health(datetime.now(supplement.LOCAL).date()),
    ]


def _gbfs_sources():
    """One entry per operator GBFS feed read directly; a failed feed is listed as unavailable."""
    from . import gbfs
    snap = gbfs.networks.peek()
    out = []
    for network in gbfs.feeds():
        feed = (snap.value if snap else {}).get(network) or {}
        ok = bool(feed.get('ok'))
        status = ('stale' if time.time() - feed['updated'] > 600 else 'live') if ok else 'unavailable'
        out.append({'id': f'gbfs:{network}', 'name': f'Bike share: {mapping.provider_name(network)} (GBFS {feed.get("version", "?")})',
                    'status': status, 'updatedAt': mapping.iso(feed['updated']) if ok else None, 'capabilities': ['rentals']})
    return out


def _sz_source():
    from . import sz
    return sz_feed_source('sz:live', 'SŽ live train delays (community feed)', sz.live, ['vehicles'])


def _sz_news_source():
    """SŽ's RSS (its passenger notices: text alerts while the closure notices are down); `since`: its last answer."""
    entry = _source('sz:news', "SŽ news and passenger notices (RSS)", operator_notices.sz_news, ['alerts'], 3600)
    snap = operator_notices.sz_news.peek()
    return {**entry, 'since': mapping.iso(snap.fetched_at) if snap else None}


def _sz_delays_source():
    from . import sz
    return sz_feed_source('sz:delays', "SŽ delay table: measured and expected delays (derp-si scraper)", sz.delays, ['vehicles'])


def sz_feed_source(id_, name, feed, capabilities):
    """A polled SŽ feed (sz.Feed); `since`: when it last answered (outages() counts from it)."""
    since = mapping.iso(feed.last_ok) if feed.last_ok else None
    return {'id': id_, 'name': name, 'status': feed.status(), 'updatedAt': since, 'capabilities': capabilities, 'since': since}


def _sz_debug() -> dict:
    """Debug counts for SŽ delays (not shown in the app): which source each train's delay came from, how often two
    fresh sources disagreed by over 2 min today (trainlive.agreement), and ijpp-rt's own trip-update feed."""
    from . import sz, trainlive
    rt = sz_feed_source('sz:rt', 'ijpp-rt SŽ trip updates', sz.rt, [])
    return {**trainlive.agreement.counts(), 'rt': {'status': rt['status'], 'since': rt['since'], 'url': sz.rt.used}}


STARTED = time.time()
OUTAGE = 30 * 60  # s an SŽ source may be down before /health lists it under `outages` (server:top, the watchdog)


def outages(srcs: list[dict], now: Optional[float] = None) -> list[dict]:
    """SŽ sources not live for more than OUTAGE s, counted from their last success (or this server's start)."""
    now = now or time.time()
    out = []
    for s in srcs:
        if not s['id'].startswith('sz:') or s['status'] == 'live':
            continue
        since = datetime.fromisoformat(s['since'].replace('Z', '+00:00')).timestamp() if s.get('since') else STARTED
        if now - since > OUTAGE:
            out.append({'id': s['id'], 'status': s['status'], 'since': s.get('since'), 'minutes': int((now - since) // 60)})
    return out


def _sz_notices_source():
    from . import closures
    return closures.notices_source()


def envelope(data, status: str, used=(), source_updated=None, extra: dict | None = None):
    data = companies.rewrite(data)  # one operator id per company, whichever feed it came from
    srcs = [s for s in all_sources() if not used or s['id'] in used]
    if source_updated is None:
        stamps = [s['updatedAt'] for s in srcs if s['updatedAt']]
        source_updated = min(stamps) if stamps else None
    return JsonResponse({'data': data, 'meta': {'generatedAt': mapping.iso(time.time()), 'sourceUpdatedAt': source_updated,
                                                'status': status, 'sources': srcs}, **(extra or {})})


def snapshot_status(cache: Cached, live_age: float) -> str:
    snap = cache.peek()
    return 'unavailable' if not snap else ('stale' if snap.error or snap.age > live_age else 'live')


# ---------------------------------------------------------------- params

def language(request) -> str:
    lang = request.GET.get('lang') or request.headers.get('Accept-Language', '')
    return 'sl' if lang.lower().startswith('sl') else 'en'


def bbox_param(request, required=True):
    raw = request.GET.get('bbox')
    if not raw:
        if required:
            raise ApiError(422, 'INVALID_BBOX', 'bbox is required as minLon,minLat,maxLon,maxLat')
        return SLOVENIA
    try:
        box = [float(v) for v in raw.split(',')]
    except ValueError:
        box = []
    if len(box) != 4 or not all(math.isfinite(v) for v in box) or not (-180 <= box[0] <= box[2] <= 180 and -90 <= box[1] <= box[3] <= 90):
        raise ApiError(422, 'INVALID_BBOX', 'bbox must be minLon,minLat,maxLon,maxLat within valid ranges')
    return box


def operator_filter(operator):
    """Predicate for items run by `operator`, given by its canonical id or any id merged into it (operators.py)."""
    if not operator:
        return lambda op_id: True
    ids = companies.table()['canonical']
    want = companies.canonical(operator, ids)
    return lambda op_id: companies.canonical(op_id, ids) == want


def inside(item, box):
    return box[0] <= item['longitude'] <= box[2] and box[1] <= item['latitude'] <= box[3]


def parse_time(raw, field):
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        raise ApiError(422, 'INVALID_TIME', f'{field} must be an ISO timestamp with offset')
    if value.tzinfo is None:
        raise ApiError(422, 'INVALID_TIME', f'{field} must include a UTC offset')
    return value


# ---------------------------------------------------------------- endpoints

@require_GET
@api
def health(request):
    database = 'ready'
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception:
        database = 'unavailable'
    # coverage: the collector's last count of the buses the map and a few boards leave out (coverage.Sampler)
    srcs = all_sources()
    body = {'api': 'ready', 'database': database, 'sources': srcs, 'collector': _collector_source() if database == 'ready' else None,
            'maintenance': _maintenance(), 'coverage': coverage.latest(), 'outages': outages(srcs), 'sz': _sz_debug()}
    return JsonResponse(body, status=200 if database == 'ready' else 503)


MAINTENANCE_GRACE = 600


def _maintenance():
    """The deploy's maintenance notice, or None. A flag left behind by a failed deploy stops
    counting ten minutes after its `until`, so the app never shows it for good."""
    path = settings.PRESTOP_MAINTENANCE_FILE
    if not path:
        return None
    try:
        with open(path, encoding='utf-8') as f:
            flag = json.load(f)
        until = datetime.fromisoformat(flag['until'])
        message = {'sl': str(flag['message']['sl']), 'en': str(flag['message']['en'])}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if until.tzinfo is None or until.timestamp() + MAINTENANCE_GRACE < time.time():
        return None
    return {'message': message, 'until': until.isoformat()}


@require_GET
@api
def capabilities(request):
    routes = sources.routes.get().value
    operators = {}
    for r in routes.values():
        if not r.get('agencyId'):
            continue
        op = operators.setdefault(r['agencyId'], {'id': r['agencyId'], 'name': r.get('agencyName') or r['agencyId'], 'modes': set()})
        op['modes'].add(mapping.mode_of(r.get('mode')))
    try:
        from . import gbfs
        snap = gbfs.networks.peek()
        # A GBFS feed's own system name ("KolesCE") beats the generic one ("Nextbike").
        own = {n: f['name'] for n, f in (snap.value if snap else {}).items() if f.get('ok') and f.get('name')}
        providers = {}
        for item in sources.rentals.get().value:
            network = item['providerId'].split(':')[0]
            providers.setdefault(item['providerId'], {'id': item['providerId'], 'name': own.get(network) or mapping.provider_name(item['providerId']), 'modes': {item['mode']}})
    except UpstreamError:
        providers = {}
    listed = [{**o, 'modes': sorted(o['modes'])} for o in [*operators.values(), *providers.values()]]
    data = {
        'operators': sorted(companies.merge_rows(listed), key=lambda o: o['name']),
        'modes': ['walk', 'bus', 'rail', 'bike', 'scooter'],
        'sources': [*all_sources(), _collector_source()],
        'journeyPlanning': True, 'viaRouting': True,
        'insaneMode': settings.PRESTOP_INSANE_MODE,
        'push': bool(settings.PRESTOP_VAPID_PUBLIC_KEY and settings.PRESTOP_VAPID_PRIVATE_KEY),
    }
    if data['push']:
        data['pushKey'] = settings.PRESTOP_VAPID_PUBLIC_KEY
    return envelope(data, snapshot_status(sources.routes, 2 * 3600))


@require_GET
@api
def locale(request):
    header = settings.PRESTOP_TRUSTED_COUNTRY_HEADER
    country = request.headers.get(header, '') if header else ''
    if country:
        return envelope({'suggestedLanguage': 'sl' if country.upper() == 'SI' else 'en', 'source': 'ip'}, 'live', used=['none'])
    return envelope({'suggestedLanguage': 'en', 'source': 'default'}, 'live', used=['none'])


def _linked_places(q: str, scope: str, limit: int, lang: str) -> list[dict]:
    """A pasted map link or coordinates: the pinned place, or with `stations` the stops nearest to it."""
    coords, name = maplinks.parse_coordinates(q), None
    if not coords:
        url = q
        if not q.lower().startswith('geo:'):
            # One expansion at a time per worker: a short link costs a few requests to Google.
            if not _expand_slots.acquire(timeout=2):
                return []
            try:
                url = maplinks.expand(q)
            finally:
                _expand_slots.release()
        parsed = maplinks.parse_link(url) if url else None
        if not parsed:
            return []
        if not parsed['coords']:
            try:
                found = sources.geocode(parsed['query'], limit, lang)
            except UpstreamError:
                return []
            if scope != 'stations' or not found:
                return found
            coords = (found[0]['latitude'], found[0]['longitude'])
        else:
            coords, name = parsed['coords'], parsed['name']
    lat, lon = coords
    if scope == 'stations':
        near = sorted(((geometry.distance([lon, lat], [s['longitude'], s['latitude']]), s) for s in stopservice.markers()
                       if abs(s['latitude'] - lat) < 0.02 and abs(s['longitude'] - lon) < 0.03), key=lambda pair: pair[0])
        # Nearest platform per stop name: one row per station, not per platform.
        nearest = {}
        for d, s in near:
            if d <= 1500:
                nearest.setdefault(s['name'], s)
        return [{'id': s['id'], 'name': s['name'], 'kind': 'station', 'stopId': s['id'], 'modes': s['modes'],
                 'latitude': s['latitude'], 'longitude': s['longitude']} for s in nearest.values()][:limit]
    return [{'id': f'geo:{lat:.6f},{lon:.6f}', 'name': name or f'{lat:.5f}, {lon:.5f}', 'latitude': round(lat, 6), 'longitude': round(lon, 6),
             'kind': 'poi' if name else 'address'}]


def near_param(request):
    """Optional `near=lat,lon` (the person's location or the map centre) to bias place search."""
    try:
        lat, lon = (float(v) for v in (request.GET.get('near') or '').split(','))
    except ValueError:
        return None
    return (lat, lon) if 45 < lat < 47.5 and 12.5 < lon < 17.5 else None


@require_GET
@api
def places(request):
    q = (request.GET.get('q') or '').strip()
    scope = request.GET.get('scope', 'all')
    try:
        limit = max(1, min(20, int(request.GET.get('limit', 10))))
    except ValueError:
        raise ApiError(422, 'INVALID_LIMIT', 'limit must be a number')
    if scope not in ('all', 'stations'):
        raise ApiError(422, 'INVALID_SCOPE', 'scope must be all or stations')
    if len(q) < 2:
        return envelope([], 'live', used=['otp:timetables'])
    if maplinks.parse_coordinates(q) or maplinks.looks_like_link(q):
        return envelope(_linked_places(q, scope, limit, language(request)), 'live', used=['otp:timetables'])
    stations = sources.search_stations(q, limit)
    if scope == 'stations':
        return envelope(stations, 'live', used=['otp:timetables'])
    try:
        addresses, complete = sources.geocode_soon(q, limit, language(request), near_param(request))
    except UpstreamError:
        addresses, complete = [], True
    # Stops whose name starts with the query come first; stops that only contain it
    # ("Boštanj - HOFER" for "hofer") go after the places themselves.
    needle = mapping.fold(q)
    leading = [s for s in stations if mapping.fold(s['name']).startswith(needle)]
    others = [s for s in stations if s not in leading]
    take = max(math.ceil(limit * 0.6), limit - len(addresses))
    result = (leading[:take] + addresses + others)[:limit]
    # partial: a geocoder is still answering (places.search); asking again shortly gives the whole list.
    return envelope(result, 'live', used=['otp:timetables'], extra=None if complete else {'partial': True})


@require_GET
@api
def stops(request):
    box = bbox_param(request)
    mode, run_by = request.GET.get('mode'), operator_filter(request.GET.get('operatorId'))
    # Stops with no trip in the next days are left out (stopservice.py); `stopId` finds the one holding that stop anyway.
    items = [s for s in stopservice.markers(request.GET.get('stopId')) if inside(s, box) and (not mode or mode in s['modes']) and run_by(s['operatorId'])]
    try:
        offset = int(request.GET.get('cursor') or 0)
    except ValueError:
        raise ApiError(422, 'INVALID_CURSOR', 'Unknown cursor')
    page = items[offset:offset + STOPS_PAGE]
    cursor = str(offset + STOPS_PAGE) if offset + STOPS_PAGE < len(items) else None
    return envelope({'items': page, 'cursor': cursor}, 'scheduled', used=['otp:timetables'])


@require_GET
@api
def vehicles(request):
    route = request.GET.get('routeId')
    box = bbox_param(request, required=not route)
    mode, run_by = request.GET.get('mode'), operator_filter(request.GET.get('operatorId'))
    items = [v for v in sources.vehicles.get().value if inside(v, box) and (not mode or v['mode'] == mode)
             and run_by(v['operatorId']) and (not route or v['routeId'] == route)]
    return envelope(items, snapshot_status(sources.positions, 60), used=['gtfs-rt:vehicles', 'gtfs-rt:trip-updates', 'sz:live', 'sz:delays'])


@require_GET
@api
def rentals(request):
    box = bbox_param(request)
    by = operator_filter(request.GET.get('provider'))
    items = [r for r in sources.rentals.get().value if inside(r, box) and by(r['providerId'])]
    return envelope(items, snapshot_status(sources.rentals, 300), used=['otp:rentals'])


@require_GET
@api
def board(request, stop_id):
    kind = request.GET.get('kind', 'departure')
    if kind not in ('departure', 'arrival'):
        raise ApiError(422, 'INVALID_KIND', 'kind must be departure or arrival')
    at = parse_time(request.GET.get('at') or mapping.iso(time.time()), 'at')
    items = sources.board(stop_id, kind, int(at.timestamp()), language(request))
    if items is None:
        raise ApiError(404, 'STOP_NOT_FOUND', 'This stop is not in the current timetable.')
    status = 'live' if any(i['quality'] for i in items) else 'scheduled'
    return envelope({'items': items, 'cursor': None}, status, used=['otp:timetables', 'gtfs-rt:trip-updates'], source_updated=mapping.iso(time.time()))


@csrf_exempt
@require_POST
@api
@bounded(_plan_slots)
def journeys(request):
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON body')
    req = planner.parse_request(body, settings.PRESTOP_INSANE_MODE)
    from . import city_journeys
    # Where the town search of city buses OTP does not know got to on the page before (city_journeys.py).
    req, city_anchor = city_journeys.take_anchor(req)
    from . import scheduled
    # What replaces trains that day (today's and tomorrow's are kept warm; another date's takes a few seconds once):
    # OTP's time moves for the trains whose replacement bus has its own times (journey_legs.search_gain).
    from . import journey_legs
    day_plan = scheduled.plan_at(req['dateTime'].timestamp(), wait=6, cold=True)
    if not req['pageCursor'] and (shift := journey_legs.search_gain(day_plan, req)):
        req = {**req, 'searchShift': shift}
    asked = [0]  # OTP queries this request (shared rules: at most planner.MAX_OTP_QUERIES with the extra searches)

    def counted(timeout):
        def query(q, v):
            if asked[0] >= planner.MAX_OTP_QUERIES:
                return {'planConnection': {'edges': [], 'pageInfo': {}, 'routingErrors': []}}  # budget spent: nothing more
            asked[0] += 1
            return otp().query(q, v, timeout=timeout)
        return query
    data = planner.plan(req, counted((5, 45)))
    page = planner.page_info(data, req)
    data = planner.bet_on_delays(data, req, counted((5, 20)))
    # Searches OTP cannot fold into one (driving, drive + park + ride, scooters next to bikes, the rider's own bike
    # networks): with what is left of the budget, and cached.
    data = planner.with_extras(data, req, counted((5, 20)), budget=planner.MAX_OTP_QUERIES - asked[0])
    # City buses OTP does not know (Kranj's full timetable, Sevnica, Jesenice): inside a town, and at either end of
    # OTP's connections, with one more search via a town's station when none comes near (within the budget).
    data, city_anchors = city_journeys.add(data, req, city_anchor, counted((5, 20)), budget=planner.MAX_OTP_QUERIES - asked[0])
    page = city_journeys.mark(page, city_anchors)
    errors = (data.get('planConnection') or {}).get('routingErrors') or []
    try:
        alert_list = sources.alerts(language(request))
    except UpstreamError:
        alert_list = []
    result = planner.build_journeys(data, req, alert_list, plan_for=lambda when: scheduled.plan_at(when, wait=6, cold=True))
    result = planner.within_time(result, req)
    # Short lines per leg: the train a bus replaces, a detour or moved stop on the leg's line.
    from . import leg_alerts
    result = leg_alerts.add_notices(result, alert_list, language(request))
    if any(leg.get('rental') for j in result for leg in j['legs']):
        from . import sharing
        # E-scooters walk where they may not ride (roads over 50 km/h without a cycle lane, ZPrCP 97.a).
        result = [j for j in (sharing.scooter_rules(j) for j in result) if j is not None]
        # Shared rides: when their free time ends, and a swap at a station along the way when that keeps it free.
        try:
            stations = sources.rentals.get().value
        except UpstreamError:
            stations = []
        result = [sharing.free_periods(j, stations) for j in result]
    if req['maxTransfers'] is not None:
        # OTP's limit counts a stay-seated through-run differently; the rider's count is the one shown.
        result = [j for j in result if j['transferCount'] <= req['maxTransfers']]
    if req['riskMode'] == 'insane':
        result = planner.by_arrival(result)
    if req['showPrices']:
        # The rider's cards (request body only) price this answer and are dropped with it.
        from . import pricing
        result = [pricing.price_journey(j, req['priceProfile'], language(request)) for j in result]
        result = pricing.rank(pricing.member_rides(result, req), req)
    if not result and errors:
        codes = {e.get('code') for e in errors}
        if codes & {'OUTSIDE_BOUNDS', 'LOCATION_NOT_FOUND'}:
            raise ApiError(422, 'LOCATION_NOT_FOUND', 'A place is outside the area we cover or too far from any street.')
        if 'OUTSIDE_SERVICE_PERIOD' in codes:
            raise ApiError(422, 'OUTSIDE_SERVICE_PERIOD', 'No timetable is published for that date yet.')
    status = 'live' if any(j['freshness'] == 'live' for j in result) else 'scheduled'
    # `wider`: nothing within the usual limits, so these were found as Insane mode would search (journeys.plan).
    return envelope(result, status, used=['otp:timetables', 'gtfs-rt:trip-updates'], source_updated=mapping.iso(time.time()),
                    extra={'page': page, **({'wider': True} if data.get('wider') and result else {})})


@require_GET
@api
def pricing_catalog(request):
    # Static: the dated tariff file's cards and bike memberships with their regions; cached a day.
    from . import pricing
    response = envelope(pricing.catalog(), 'live', used=['otp:timetables'])
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@require_GET
@api
def alerts(request):
    # Notices in effect now or starting within the horizon; far-off planned works would bury today's.
    horizon = time.time() + ALERT_HORIZON
    items = [a for a in sources.alerts(language(request)) if a['_from'] <= horizon]
    stop_id, route_id = request.GET.get('stopId'), request.GET.get('routeId')
    if stop_id:
        serving = sources.stops.get().value['routes'].get(stop_id, set())
        members = set(sources.stop_group(stop_id))
        items = [a for a in items if members & set(a['stopIds']) or serving & set(a['routeIds'])]
    if route_id:
        items = [a for a in items if route_id in a['routeIds']]
    if request.GET.get('journeyId'):
        items = []  # journeys are not stored; legs carry their own alertIds
    return envelope([mapping.public_alert(a) for a in items], snapshot_status(sources.alerts_raw, 300), used=['otp:alerts', 'sz:notices', 'operator-site:arriva'])


@csrf_exempt
@require_POST
@api
def alert_votes(request, alert_id):
    """Contract 6: "Is this right?" on a detected alert. Anonymous: no location, one vote per alert and device."""
    from . import detected
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON body')
    if not isinstance(body, dict):
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON object')
    header = settings.PRESTOP_CLIENT_IP_HEADER
    ip = (request.headers.get(header) if header else None) or request.META.get('REMOTE_ADDR') or ''
    try:
        votes = detected.vote(alert_id, body.get('vote'), body.get('deviceId'), ip)
    except detected.VoteError as e:
        raise ApiError(e.status, e.code, str(e))
    return envelope({'id': alert_id, 'votes': votes}, 'live')


@csrf_exempt
@require_POST
@api
def stats_hello(request):
    """The app's one-time "onboarding done": counts a new user (analytics.hello). No body, nothing stored about who."""
    from . import analytics
    ip = analytics.client_ip(request)
    if ip and settings.PRESTOP_ANALYTICS:
        try:
            analytics.hello(ip, request.headers.get('User-Agent', ''))
        except Exception as e:  # noqa: BLE001 — a lost count is no error for the app
            logger.info('stats hello not counted: %r', e)
    return HttpResponse(status=204)


def _hop(action):
    """Runs a Hop call (hop.py): its own errors become API errors, Redis trouble a retryable 503."""
    import redis
    from . import hop
    try:
        return action(hop)
    except hop.HopError as e:
        raise ApiError(e.status, e.code, str(e))
    except redis.RedisError:
        raise ApiError(503, 'HOP_UNAVAILABLE', 'Hop is not available right now. Please try again.', True)


def _hop_body(request) -> dict:
    from . import hop
    if len(request.body or b'') > hop.MAX_BODY:
        raise ApiError(413, 'TOO_LARGE', 'At most 4 KB.')
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON body')
    if not isinstance(body, dict):
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON object')
    return body


def _hop_ip(request) -> str:
    from . import analytics
    return analytics.client_ip(request) or request.META.get('REMOTE_ADDR') or ''


@csrf_exempt
@require_POST
@api
def hop_presence(request):
    """Hop: this device is here (every ~15 s while the app is visible); answers its code and the hops waiting for it."""
    body = _hop_body(request)
    return envelope(_hop(lambda hop: hop.presence(body, _hop_ip(request))), 'live', used=['none'])


@csrf_exempt
@require_POST
@api
def hop_nearby(request):
    """Hop: the phones nearby this device can send to, under tokens only it can use. A POST, so the device id
    stays out of the access log (which records URLs)."""
    body = _hop_body(request)
    return envelope(_hop(lambda hop: hop.nearby(body.get('device') if isinstance(body.get('device'), str) else '')), 'live', used=['none'])


@csrf_exempt
@require_POST
@api
def hop_send(request):
    """Hop: sends an app object (journey, stop, line, vehicle) to a nearby peer or a code."""
    body = _hop_body(request)
    return envelope(_hop(lambda hop: hop.send(body)), 'live', used=['none'])


@require_GET
@api
def statistics_routes(request):
    from prestop_statistics.models import TripDelay
    q, mode = mapping.fold(request.GET.get('q', '')), request.GET.get('mode')
    ids, run_by = companies.table()['canonical'], operator_filter(request.GET.get('operatorId'))
    since = date.today() - timedelta(days=30)
    measured = set(TripDelay.objects.filter(service_date__gte=since).values_list('route_id', flat=True).distinct())
    items = []
    groups = variants.table()  # contract 4: groupId and via
    for r in sources.routes.get().value.values():
        origin, destination = mapping.route_ends(r)
        operator = companies.canonical(r.get('agencyId'), ids) or f'{r["gtfsId"].split(":")[0]}:unknown'
        item = {'id': r['gtfsId'], 'name': mapping.route_name(r) or r['gtfsId'], 'operatorId': operator,
                'mode': mapping.mode_of(r.get('mode')), 'origin': origin, 'destination': destination,
                'directions': mapping.route_directions(r), 'qualities': ['observed'], **groups.get(r['gtfsId'], variants.of(r['gtfsId']))}
        if q and q not in mapping.fold(f'{item["name"]} {origin} {destination} {item["via"] or ""}'):
            continue
        if not run_by(item['operatorId']) or (mode and item['mode'] != mode):
            continue
        items.append((item['id'] not in measured, item['operatorId'], item['name'], item))
    items.sort(key=lambda t: t[:3])
    return envelope({'items': [t[3] for t in items], 'cursor': None}, 'live', used=['otp:timetables'])


_scheduled_cache: dict[str, tuple[float, dict]] = {}


def scheduled_trip_counts(route_id: str):
    hit = _scheduled_cache.get(route_id)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    data = otp().query('query($id: String!) { route(id: $id) { patterns { directionId trips { activeDates } } } }', {'id': route_id})
    counts: dict = {}
    for p in ((data.get('route') or {}).get('patterns') or []):
        direction = mapping.direction_key(p.get('directionId'))
        for t in p.get('trips') or []:
            for d in t.get('activeDates') or []:
                key = (datetime.strptime(d, '%Y%m%d').date(), direction)
                counts[key] = counts.get(key, 0) + 1
    if len(_scheduled_cache) > 2000:
        _scheduled_cache.clear()
    _scheduled_cache[route_id] = (time.time(), counts)
    return counts


@require_GET
@api
def statistics_daily(request, route_id):
    from prestop_statistics.aggregation import daily_statistics
    try:
        start, end = date.fromisoformat(request.GET['from']), date.fromisoformat(request.GET['to'])
    except (KeyError, ValueError):
        raise ApiError(422, 'INVALID_DATE_RANGE', 'from and to must be YYYY-MM-DD dates')
    if end < start or (end - start).days > 730:
        raise ApiError(422, 'INVALID_DATE_RANGE', 'The range must be ascending and at most 731 days')
    quality = request.GET.get('quality', 'observed')
    if quality not in ('observed', 'inferred', 'predicted'):
        raise ApiError(422, 'INVALID_QUALITY', 'quality must be observed, inferred or predicted')
    direction = request.GET.get('direction', 'all')
    try:
        scheduled = scheduled_trip_counts(route_id)
    except UpstreamError:
        scheduled = None
    days = daily_statistics(route_id, start, end, direction, quality, scheduled)
    collector = _collector_source()
    return envelope(days, collector['status'], used=['otp:timetables'], source_updated=collector['updatedAt'])


# ---------------------------------------------------------------- trips, lines, reliability

MAX_TRIPS = 60
MAX_RELIABILITY = 80
POINT_BUDGET = 40_000  # shape points per response (~0.9 MB of JSON): the app refuses responses over 2 MB
_derived: dict[tuple, tuple[float, object]] = {}


def _memo(key: tuple, ttl: float, load):
    """Small process-local memo for per-route statistics derived from the database."""
    hit = _derived.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = load()
    if len(_derived) > 5000:
        _derived.clear()
    _derived[key] = (time.time(), value)
    return value


def typical_segments(route_id: str) -> dict:
    from prestop_statistics.aggregation import typical_segments as load
    return _memo(('segments', route_id), 600, lambda: load(route_id, trips.service_day()))


def _dense(shapes: list[dict]) -> list[dict]:
    """Trips or line variants with their shapes densified, so the app can move vehicles smoothly along them
    (geometry.DENSE_STEP apart, wider when the response would get too big). Copies; cached values stay as they are."""
    step = max(geometry.DENSE_STEP, sum(s.get('length') or 0 for s in shapes) / POINT_BUDGET)
    return [{**s, 'geometry': geometry.densify(s['geometry'], step)} if s.get('geometry') else s for s in shapes]


def _typical(entry: dict) -> dict:
    """{'typical': {"from>to": s}, 'dwells': {stopId: learned}} for build_trip: the running and dwell times learned
    for the trip's route on its kind of day at its hour (prestop_statistics.learned), backed off to the route's
    plain 21-day medians."""
    # A synthetic replacement bus shares the train's route and stops, not its running times.
    if entry['static'].get('synthetic'):
        return {'typical': {}, 'dwells': {}}
    from prestop_statistics import learned
    from prestop_statistics.aggregation import day_kind
    route = entry['static']['routeId']
    first = min(entry['times'], key=lambda s: s['stopPosition'], default=None)
    hour = (first['scheduledDeparture'] // 3600) if first else 12
    segments, dwells = learned.lookup(route, day_kind(entry['serviceDate']), hour)
    return {'typical': {**typical_segments(route), **segments}, 'dwells': dwells}


def _ids_param(request, name: str, limit: int) -> list[str]:
    ids = [i for i in dict.fromkeys((request.GET.get(name) or '').split(',')) if i.strip()]
    if not ids:
        raise ApiError(422, 'INVALID_IDS', f'{name} is required as a comma-separated list')
    if len(ids) > limit:
        raise ApiError(422, 'INVALID_IDS', f'At most {limit} ids per request')
    return ids


def _day_param(request):
    raw = request.GET.get('date')
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(422, 'INVALID_DATE', 'date must be YYYY-MM-DD')


@require_GET
@api
def trip_list(request):
    ids = _ids_param(request, 'ids', MAX_TRIPS)
    geometry = request.GET.get('geometry', '1') != '0'
    found = trips.load_trips(ids, _day_param(request))
    data = [trips.build_trip(found[t], geometry=geometry, **_typical(found[t])) for t in ids if t in found]
    _with_observed(data, found)
    data = _dense(data)
    _with_replaced(data)
    status = 'live' if any(t['realtime'] for t in data) else 'scheduled'
    return envelope(data, status, used=['otp:timetables', 'gtfs-rt:trip-updates'], source_updated=mapping.iso(time.time()))


@require_GET
@api
def trip_detail(request, trip_id):
    found = trips.load_trips([trip_id], _day_param(request)).get(trip_id)
    if not found:
        raise ApiError(404, 'TRIP_NOT_FOUND', 'This trip is not in the current timetable.')
    data = trips.build_trip(found, **_typical(found))
    _with_observed([data], {trip_id: found})
    [data] = _dense([data])
    _with_replaced([data])
    return envelope(data, 'live' if data['realtime'] else 'scheduled', used=['otp:timetables', 'gtfs-rt:trip-updates'], source_updated=mapping.iso(time.time()))


def _with_replaced(data: list[dict]) -> None:
    """Each train's stretches that a replacement bus runs instead that day (`replacedSections`)."""
    from . import replacement, scheduled
    for trip in data:
        if trip['mode'] != 'rail' or not trip['stops']:
            continue
        try:
            sections = replacement.trip_sections(trip, scheduled.plan_at(replacement._epoch(trip['stops'][0]['scheduledDeparture']), wait=3))
        except Exception as e:  # The trip is still useful without them.
            logger.warning('Replaced sections failed: %r', e)
            continue
        if sections:
            trip['replacedSections'] = sections


def _with_observed(data: list[dict], found: dict[str, dict]) -> None:
    """Each stop's delay as the collector observed it once passed (null: never observed, not zero)."""
    from prestop_statistics.aggregation import observed_trip_delays
    try:
        observed = observed_trip_delays([(trip['id'], found[trip['id']]['serviceDate']) for trip in data])
    except Exception as e:  # The trips are still useful without their history.
        logger.warning('Observed delays failed: %r', e)
        return
    for trip in data:
        entry = found[trip['id']]
        delays = observed.get((trip['id'], entry['serviceDate']), {})
        # Stops in order; a loop line visits a stop twice, each visit with its own sequence.
        positions: dict[str, list[int]] = {}
        for stop in entry['static']['stops']:
            positions.setdefault(stop['stopId'], []).append(stop['position'])
        for stop in trip['stops']:
            queue = positions.get(stop['stopId']) or [None]
            position = queue.pop(0) if len(queue) > 1 else queue[0]
            stop['observedDelaySeconds'] = delays.get(str(position)) if position is not None else None


@require_GET
@api
def line_detail(request, route_id):
    line = trips.load_line(route_id, _day_param(request))
    if not line:
        raise ApiError(404, 'LINE_NOT_FOUND', 'This line is not in the current timetable.')
    line = _with_final_delays(line)
    # Contract 4: the line's group, what sets it apart, and the other variants of the group.
    grouped = {**variants.of(line['id']), 'variants': variants.siblings(line['id'])}
    patterns = _dense(line['patterns'])
    if line.get('mode') == 'rail':
        patterns = _with_sibling_trains(line['id'], patterns, grouped['variants'], _day_param(request))
    return envelope({**line, **grouped, 'patterns': patterns}, 'scheduled', used=['otp:timetables'])


SIBLING_TRAINS = 40


def _with_sibling_trains(route_id: str, patterns: list[dict], siblings: list[dict], day) -> list[dict]:
    """A train's line lists every train of its group (same ends, same direction) by departure, not by the way each
    takes: a sibling's departures join the pattern ending at the same stop, marked with their own `routeId`."""
    others = [s['routeId'] for s in siblings if s['routeId'] != route_id][:SIBLING_TRAINS]
    if not others or not patterns:
        return patterns
    patterns = [{**p, 'departures': [{**d, 'routeId': route_id} for d in p.get('departures') or []]} for p in patterns]
    by_end = {p['stops'][-1]['name']: p for p in patterns if p.get('stops')}
    for rid in others:
        try:
            other = trips.load_line(rid, day)
        except Exception as e:  # The line is still useful with its own trains only.
            logger.warning('Sibling train %s failed: %r', rid, e)
            continue
        for p in (other or {}).get('patterns') or []:
            target = by_end.get(p['stops'][-1]['name']) if p.get('stops') else None
            if target is not None:
                target['departures'] += [{**d, 'routeId': rid} for d in p.get('departures') or []]
    for p in patterns:
        p['departures'].sort(key=lambda d: d['departure'])
    return patterns


def _with_final_delays(line: dict) -> dict:
    """Departures that already ran carry the delay last observed on them (absent: never observed)."""
    from prestop_statistics.aggregation import final_observed_delays
    day = date.fromisoformat(line['serviceDate'])
    try:
        final = _memo(('final', line['id'], day), 60, lambda: final_observed_delays(line['id'], day))
    except Exception as e:
        logger.warning('Final delays failed: %r', e)
        return line
    if not final:
        return line
    # The cached line is shared: copy the patterns instead of writing into them.
    patterns = [{**p, 'departures': [{**d, 'observedDelaySeconds': final[d['tripId']]} if d['tripId'] in final else d for d in p.get('departures') or []]} for p in line['patterns']]
    return {**line, 'patterns': patterns}


@require_GET
@api
def statistics_reliability(request):
    from prestop_statistics.aggregation import route_reliability
    ids = _ids_param(request, 'routeIds', MAX_RELIABILITY)
    today = trips.service_day()
    data = [_memo(('reliability', r, today), 600, lambda r=r: route_reliability(r, today)) for r in ids]
    collector = _collector_source()
    return envelope(data, collector['status'], used=['otp:timetables'], source_updated=collector['updatedAt'])
