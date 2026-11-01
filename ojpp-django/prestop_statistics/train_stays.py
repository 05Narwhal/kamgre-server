"""Staying on the train (spec 2026-10-31 H5–H8): train A's set goes on as train B under another number, or joins it.

SŽ's live data has train numbers, delays and the next station, but no unit or vehicle id, so unlike the buses
(stays.py) which set runs which train is never seen. It is inferred from delays, and only where the delays could have
said otherwise (docs/research/2026-10-31-train-stays.md):

- Candidates, per service day from the timetable: A's last station is B's first (the same station by name) and B
  leaves GAP_MIN to GAP_MAX after A's timetable arrival. OTP's SŽ trips carry no blockId and the timetable says
  nothing about "continues as", so nothing else proposes a pair.
- Evidence, from the nightly rollups (TrainDay): A's delay near its end and B's near its start (the first reported of
  NEAR stations: SŽ rarely reports a train at its first station). slack = gap − the station's least turn (MIN_TURN
  until TURN_SAMPLES turns were seen there); B is expected late by A's delay − slack. A day is informative when that
  is more than TOLERANCE (a smaller one could not be told from on time); it agrees when B was late by that, within
  TOLERANCE; it contradicts when B was clearly less late (or on time); B even later says neither (B late on its own
  account). Days on which A or B was canceled, replaced by buses, or planned in another class (zamudil.si) are skipped.
- Levels: `sure` needs at least `min_days` agreeing days and no contradiction, where `min_days` starts at SURE_DAYS and
  is raised until the backtest (each day predicted from the days before it) has no `sure` miss (SURE_PRECISION 1.0);
  `likely` needs LIKELY_DAYS agreeing days and no contradiction. A train with two candidates at a level, either way,
  gets none (a split or a join the notices do not explain). A `sure` that a day contradicted is at most `likely` for
  DEMOTE_DAYS.
- Gate: nothing is learned before SŽ's live data covered GATE_DAYS consecutive days (stays.gate_opens): the collector
  ran at least stays.FULL_DAY and at least COVERED of the day's timetable trains had a reported delay.

Joined trains come from zamudil.si's notices only (zamudil.joined_trains): SŽ says which train joins which, the
timetable says where. Which set to sit in is said only when the notice says it. The timetable lists a coupled stretch
once (RG 618 starts at Zidani Most; RG 631 carries it from Ljubljana), so equal times at shared stations are looked for
too (`timetable_coupled`) but found nothing on the stored days.

The collector runs `nightly` once a night after the rollups: it records yesterday (TrainLinkDay, TrainCoverDay, with the
level each pair had: the live check), then relearns TrainStay. The web process holds TrainStay (`table`) and carries a
late A's delay on to B through `sure` links only (trainlive.carried_delay, predictions.predict_leg).
"""
import json
import logging
import statistics
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Count, Max

from prestop_statistics import blocks, stays

logger = logging.getLogger(__name__)
GAP_MIN, GAP_MAX = 120, 5400  # s between A's timetable arrival and B's departure
MIN_TURN = 240         # s a set needs at least between arriving and leaving, until a station's own is learned
TURN_SAMPLES = 5       # agreeing days with B late at a station before its own least turn is used
TURN_RANGE = (120, 600)
TOLERANCE = 180        # s: SŽ reports whole minutes, and "on time" is under 3 min
NEAR = 3               # stations at A's end / B's start whose first report counts
SURE_DAYS, MAX_SURE_DAYS, LIKELY_DAYS = 4, 10, 2
SURE_PRECISION = 1.0
GATE_DAYS = stays.GATE_DAYS
COVERED = 0.95
DEMOTE_DAYS = 7
KEEP_DAYS = blocks.KEEP_DAYS
NIGHTLY_HOUR = stays.NIGHTLY_HOUR
AGREE, CONTRADICT, LATER, SILENT, NODATA, SKIPPED = 'agree', 'contradict', 'later', 'silent', 'nodata', 'skipped'
INFORMATIVE = (AGREE, CONTRADICT, LATER)
_nightly: dict = {'day': None}

TIMETABLE_Q = '''query($date: String!) { routes(transportModes: [RAIL]) { gtfsId shortName longName
  patterns { tripsForDate(serviceDate: $date) { gtfsId
    stoptimesForDate(serviceDate: $date) { scheduledArrival scheduledDeparture stop { gtfsId name } } } } } }'''


# ---------------------------------------------------------------- the timetable

def timetable(day: date) -> dict[str, dict]:
    """Train number -> its run on service day `day` from OTP: {'number', 'name', 'trip', 'stops' [{'id', 'name',
    'arr', 'dep'}] (s after the service day's midnight)}. A number on two routes (LP 4208) is one train: the first."""
    from prestop_api import sz
    from prestop_api.upstream import otp
    out: dict[str, dict] = {}
    for route in otp().query(TIMETABLE_Q, {'date': day.strftime('%Y%m%d')}, timeout=(5, 90))['routes']:
        name = route.get('shortName') or route.get('longName') or ''
        number = sz.train_parts(name)[1]
        if not number:
            continue
        for pattern in route.get('patterns') or []:
            for trip in pattern.get('tripsForDate') or []:
                times = trip.get('stoptimesForDate') or []
                if len(times) >= 2 and number not in out:
                    out[number] = {'number': number, 'name': name, 'trip': trip['gtfsId'],
                                   'stops': [{'id': s['stop']['gtfsId'], 'name': s['stop'].get('name') or '', 'arr': s['scheduledArrival'],
                                              'dep': s['scheduledDeparture']} for s in times]}
    return out


def _key(name: str) -> str:
    from prestop_api import sz
    return sz.station_key(name)


def candidates(runs: dict[str, dict]) -> list[dict]:
    """Every (A, B) with A ending where B starts, B leaving GAP_MIN–GAP_MAX after A's arrival: {'from', 'to', 'station'
    (B's first stop id), 'station_name', 'arrival', 'departure'}."""
    ending: dict[str, list[dict]] = defaultdict(list)
    for a in runs.values():
        ending[_key(a['stops'][-1]['name'])].append(a)
    out = []
    for b in runs.values():
        first = b['stops'][0]
        for a in ending.get(_key(first['name']), ()):
            gap = first['dep'] - a['stops'][-1]['arr']
            if a is not b and GAP_MIN <= gap <= GAP_MAX:
                out.append({'from': a['number'], 'to': b['number'], 'station': first['id'], 'station_name': first['name'],
                            'arrival': a['stops'][-1]['arr'], 'departure': first['dep']})
    return out


def timetable_coupled(runs: dict[str, dict]) -> list[dict]:
    """Two numbers with equal times (± 60 s) at 2 or more consecutive shared stations run coupled there: {'trains',
    'from', 'to' (station names), 'source': 'timetable'}. (None on the stored days: SŽ lists a coupled stretch once.)"""
    at: dict[str, list[tuple]] = defaultdict(list)
    for r in runs.values():
        for i, s in enumerate(r['stops']):
            at[_key(s['name'])].append((r['number'], i, s['dep'], s['name']))
    shared: dict[tuple, list] = defaultdict(list)
    for calls in at.values():
        for x in calls:
            for y in calls:
                if x[0] < y[0] and abs(x[2] - y[2]) <= 60:
                    shared[(x[0], y[0])].append((x[1], y[1], x[3]))
    out = []
    for pair, hits in shared.items():
        hits.sort()
        run = [hits[0]]
        best = run
        for h in hits[1:]:
            run = run + [h] if h[0] == run[-1][0] + 1 and h[1] == run[-1][1] + 1 else [h]
            best = run if len(run) > len(best) else best
        if len(best) >= 2:
            out.append({'trains': pair, 'from': best[0][2], 'to': best[-1][2], 'source': 'timetable'})
    return out


# ---------------------------------------------------------------- one day's evidence

def end_delay(stops: list[dict]) -> Optional[int]:
    """A's delay at its last reported station of the last NEAR."""
    return next((s['delay'] for s in reversed(stops[-NEAR:]) if s.get('delay') is not None), None)


def start_delay(stops: list[dict]) -> Optional[int]:
    """B's delay at its first reported station of the first NEAR."""
    return next((s['delay'] for s in stops[:NEAR] if s.get('delay') is not None), None)


def rollups(day: date) -> dict[str, dict]:
    """Number -> {'stops', 'canceled', 'replaced'} of the day's TrainDay rows."""
    from prestop_statistics.models import TrainDay
    have = {f.name for f in TrainDay._meta.get_fields()}  # a server before migration 0008 has no canceled/replaced
    fields = ['number', 'stops'] + [f for f in ('canceled', 'replaced') if f in have]
    return {r['number']: {'stops': r['stops'] or [], 'canceled': r.get('canceled'), 'replaced': r.get('replaced')}
            for r in TrainDay.objects.filter(service_date=day).values(*fields)}


def observe(day: date, runs: dict[str, dict], rows: dict[str, dict], classes: Optional[dict] = None) -> tuple[list[dict], dict]:
    """(TrainLinkDay fields of every candidate, TrainCoverDay fields) of one day. `classes`: number -> the planned
    class that day (zamudil.classes); a pair planned in two series is skipped."""
    classes = classes or {}
    links = []
    for c in candidates(runs):
        a, b = rows.get(c['from']) or {}, rows.get(c['to']) or {}
        ca, cb = (classes.get(c['from']) or {}).get('series'), (classes.get(c['to']) or {}).get('series')
        skipped = ('canceled' if a.get('canceled') or b.get('canceled') else
                   'replaced' if a.get('replaced') in ('part', 'whole') or b.get('replaced') in ('part', 'whole') else
                   'class' if ca and cb and ca != cb and 'unknown' not in (ca, cb) else '')
        links.append({**{k: c[k] for k in ('station', 'station_name', 'arrival', 'departure')}, 'day': day,
                      'from_number': c['from'], 'to_number': c['to'], 'skipped': skipped,
                      'from_delay': end_delay(a.get('stops') or []), 'to_delay': start_delay(b.get('stops') or [])})
    reported = sum(1 for n in runs if any(s.get('delay') is not None for s in (rows.get(n) or {}).get('stops') or []))
    return links, {'day': day, 'trains': len(runs), 'reported': reported}


def outcome(link: dict, turn: int = MIN_TURN) -> str:
    """What one day says about a pair (see the module's doc)."""
    if link.get('skipped'):
        return SKIPPED
    a, b = link.get('from_delay'), link.get('to_delay')
    if a is None or b is None:
        return NODATA
    expected = a - max(0, link['departure'] - link['arrival'] - turn)
    if expected <= TOLERANCE:
        return SILENT
    if abs(b - expected) <= TOLERANCE:
        return AGREE
    return CONTRADICT if b < expected - TOLERANCE else LATER


def record(day: date, runs: Optional[dict] = None, rows: Optional[dict] = None, classes: Optional[dict] = None) -> dict:
    """Store one day's evidence (TrainLinkDay, TrainCoverDay) with the level each pair had then, and return the live
    check: {level: [hits, misses]}; a `sure` miss is logged."""
    from prestop_statistics.models import RecorderDay, TrainCoverDay, TrainLinkDay, TrainStay
    runs = timetable(day) if runs is None else runs
    rows = rollups(day) if rows is None else rows
    links, cover = observe(day, runs, rows, classes)
    levels = {(s.from_number, s.to_number): s for s in TrainStay.objects.all()}
    turns = station_turns(list(TrainLinkDay.objects.filter(day__gte=day - timedelta(days=KEEP_DAYS), day__lt=day).values()))
    tally: dict[str, list] = defaultdict(lambda: [0, 0])
    for link in links:
        stay = levels.get((link['from_number'], link['to_number']))
        link['level'] = stay.level if stay else ''
        result = outcome(link, turns.get(link['station'], MIN_TURN))
        if link['level'] and result in INFORMATIVE:
            tally[link['level']][0 if result != CONTRADICT else 1] += 1
            if result == CONTRADICT and link['level'] == 'sure':
                logger.warning('train stays: "sure" missed on %s: %s -> %s at %s (A +%s s, B +%s s)', day, link['from_number'],
                               link['to_number'], link['station_name'], link['from_delay'], link['to_delay'])
    seconds = RecorderDay.objects.filter(day=day, feed='*').values_list('seconds', flat=True).first() or 0
    with transaction.atomic():
        TrainLinkDay.objects.filter(day=day).delete()
        TrainLinkDay.objects.bulk_create([TrainLinkDay(**link) for link in links], batch_size=2000)
        TrainCoverDay.objects.update_or_create(day=day, defaults={'trains': cover['trains'], 'reported': cover['reported'], 'collector_seconds': seconds})
    return {'pairs': len(links), 'trains': cover['trains'], 'reported': cover['reported'], 'check': dict(tally)}


# ---------------------------------------------------------------- learning

def complete(covers: list[dict]) -> set[date]:
    """The days SŽ's live data covered: the collector ran FULL_DAY and COVERED of the timetable trains were reported."""
    return {c['day'] for c in covers if c['trains'] and c['collector_seconds'] >= stays.FULL_DAY and c['reported'] >= COVERED * c['trains']}


def station_turns(links: list[dict]) -> dict[str, int]:
    """Station -> the least turn learned there: the median time between A's arrival and B's departure on agreeing
    days on which B left late (it left as soon as it could), once TURN_SAMPLES were seen; clamped to TURN_RANGE."""
    seen: dict[str, list[int]] = defaultdict(list)
    for link in links:
        if outcome(link) == AGREE and link['to_delay'] > TOLERANCE:
            seen[link['station']].append(link['departure'] + link['to_delay'] - link['arrival'] - link['from_delay'])
    return {s: max(TURN_RANGE[0], min(TURN_RANGE[1], round(statistics.median(v)))) for s, v in seen.items() if len(v) >= TURN_SAMPLES}


def histories(links: list[dict], turns: dict[str, int]) -> dict[tuple, list[tuple]]:
    """(from, to) -> [(day, outcome)] oldest first."""
    out: dict[tuple, list[tuple]] = defaultdict(list)
    for link in sorted(links, key=lambda x: x['day']):
        out[(link['from_number'], link['to_number'])].append((link['day'], outcome(link, turns.get(link['station'], MIN_TURN))))
    return out


def level(outcomes: list[str], min_days: Optional[int]) -> str:
    """'sure', 'likely' or '' from a pair's outcomes; `min_days` None: no `sure` at all."""
    c = Counter(outcomes)
    if c[CONTRADICT]:
        return ''
    if min_days is not None and c[AGREE] >= min_days:
        return 'sure'
    return 'likely' if c[AGREE] >= LIKELY_DAYS else ''


def points(groups: dict[tuple, list[tuple]]):
    """(pair, the day's outcome, the outcomes before that day) for every informative day."""
    for pair, hist in groups.items():
        for i, (day, result) in enumerate(hist):
            if result in INFORMATIVE:
                yield pair, result, [r for d, r in hist[:i] if d < day]


def tune(groups: dict[tuple, list[tuple]]) -> Optional[int]:
    """The smallest `min_days` whose `sure` never missed in the backtest, None when none reaches SURE_PRECISION."""
    cases = [(prior, result != CONTRADICT) for _, result, prior in points(groups)]
    for k in range(SURE_DAYS, MAX_SURE_DAYS + 1):
        hits = [hit for prior, hit in cases if level(prior, k) == 'sure']
        if (sum(hits) / len(hits) if hits else 1.0) >= SURE_PRECISION:
            return k
    return None


def backtest(groups: dict[tuple, list[tuple]], min_days: Optional[int]) -> dict:
    """{'sure' | 'likely': {'predicted', 'hits'}}: every informative day predicted from the days before it."""
    out = {name: {'predicted': 0, 'hits': 0} for name in ('sure', 'likely')}
    for _, result, prior in points(groups):
        lvl = level(prior, min_days)
        if lvl:
            out[lvl]['predicted'] += 1
            out[lvl]['hits'] += result != CONTRADICT
    return out


def unique(levels: dict[tuple, str]) -> dict[tuple, str]:
    """Pairs whose trains have no other pair at a level the same way: a train going on as two trains (or two as one)
    is a split or a join the evidence cannot tell apart, so none is kept."""
    out_of, into = Counter(a for (a, _), lvl in levels.items() if lvl), Counter(b for (_, b), lvl in levels.items() if lvl)
    return {(a, b): lvl for (a, b), lvl in levels.items() if lvl and out_of[a] == 1 and into[b] == 1}


def learn_rows(links: list[dict], covers: list[dict], today: date, joined: frozenset = frozenset()) -> tuple[list[dict], dict]:
    """(TrainStay fields, summary) learned on `today` from the stored days."""
    days = complete(covers)
    opens = stays.gate_opens(days)
    summary = {'complete days': len(days), 'gate': opens.isoformat() if opens else None}
    if not opens or opens > today:
        return [], summary
    used = [x for x in links if x['day'] in days]
    turns = station_turns(used)
    groups = histories(used, turns)
    min_days = tune(groups)
    demoted = {(x['from_number'], x['to_number']) for x in used if x.get('level') == 'sure' and x['day'] >= today - timedelta(days=DEMOTE_DAYS)
               and outcome(x, turns.get(x['station'], MIN_TURN)) == CONTRADICT}
    levels = {}
    for pair, hist in groups.items():
        lvl = level([r for _, r in hist], min_days)
        levels[pair] = 'likely' if lvl == 'sure' and pair in demoted else lvl
    kept = unique(levels)
    latest = {}
    for x in sorted(used, key=lambda x: x['day']):
        latest[(x['from_number'], x['to_number'])] = x
    rows = []
    for pair, lvl in kept.items():
        x, hist = latest[pair], groups[pair]
        turn = turns.get(x['station'], MIN_TURN)
        rows.append({'from_number': pair[0], 'to_number': pair[1], 'station': x['station'], 'station_name': x['station_name'],
                     'kind': 'coupled' if pair in joined else 'continues', 'level': lvl, 'arrival': x['arrival'], 'departure': x['departure'],
                     'slack': max(0, x['departure'] - x['arrival'] - turn), 'informative_days': sum(1 for _, r in hist if r in INFORMATIVE),
                     'agree_days': sum(1 for _, r in hist if r == AGREE),
                     'last_seen': max(d for d, r in hist if r in INFORMATIVE), 'learned_on': today})
    summary.update({'pairs': len(groups), 'informative': sum(1 for h in groups.values() if any(r in INFORMATIVE for _, r in h)),
                    'minDays': min_days, 'ambiguous': sum(1 for p, lvl in levels.items() if lvl and p not in kept),
                    **Counter(r['level'] for r in rows), 'backtest': backtest(groups, min_days)})
    return rows, summary


def learn(today: date) -> dict:
    """Relearn TrainStay from the stored days before `today`."""
    from prestop_statistics.models import TrainCoverDay, TrainLinkDay, TrainStay
    since = today - timedelta(days=KEEP_DAYS)
    links = list(TrainLinkDay.objects.filter(day__gte=since, day__lt=today).values())
    covers = list(TrainCoverDay.objects.filter(day__gte=since, day__lt=today).values())
    rows, summary = learn_rows(links, covers, today, joined_pairs(today))
    with transaction.atomic():
        TrainStay.objects.all().delete()
        TrainStay.objects.bulk_create([TrainStay(**r) for r in rows])
    return summary


BACKFILL = 7  # past days recorded per night


def backlog(today: date) -> list[date]:
    """Days of the window with rolled-up trains but no evidence recorded yet, newest first."""
    from prestop_statistics.models import TrainCoverDay, TrainDay
    since = today - timedelta(days=KEEP_DAYS)
    rolled = set(TrainDay.objects.filter(service_date__gte=since, service_date__lt=today - timedelta(days=1)).values_list('service_date', flat=True).distinct())
    done = set(TrainCoverDay.objects.filter(day__gte=since).values_list('day', flat=True))
    return sorted(rolled - done, reverse=True)


def nightly(now: Optional[float] = None) -> Optional[dict]:
    """Once a day, after NIGHTLY_HOUR (the rollups ran at 02:05): record yesterday, then relearn. Called on every
    collector poll; the old days are forgotten after KEEP_DAYS."""
    from prestop_statistics.models import TrainCoverDay, TrainLinkDay, TrainStay
    local = datetime.fromtimestamp(now or time.time(), blocks._tz())
    if local.hour + local.minute / 60 < NIGHTLY_HOUR or _nightly['day'] == local.date():
        return None
    today = _nightly['day'] = local.date()
    if TrainStay.objects.filter(learned_on=today).exists() or TrainCoverDay.objects.filter(day=today - timedelta(days=1)).exists():
        return None  # the collector restarted after tonight's run
    yesterday = today - timedelta(days=1)
    from prestop_api import zamudil
    recorded = record(yesterday, classes=zamudil.classes(yesterday))
    # Days rolled up before this ran (the first night after a deploy): from the timetable of that date, without the
    # planned classes (zamudil keeps no copy of past dates). A few a night, so the gate counts the stored days.
    for day in backlog(today)[:BACKFILL]:
        recorded[day.isoformat()] = record(day)
    TrainLinkDay.objects.filter(day__lt=today - timedelta(days=KEEP_DAYS)).delete()
    TrainCoverDay.objects.filter(day__lt=today - timedelta(days=KEEP_DAYS)).delete()
    return {'recorded': recorded, **learn(today)}


# ---------------------------------------------------------------- joined trains from the notices (H7)

def notice_links(day: date, runs: dict[str, dict], joined: Optional[list[dict]] = None) -> list[dict]:
    """zamudil's joined trains on `day` placed on the timetable: {'from', 'to', 'station', 'station_name', 'kind' ('join':
    A ends at S and its set goes on with B; 'split': B's set rides with A to S, where B starts), 'stretch' (first and
    last station names they run coupled), 'part' ({number: position}, only what the notice says), 'source': 'notice'}.
    A pair the timetable cannot place is left out."""
    from prestop_api import zamudil
    joined = zamudil.joined_trains(day) if joined is None else joined
    out = []
    for item in joined:
        x, y = (runs.get(n) for n in item['trains'])
        if not x or not y:
            continue
        for a, b in ((x, y), (y, x)):
            keys_b = [_key(s['name']) for s in b['stops']]
            keys_a = [_key(s['name']) for s in a['stops']]
            end = _key(a['stops'][-1]['name'])
            if end in keys_b[:-1]:  # a joins b at its last station; b goes on
                i = keys_b.index(end)
                link = {'from': a['number'], 'to': b['number'], 'station': b['stops'][i]['id'], 'station_name': b['stops'][i]['name'],
                        'kind': 'join', 'stretch': (b['stops'][i]['name'], b['stops'][-1]['name'])}
                break
            start = _key(b['stops'][0]['name'])
            if start in keys_a[1:]:  # b starts where a, carrying b's set, passes: they split there
                i = keys_a.index(start, 1)
                link = {'from': a['number'], 'to': b['number'], 'station': b['stops'][0]['id'], 'station_name': b['stops'][0]['name'],
                        'kind': 'split', 'stretch': (a['stops'][0]['name'], a['stops'][i]['name'])}
                break
        else:
            continue
        part = {}
        for place, position in item['sets'].items():
            for run in (x, y):
                if any(_key(s['name']) == _key(place) or (_key(s['name']) and _key(place).startswith(_key(s['name'])) and len(_key(place)) - len(_key(s['name'])) <= 2)
                       for s in run['stops'][1:]) and run['number'] not in part:
                    part[run['number']] = position
                    break
        out.append({**link, 'part': part if len(part) == 2 else {}, 'source': 'notice', 'notice': item['notice']})
    return out


def joined_pairs(day: date) -> frozenset:
    """(from, to) of today's notice joins, to mark learned pairs `coupled`."""
    try:
        return frozenset((x['from'], x['to']) for x in notice_links(day, _runs(day)) if x['kind'] == 'join')
    except Exception as e:  # noqa: BLE001 - only the kind's label
        logger.info('Joined trains of %s unavailable: %r', day, e)
        return frozenset()


# ---------------------------------------------------------------- reading (the web process)

CHECK = 600  # s between looks at whether a new table was learned
_lock = threading.Lock()
_table: dict = {'on': None, 'checked': 0.0, 'from': {}, 'to': {}}
FIELDS = ('from_number', 'to_number', 'station', 'station_name', 'kind', 'level', 'arrival', 'departure', 'slack', 'informative_days', 'agree_days')


def version() -> tuple:
    from prestop_statistics.models import TrainStay
    got = TrainStay.objects.aggregate(day=Max('learned_on'), rows=Count('id'))
    return got['day'], got['rows']


def table() -> dict:
    """{'from': number -> its stay, 'to': number -> its stay}, held per process and reloaded when a new table was
    learned (looked at most every CHECK s). Empty until the gate opens. A failed read keeps the old table."""
    from prestop_statistics.models import TrainStay
    if _table['on'] is not None and time.monotonic() - _table['checked'] < CHECK:
        return _table
    with _lock:
        if _table['on'] is not None and time.monotonic() - _table['checked'] < CHECK:
            return _table
        try:
            v = version()
            if v != _table['on']:
                rows = list(TrainStay.objects.values(*FIELDS))
                _table.update({'from': {r['from_number']: r for r in rows}, 'to': {r['to_number']: r for r in rows}})
            _table['on'], _table['checked'] = v, time.monotonic()
        except Exception as e:  # noqa: BLE001 - a stay is optional
            logger.warning('Train stays unavailable: %r', e)
            _table['checked'] = time.monotonic() - CHECK + 60
    return _table


def continues_as(number: Optional[str]) -> Optional[dict]:
    return table()['from'].get(number) if number else None


def comes_from(number: Optional[str]) -> Optional[dict]:
    return table()['to'].get(number) if number else None


_days: dict[str, tuple] = {}  # date -> (monotonic time, runs by number)
RUNS_TTL = 3600
RETRY = 300  # s after a failed timetable read


def _from_map(day: date) -> dict[str, dict]:
    """The same as `timetable(day)` from the timetable the map already holds (the web process), {} when it has none."""
    from prestop_api import mapping, scheduled, sz
    cache = scheduled.timetable if day == scheduled.service_day() else scheduled._day_tables.get(day.isoformat())
    snap = cache.peek() if cache else None
    out: dict[str, dict] = {}
    for t in (snap.value if snap else []):
        if t['route'].get('mode') != 'RAIL' or scheduled._service_date(t) != day:
            continue
        name = mapping.route_name(t['route']) or ''
        number = sz.train_parts(name)[1]
        if number and number not in out:
            arr, dep = t.get('scheduledArrivals') or t['arrivals'], t.get('scheduledDepartures') or t['departures']
            out[number] = {'number': number, 'name': name, 'trip': t['id'],
                           'stops': [{'id': s['gtfsId'], 'name': s.get('name') or '', 'arr': a - t['serviceDay'], 'dep': d - t['serviceDay']}
                                     for s, a, d in zip(t['stops'], arr, dep)]}
    return out


def _runs(day: date) -> dict[str, dict]:
    """Train number -> run on `day` (timetable), from the map's timetable for today and the days it holds, else OTP."""
    key = day.isoformat()
    hit = _days.get(key)
    if hit and time.monotonic() - hit[0] < RUNS_TTL:
        return hit[1]
    try:
        runs = _from_map(day) or timetable(day)
    except Exception as e:  # noqa: BLE001 - asked again in RETRY s, not on every map refresh
        logger.info('Timetable of %s for train stays unavailable: %r', day, e)
        runs = hit[1] if hit else {}
        _days[key] = (time.monotonic() - RUNS_TTL + RETRY, runs)
        return runs
    if len(_days) > 4:
        _days.clear()
    _days[key] = (time.monotonic(), runs)
    return runs


_coupled_memo: dict = {'runs': None, 'value': []}


def _coupled_by_timetable(runs: dict) -> list[dict]:
    if _coupled_memo['runs'] is not runs:
        _coupled_memo.update(runs=runs, value=timetable_coupled(runs))
    return _coupled_memo['value']


def replaced(day: date, trip_ids) -> bool:
    """Whether buses run any part of these train trips on `day`, by the plan boards and journeys use (not waited for:
    unknown counts as not replaced, as the timetable says)."""
    from prestop_api import scheduled, trainlive
    plan = scheduled.day_plan(day)
    return bool(plan) and any(trainlive.replaced(plan, run) for t in trip_ids for run in (plan.get('trips') or {}).get(t) or ())


def holds(stay: dict, day: date, runs: Optional[dict] = None) -> bool:
    """Whether a learned stay still fits `day`: both trains run with the times it was learned from (± 60 s), from
    the same station, and zamudil does not plan them in two series."""
    from prestop_api import zamudil
    runs = _runs(day) if runs is None else runs
    a, b = runs.get(stay['from_number']), runs.get(stay['to_number'])
    if not a or not b or b['stops'][0]['id'] != stay['station'] and _key(b['stops'][0]['name']) != _key(stay['station_name']):
        return False
    if abs(a['stops'][-1]['arr'] - stay['arrival']) > 60 or abs(b['stops'][0]['dep'] - stay['departure']) > 60:
        return False
    if replaced(day, (a['trip'], b['trip'])):
        return False  # a bus runs part of either: the set does not go on as the other train (evidence skips such days too)
    ca, cb = ((zamudil.class_of(n, day) or {}).get('series') for n in (stay['from_number'], stay['to_number']))
    return not (ca and cb and ca != cb and 'unknown' not in (ca, cb))


def links_of(number: str, day: date) -> dict:
    """What the train page shows (H9): {'comesFrom', 'continuesAs', 'coupledWith'} as far as known on `day`."""
    out: dict = {}
    try:
        runs = _runs(day)
    except Exception as e:  # noqa: BLE001 - optional
        logger.info('Timetable of %s for train stays unavailable: %r', day, e)
        return out
    names = {n: r['name'] for n, r in runs.items()}
    joins = notice_links(day, runs)
    stay = continues_as(number)
    if stay and holds(stay, day, runs):
        b = runs[stay['to_number']]
        out['continuesAs'] = {'number': stay['to_number'], 'name': names.get(stay['to_number']) or stay['to_number'], 'station': stay['station_name'],
                              'departure': stay['departure'], 'destination': b['stops'][-1]['name'], 'level': stay['level'], 'kind': stay['kind']}
    else:
        join = next((j for j in joins if j['from'] == number and j['kind'] == 'join'), None)
        if join:
            b = runs[join['to']]
            dep = next(s['dep'] for s in b['stops'] if s['id'] == join['station'])
            out['continuesAs'] = {'number': join['to'], 'name': names.get(join['to']) or join['to'], 'station': join['station_name'],
                                  'departure': dep, 'destination': b['stops'][-1]['name'], 'level': 'sure', 'kind': 'coupled'}
    stay = comes_from(number)
    if stay and holds(stay, day, runs):
        out['comesFrom'] = {'number': stay['from_number'], 'name': names.get(stay['from_number']) or stay['from_number'], 'station': stay['station_name'],
                            'arrival': stay['arrival'], 'level': stay['level'], 'kind': stay['kind']}
    coupled = []
    for j in joins:
        if number not in (j['from'], j['to']):
            continue
        other = j['to'] if j['from'] == number else j['from']
        entry = {'number': other, 'name': names.get(other) or other, 'from': j['stretch'][0], 'to': j['stretch'][1], 'source': 'notice'}
        if j['part'].get(number) is not None:
            entry['part'] = j['part'][number]
        coupled.append(entry)
    for c in _coupled_by_timetable(runs):
        if number in c['trains']:
            other = next(n for n in c['trains'] if n != number)
            if all(e['number'] != other for e in coupled):
                coupled.append({'number': other, 'name': names.get(other) or other, 'from': c['from'], 'to': c['to'], 'source': 'timetable'})
    if coupled:
        out['coupledWith'] = coupled
    return out


def journey_level(previous_number: Optional[str], number: Optional[str], station_id: Optional[str], day: date) -> Optional[str]:
    """'sure' or 'likely' when the train of one journey leg goes on as the next one's at that station: a learned stay
    that still fits the day, or a join SŽ's notice announces (sure); else None (a normal change). A split is a change:
    which set to sit in is up to the rider and the sign."""
    if not previous_number or not number:
        return None
    try:
        runs = _runs(day)
    except Exception as e:  # noqa: BLE001 - optional
        logger.info('Timetable of %s for train stays unavailable: %r', day, e)
        return None
    stay = continues_as(previous_number)
    if stay and stay['to_number'] == number and holds(stay, day, runs):
        return stay['level']
    if any(j['from'] == previous_number and j['to'] == number and j['kind'] == 'join' for j in notice_links(day, runs)):
        return 'sure'
    return None


def sure_link_to(number: Optional[str], day: date) -> Optional[dict]:
    """The `sure` learned stay train `number` continues, if it still fits `day` (delays carry only through these)."""
    stay = comes_from(number)
    try:
        return stay if stay and stay['level'] == 'sure' and holds(stay, day) else None
    except Exception as e:  # noqa: BLE001 - optional
        logger.info('Train stay of %s unavailable: %r', number, e)
        return None


def report(day: Optional[date] = None) -> dict:
    """The learned table (and a day's evidence when asked): `manage.py train_stays`."""
    from prestop_statistics.models import TrainCoverDay, TrainLinkDay, TrainStay
    out = {'stays': [{k: getattr(s, k) for k in FIELDS} for s in TrainStay.objects.order_by('station_name', 'arrival')],
           'cover': [{'day': c.day.isoformat(), 'trains': c.trains, 'reported': c.reported, 'collector': c.collector_seconds}
                     for c in TrainCoverDay.objects.order_by('day')]}
    if day:
        links = list(TrainLinkDay.objects.filter(day=day).values())
        out['day'] = Counter(outcome(x) for x in links)
    return json.loads(json.dumps(out, default=str))


# ---------------------------------------------------------------- "why isn't it showing?" (spec 2026-11-01 I14)

STATUS_DAYS = 10    # days listed
NEVER_DAYS = 3      # the latest days looked at for trains SŽ never reported
TOP_PAIRS = 8
SHORT_TRAIN = 3     # stops: "short" in the list of trains never reported


def _misses(cover: dict) -> list[str]:
    """What keeps a day from counting (`complete`): 'collector', 'reported'."""
    return [name for name, ok in (('collector', cover['collector_seconds'] >= stays.FULL_DAY),
                                  ('reported', cover['trains'] and cover['reported'] >= COVERED * cover['trains'])) if not ok]


def _estimated(day: date, runs_of) -> Optional[dict]:
    """A day rolled up but not recorded yet (the nightly job backfills it): its cover worked out as `record` would."""
    from prestop_statistics.models import RecorderDay
    try:
        runs = runs_of(day)
    except Exception as e:  # noqa: BLE001 - OTP may no longer have the day: the list goes on without it
        logger.info('Timetable of %s for the status unavailable: %r', day, e)
        return None
    cover = observe(day, runs, rollups(day))[1]
    seconds = RecorderDay.objects.filter(day=day, feed='*').values_list('seconds', flat=True).first() or 0
    return {**cover, 'collector_seconds': seconds}


def never_reported(days: list[date], runs_of) -> dict:
    """The timetable's trains with no reported delay on any of `days`: {'trains' (in the timetable), 'categories'
    {category: [reported, in the timetable]}, 'never' [{'number', 'name', 'from', 'to', 'stops', 'abroad'}]}."""
    from prestop_api import abroad, sz
    runs: dict[str, dict] = {}
    seen: set[str] = set()
    for day in days:
        try:
            runs = {**runs_of(day), **runs}
        except Exception as e:  # noqa: BLE001 - see _estimated
            logger.info('Timetable of %s for the status unavailable: %r', day, e)
        seen |= {n for n, row in rollups(day).items() if any(s.get('delay') is not None for s in row['stops'])}
    categories: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    never = []
    for number, r in runs.items():
        cell = categories[sz.train_parts(r['name'])[0] or '?']
        cell[1] += 1
        if number in seen:
            cell[0] += 1
            continue
        first, last = r['stops'][0]['name'], r['stops'][-1]['name']
        never.append({'number': number, 'name': r['name'], 'from': first, 'to': last, 'stops': len(r['stops']),
                      'abroad': any(abroad.train_ends(r['name'], first, last)) or any(abroad.is_abroad_stop(s['name']) or (abroad.place(s['name']) in abroad.PLACES.values() and 'gorica' not in s['name'].lower())  # not Nova Gorica
                                                                                                for s in r['stops'])})
    return {'trains': len(runs), 'categories': {k: categories[k] for k in sorted(categories)}, 'never': sorted(never, key=lambda x: x['name'])}


def status(today: Optional[date] = None, runs_of=None) -> dict:
    """What `manage.py train_stays --status` says: the last days against the gate, the streak, when the gate can open,
    what was learned, and which trains SŽ never reports when that is what holds it shut. It only reads."""
    from prestop_api import trips
    from prestop_statistics.models import TrainCoverDay, TrainDay, TrainLinkDay, TrainStay
    today = today or trips.service_day()
    runs_of = runs_of or _runs
    since = today - timedelta(days=KEEP_DAYS)
    covers = list(TrainCoverDay.objects.filter(day__gte=since, day__lt=today).values('day', 'trains', 'reported', 'collector_seconds'))
    recorded = {c['day'] for c in covers}
    # The first look after a deploy: stored days not recorded yet, which the coming nights backfill and then count.
    recent = {today - timedelta(days=k) for k in range(1, STATUS_DAYS + 1)}
    rolled = set(TrainDay.objects.filter(service_date__in=recent).values_list('service_date', flat=True).distinct())
    estimated = [e for e in (_estimated(d, runs_of) for d in sorted(rolled - recorded)) if e]
    rows = {c['day']: c for c in covers + estimated}
    counted = complete(list(rows.values()))

    opens = stays.gate_opens(complete(covers))
    is_open = bool(opens and opens <= today)
    latest = max((d for d in rows if d >= today - timedelta(days=2)), default=None)  # before tonight's run, yesterday has no row yet
    streak = 0
    if latest:
        while latest - timedelta(days=streak) in counted:
            streak += 1
    # Every day from the first free one must count; the gate opens the day after the last of them (stays.gate_opens).
    first_free = latest + timedelta(days=1) if latest else today
    earliest = opens if is_open else max(today, first_free + timedelta(days=max(0, GATE_DAYS - streak)))

    days = [{'day': d, 'trains': rows[d]['trains'], 'reported': rows[d]['reported'], 'collector': rows[d]['collector_seconds'] / 86400,
             'counts': d in counted, 'recorded': d in recorded, 'misses': _misses(rows[d])} for d in sorted(recent & set(rows))]
    learned = list(TrainStay.objects.values('from_number', 'to_number', 'level'))
    levels = Counter(s['level'] for s in learned)

    links = list(TrainLinkDay.objects.filter(day__gte=since, day__lt=today).values())
    groups = histories(links, station_turns([x for x in links if x['day'] in counted]))
    level_of = {(s['from_number'], s['to_number']): s['level'] for s in learned}
    names = {(x['from_number'], x['to_number']): x['station_name'] for x in links}
    tally = {pair: Counter(r for _, r in hist) for pair, hist in groups.items()}
    ranked = sorted((p for p, c in tally.items() if c[AGREE]), key=lambda p: (p not in level_of, -tally[p][AGREE], tally[p][CONTRADICT], p))
    top = [{'from': p[0], 'to': p[1], 'station': names[p], 'level': level_of.get(p, ''), 'agree': tally[p][AGREE], 'contradict': tally[p][CONTRADICT],
            'later': tally[p][LATER]} for p in ranked[:TOP_PAIRS]]

    out = {'today': today, 'days': days, 'streak': streak, 'needs': GATE_DAYS, 'open': is_open, 'opens': earliest, 'sure': levels['sure'],
           'likely': levels['likely'], 'top': top, 'pairs': len(groups)}
    if any('reported' in d['misses'] for d in days):
        out['looked'] = [d['day'] for d in days if d['trains']][-NEVER_DAYS:]
        out['unreported'] = never_reported(out['looked'], runs_of)
    out['sentence'] = status_sentence(out)
    return out


def status_sentence(s: dict) -> str:
    """The state in one plain sentence. It says what is, and proposes no threshold."""
    if s['open']:
        if s['sure'] or s['likely']:
            return f'The gate is open since {s["opens"]}, and riders can see {s["sure"]} sure and {s["likely"]} likely train stays.'
        return f'The gate is open since {s["opens"]}, but no pair has enough agreeing days yet, so riders see no train stay.'
    if not s['days']:
        return f'The gate is closed: no day has been recorded yet, and {s["opens"]} is the earliest it can open.'
    if not any(d['counts'] for d in s['days']):
        blames = {name: all(name in d['misses'] for d in s['days']) for name in ('collector', 'reported')}
        why = ('the collector did not run enough of them and SŽ reported too few trains on every one' if blames['reported'] and blames['collector'] else
               'SŽ reported too few trains on every one of them' if blames['reported'] else
               'the collector did not run enough of every one of them' if blames['collector'] else
               'the collector or SŽ\'s reports fell short on each of them')
        return f'The gate is closed and stays closed while this holds: none of the last {len(s["days"])} days counted, because {why}.'
    last = s['days'][-1]
    if not last['counts']:
        share = last['reported'] / last['trains'] if last['trains'] else 0
        why = {'collector': f'the collector ran only {last["collector"]:.0%} of it', 'reported': f'SŽ reported only {share:.0%} of its trains'}
        return (f'The gate is closed: {last["day"]} did not count because {" and ".join(why[m] for m in last["misses"])}, '
                f'so the streak is 0 of {s["needs"]}, and {s["opens"]} is the earliest it can open.')
    if not s['streak']:
        return f'The gate is closed: nothing has been recorded since {last["day"]}, and {s["opens"]} is the earliest it can open.'
    return f'The gate is closed but on its way: {s["streak"]} of {s["needs"]} days in a row, and it can open on {s["opens"]} if every day until then counts.'
