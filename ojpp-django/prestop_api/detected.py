"""Disruptions we see ourselves (contract 6, `source: 'detected'`), and what riders say about them.

A vehicle that stands more than HALT_SECONDS at a stop of its trip becomes a `vehicle-stopped` alert on its route,
unless the stop is where the trip starts or ends, and at a timed point (a scheduled wait) the clock only runs from
the scheduled departure. It clears when the vehicle moves MOVE_METERS or drops out of the feed. The collector
(`collect_delays`, one process) watches the feed every poll and keeps the candidates in memory; only real halts are
written (VehicleHalt), so the API's processes all see the same alerts.

Riders near one are asked "Is this right?" (the app; their location stays on the device): `vote` records one
answer per alert and device, salted hashes only, rate-limited by the hashed IP. Three or more "no" and no "yes"
hide it. Halts and votes are pruned after KEEP_DAYS.
"""
import hashlib
import math
import time
from datetime import datetime, timedelta, timezone as tz
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import mapping
from .models import AlertVote, VehicleHalt

HALT_SECONDS = 8 * 60
MOVE_METERS = 40       # moved this far from where it stood: going again
AT_STOP_METERS = 60    # standing this close to a stop of its trip: at that stop
TIMED_POINT = 120      # s between scheduled arrival and departure: a stop where the timetable waits
GONE_SECONDS = 180     # not reported for this long: the halt is over (or unknown)
FRESH_REPORT = 120     # a report older than this is a frozen GPS, not a vehicle standing still
KEEP_DAYS = 56
HIDE_NO = 3
VOTE_LIMIT = (20, 3600)  # votes per hashed IP per hour
PREFIX = 'detected:'
_candidates: dict[str, dict] = {}  # vehicle id -> where and since when it stands (collector process)
_pruned: dict = {'day': None}
_cache: dict = {'at': 0.0, 'rows': None}


def _meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    kx = 111_320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110_574)


def _stop_at(position: tuple, schedule: dict) -> Optional[dict]:
    """The stop of the trip the vehicle stands at: {'stopId', 'from' (epoch the halt may count from)}, None when it
    stands elsewhere, at the trip's first or last stop."""
    ordered = sorted(schedule['bySequence'].values(), key=lambda s: s['stopPosition'])
    best = None
    for i, s in enumerate(ordered):
        where = (s['stop'].get('lat'), s['stop'].get('lon'))
        if where[0] is not None and where[1] is not None and (d := _meters(position, where)) <= AT_STOP_METERS and (best is None or d < best[0]):
            best = (d, i, s)
    if not best or best[1] in (0, len(ordered) - 1):
        return None
    s = best[2]
    timed = s['scheduledDeparture'] - s['scheduledArrival'] >= TIMED_POINT
    return {'stopId': s['stop']['gtfsId'], 'from': (s.get('serviceDay') or 0) + s['scheduledDeparture'] if timed else 0}


def observe(schedules, positions: list[dict], now: Optional[float] = None) -> dict:
    """One poll of the vehicle feed: new halts are written, halts that ended are cleared."""
    from prestop_statistics.collector import _service_days
    now = now or time.time()
    stamp = datetime.fromtimestamp(now, tz.utc)
    seen = {}
    for e in positions:
        v = e.get('vehicle') or {}
        trip, pos = v.get('trip') or {}, v.get('position') or {}
        trip_id, vehicle = trip.get('tripId'), (v.get('vehicle') or {}).get('id')
        reported = int(v.get('timestamp') or 0)
        if not trip_id or not vehicle or ':' not in trip_id or pos.get('latitude') is None or now - reported > FRESH_REPORT:
            continue
        seen[mapping.qualify(vehicle, trip_id.split(':', 1)[0])] = (trip_id, trip, (pos['latitude'], pos['longitude']), reported)
    keys = [(t, d) for t, trip, _, _ in seen.values() for d in _service_days(trip, now)]
    found = schedules.get_many(keys)
    open_rows = {r.vehicle_id: r for r in VehicleHalt.objects.filter(cleared__isnull=True)}
    created = cleared = 0
    for vehicle_id, (trip_id, trip, position, reported) in seen.items():
        schedule = next((found[(trip_id, d)] for d in _service_days(trip, now) if found.get((trip_id, d))), None)
        cand = _candidates.get(vehicle_id)
        if cand and (cand['tripId'] != trip_id or _meters(cand['position'], position) > MOVE_METERS):
            cand = None
        if cand is None:
            row = open_rows.pop(vehicle_id, None)
            if row:
                row.cleared = stamp
                row.save(update_fields=['cleared'])
                cleared += 1
            at = _stop_at(position, schedule) if schedule else None
            _candidates[vehicle_id] = cand = {'tripId': trip_id, 'position': position, 'since': reported, 'stop': at,
                                              'routeId': schedule['routeId'] if schedule else None, 'reported': reported}
            continue
        if reported <= cand['reported']:  # the same report again: the feed is frozen, not the vehicle
            continue
        cand['reported'] = reported
        row = open_rows.pop(vehicle_id, None)
        stop = cand['stop']
        if row:
            row.last_seen = stamp
            row.save(update_fields=['last_seen'])
        elif stop and reported - max(cand['since'], stop['from']) > HALT_SECONDS:
            VehicleHalt.objects.create(vehicle_id=vehicle_id, trip_id=trip_id, route_id=cand['routeId'] or '', stop_id=stop['stopId'],
                                       latitude=position[0], longitude=position[1],
                                       since=datetime.fromtimestamp(max(cand['since'], stop['from']), tz.utc), last_seen=stamp)
            created += 1
    for vehicle_id in [v for v in _candidates if v not in seen]:
        del _candidates[vehicle_id]
    # Halts whose vehicle left the feed.
    for row in open_rows.values():
        if (stamp - row.last_seen).total_seconds() > GONE_SECONDS:
            row.cleared = stamp
            row.save(update_fields=['cleared'])
            cleared += 1
    return {'halts': created, 'cleared': cleared, 'pruned': prune(now)}


def prune(now: Optional[float] = None) -> int:
    day = datetime.fromtimestamp(now or time.time(), tz.utc).date()
    if _pruned['day'] == day:
        return 0
    _pruned['day'] = day
    cutoff = timezone.now() - timedelta(days=KEEP_DAYS)
    halts, _ = VehicleHalt.objects.filter(since__lt=cutoff).delete()
    votes, _ = AlertVote.objects.filter(created__lt=cutoff).delete()
    return halts + votes


# ---------------------------------------------------------------- alerts and votes (API)

TEXTS = {
    'sl': ('{route} stoji na postaji {stop}', 'Vozilo linije {route} že {minutes} min stoji na postaji {stop}, kjer po voznem redu ne čaka. '
           'Mogoča je motnja na progi.'),
    'en': ('{route} is standing at {stop}', 'A {route} vehicle has been standing at {stop} for {minutes} min, where the timetable '
           'does not wait. There may be a disruption.'),
}


def _open_rows() -> list:
    if _cache['rows'] is None or time.monotonic() - _cache['at'] > 20:
        cutoff = timezone.now() - timedelta(seconds=GONE_SECONDS)
        _cache.update(at=time.monotonic(), rows=list(VehicleHalt.objects.filter(cleared__isnull=True, last_seen__gte=cutoff)))
    return _cache['rows']


def tally(alert_ids) -> dict[str, dict]:
    counts = {i: {'yes': 0, 'no': 0} for i in alert_ids}
    for alert_id, vote in AlertVote.objects.filter(alert_id__in=list(counts)).values_list('alert_id', 'vote'):
        counts[alert_id]['yes' if vote else 'no'] += 1
    return counts


def alerts(language: str, routes: dict, stop_names: dict[str, str], now: Optional[float] = None) -> list[dict]:
    """Open halts as alerts (contract 6), without those riders voted down (HIDE_NO "no", no "yes")."""
    rows = _open_rows()
    if not rows:
        return []
    now = now or time.time()
    votes = tally([f'{PREFIX}{r.pk}' for r in rows])
    title, message = TEXTS.get(language, TEXTS['en'])
    out = []
    for r in rows:
        alert_id = f'{PREFIX}{r.pk}'
        v = votes[alert_id]
        if v['no'] >= HIDE_NO and v['yes'] == 0:
            continue
        route = routes.get(r.route_id) or {}
        names = {'route': mapping.route_name(route) or '?', 'stop': stop_names.get(r.stop_id) or r.stop_id,
                 'minutes': max(1, round((now - r.since.timestamp()) / 60))}
        start = r.since.timestamp()
        out.append({
            'id': alert_id, 'title': title.format(**names), 'message': message.format(**names),
            'operatorId': route.get('agencyId') or f'{r.route_id.split(":", 1)[0]}:unknown', 'stopIds': [r.stop_id], 'routeIds': [r.route_id],
            'validFrom': mapping.iso(start), 'validTo': None, 'from': mapping.iso(start), 'to': None, 'sourceUrl': None,
            'kind': 'vehicle-stopped', 'source': 'detected', 'vehicleId': r.vehicle_id,
            'latitude': round(r.latitude, 6), 'longitude': round(r.longitude, 6), 'votes': v,
            '_from': start, '_to': None, '_aliases': [alert_id],
        })
    return out


class VoteError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _hash(value: str) -> str:
    return hashlib.sha256(settings.SECRET_KEY.encode() + value.encode()).hexdigest()[:40]


def vote(alert_id: str, answer: str, device_id: Optional[str], ip: str) -> dict:
    """Record (or change) one device's answer; {yes, no} after it."""
    if answer not in ('yes', 'no'):
        raise VoteError(422, 'INVALID_VOTE', "vote must be 'yes' or 'no'")
    if not alert_id.startswith(PREFIX) or not alert_id[len(PREFIX):].isdigit() or \
            not VehicleHalt.objects.filter(pk=int(alert_id[len(PREFIX):])).exists():
        raise VoteError(404, 'ALERT_NOT_FOUND', 'Only detected alerts take votes.')
    ip_hash = _hash(f'ip:{ip}')
    limit, window = VOTE_LIMIT
    if AlertVote.objects.filter(ip=ip_hash, created__gte=timezone.now() - timedelta(seconds=window)).count() >= limit:
        raise VoteError(429, 'TOO_MANY_VOTES', 'Too many votes from here; try again later.')
    device = _hash(f'device:{device_id}') if isinstance(device_id, str) and 8 <= len(device_id) <= 100 else ip_hash
    try:
        with transaction.atomic():
            AlertVote.objects.update_or_create(alert_id=alert_id, device=device,
                                               defaults={'vote': answer == 'yes', 'ip': ip_hash, 'created': timezone.now()})
    except IntegrityError:  # the same device twice at once: one of them counts
        pass
    _cache['at'] = 0.0
    return tally([alert_id])[alert_id]
