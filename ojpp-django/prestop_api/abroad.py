"""Places abroad: never a stop, line, vehicle or shape, only the text of where a trip really starts or ends.

KamGre shows Slovenia only. A trip that runs abroad ends (or starts) at its last stop in Slovenia and shows
the place abroad as its destination (or origin) text: the RG train to Villach is "→ Beljak / Villach" at
Jesenice, BUS 415 reads "from Beljak / Villach". Where the real end comes from, most trustworthy first:
- the trip's own stops abroad (the IJPP feed marks them with their country: "Gorizia Corso Italia 85/89 (I)");
- for SŽ's replacement buses, the station abroad in SŽ's timetable column (sztimetables.Stations.resolve);
- for trains, the feed's other legs of the same train number: the national feed splits an international train at
  the border stations ("EC 115" is three trips, München - Jesenice, Jesenice - Dobova, Dobova - Zagreb), joined
  here by their shared station and times (whole_run, learn); the timetable cache is the sync, no call of its own;
- for trains the feed doesn't take that far, `data/international_trains.csv`, the fallback.
"""
import csv
import logging
import os
import re
from functools import lru_cache
from typing import Callable, Optional, Sequence, TypeVar

from .mapping import fold, iso, route_name as _route_name
from .sz import train_parts

T = TypeVar('T')
TRAINS_CSV = os.path.join(os.path.dirname(__file__), 'data', 'international_trains.csv')
# The IJPP feed's stops abroad end in their country: "Tarvisio autostazione (I)", "Bleiburg Bahnhof (A)".
_MARK = re.compile(r'\((I|A|HR|H|D|CH|SRB|BIH)\)\s*$')
_MARK_COUNTRY = {'I': 'IT', 'A': 'AT', 'HR': 'HR', 'H': 'HU', 'D': 'DE', 'CH': 'CH', 'SRB': 'RS', 'BIH': 'BA'}
_UIC_COUNTRY = {'55': 'HU', '78': 'HR', '80': 'DE', '81': 'AT', '83': 'IT', '85': 'CH'}  # see _INTL
# A place abroad as riders read it: Slovenian name / local name, the way SŽ and the stations sign it.
PLACES = {
    'beljak': 'Beljak / Villach', 'villach': 'Beljak / Villach',
    'opcine': 'Opčine', 'villa opicina': 'Opčine',
    'trst': 'Trst / Trieste', 'trieste': 'Trst / Trieste',
    'gorizia': 'Gorica / Gorizia', 'gorica': 'Gorica / Gorizia',
    'tarvisio': 'Trbiž / Tarvisio', 'trbiz': 'Trbiž / Tarvisio',
    'cividale': 'Čedad / Cividale', 'cedad': 'Čedad / Cividale',
    'lavamund': 'Labot / Lavamünd', 'labot': 'Labot / Lavamünd',
    'bleiburg': 'Pliberk / Bleiburg', 'pliberk': 'Pliberk / Bleiburg',
    'spielfeld': 'Špilje / Spielfeld', 'spilje': 'Špilje / Spielfeld',
    'graz': 'Gradec / Graz', 'gradec': 'Gradec / Graz',
    'wien': 'Dunaj / Wien', 'dunaj': 'Dunaj / Wien',
    'munchen': 'München', 'monakovo': 'München', 'salzburg': 'Salzburg', 'zurich': 'Zürich',
    'zagreb': 'Zagreb', 'rijeka': 'Reka / Rijeka', 'reka': 'Reka / Rijeka', 'pula': 'Pulj / Pula', 'pulj': 'Pulj / Pula',
    'split': 'Split', 'buzet': 'Buzet', 'cakovec': 'Čakovec', 'durmanec': 'Durmanec',
    'budapest': 'Budimpešta / Budapest', 'budimpesta': 'Budimpešta / Budapest',
}


def _words(name: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', fold(_MARK.sub('', name or '')))


# The feed's international stations (since late Oct 2026): "IJPP:INTL-5500028" (Szombathely), their UIC country code
# first: 55 Hungary, 78 Croatia, 81 Austria, 83 Italy. 79 is Slovenia's own (Lendava); "Hodos Drzavna meja" (79) is
# only the border point, no station anyone gets on at.
_INTL = re.compile(r':INTL-(\d{2})')
HOME_UIC = '79'
_BORDER = re.compile(r'dr[zž]avna meja', re.IGNORECASE)
# 'Stuttgart Hauptbahnhof' is the town of Stuttgart as a train's end.
_MAIN_STATION = re.compile(r'\s+(?:hauptbahnhof|hbf|glavni kolodvor)$', re.IGNORECASE)
MAX_GAP = 3600  # s: the longest stand at a border station between two legs of one train; longer, they aren't joined


def is_abroad_stop(name: Optional[str], stop_id: Optional[str] = None) -> bool:
    """A feed stop abroad: by the country the feed puts after its name, or an international station of another
    country (or the border point) by its id."""
    if _MARK.search(name or ''):
        return True
    found = _INTL.search(stop_id or '')
    return bool(found) and (found.group(1) != HOME_UIC or bool(_BORDER.search(name or '')))


def country_of(name: Optional[str], stop_id: Optional[str] = None) -> Optional[str]:
    """The country code (ISO) of a stop abroad, from the feed's own mark or id; None when they don't say."""
    mark, found = _MARK.search(name or ''), _INTL.search(stop_id or '')
    return _MARK_COUNTRY[mark.group(1)] if mark else _UIC_COUNTRY.get(found.group(1)) if found else None


def place(name: Optional[str]) -> str:
    """The place a stop or station abroad lies in, as riders read it ('Gorizia Corso Italia 85/89 (I)' ->
    'Gorica / Gorizia', 'BELJAK' -> 'Beljak / Villach'); an unknown one keeps its own name."""
    words = _words(name or '')
    for n in (2, 1):
        for i in range(len(words) - n + 1):
            found = PLACES.get(' '.join(words[i:i + n]))
            if found:
                return found
    return _MAIN_STATION.sub('', _MARK.sub('', name or '').strip()).strip()


def trim(items: Sequence[T], name_of: Callable[[T], Optional[str]],
         id_of: Optional[Callable[[T], Optional[str]]] = None) -> tuple[int, int, Optional[str], Optional[str]]:
    """The stretch of `items` (a trip's stops, in order) in Slovenia, as (start, end) slice bounds, with the place
    abroad the trip comes from and goes to (None where it starts or ends in Slovenia). No stop in Slovenia: (0, 0)."""
    inside = [i for i, s in enumerate(items) if not is_abroad_stop(name_of(s), id_of(s) if id_of else None)]
    if not inside:
        return 0, 0, None, None
    a, b = inside[0], inside[-1] + 1
    return a, b, place(name_of(items[0])) if a > 0 else None, place(name_of(items[-1])) if b < len(items) else None


@lru_cache(maxsize=1)
def _trains() -> dict[str, tuple[str, str]]:
    out = {}
    try:
        with open(TRAINS_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(r for r in f if not r.startswith('#')):
                out[re.sub(r'\s+', ' ', row['train'].strip().upper())] = (row['from'].strip(), row['to'].strip())
    except OSError:
        pass
    return out


def train_ends(route_name: Optional[str], first: Optional[str] = None, last: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """An international train's places abroad: (where it comes from, where it goes), each None in Slovenia.
    'EC 115' -> ('München', 'Zagreb'). `first`/`last`: the trip's own end stations in the feed; a start or end
    the table puts in Slovenia, or at a station the feed has, is no place abroad."""
    feed = _feed_ends.get(_number(route_name), (None, None))
    found = _trains().get(re.sub(r'\s+', ' ', (route_name or '').strip().upper()))
    if not found:
        return feed
    ends = []
    for real, own in zip(found, (first, last)):
        label = place(real) if real else ''
        ends.append(label if label and label in PLACES.values() and fold(real) not in fold(own or '') else None)
    return feed[0] or ends[0], feed[1] or ends[1]


# ---------------------------------------------------------------- the whole run, from the feed's legs

_feed_ends: dict[str, tuple[Optional[str], Optional[str]]] = {}  # train number -> its places abroad (learn)


def _number(route_name: Optional[str]) -> Optional[str]:
    """A train's number, whatever the category each leg's operator gives it ('RG 678' and 'IR 678' are one train)."""
    category, number = train_parts(route_name or '')
    return None if category == 'BUS' else number


def _inside(run: dict) -> int:
    return sum(not is_abroad_stop(s.get('name'), s.get('gtfsId')) for s in run['stops'])


def only_touches_slovenia(run: dict) -> bool:
    """A leg abroad with one station here, the border station it leaves from or arrives at."""
    return _inside(run) == 1


def main_run(runs: Sequence[dict]) -> Optional[dict]:
    """The leg with most stations in Slovenia, the one a train's page shows; on a tie the first found, SŽ's own
    (their ids have no INTL). None: no leg in Slovenia."""
    best = max(runs, key=lambda t: (_inside(t), 'INTL' not in t['id']), default=None)
    return best if best and _inside(best) else None


def legs_of(route_name: Optional[str], trips: Sequence[dict]) -> list[dict]:
    """The timetable's trips (scheduled._trips_for) of this train's number."""
    number = _number(route_name)
    return [t for t in trips if number and t['route'].get('mode') == 'RAIL' and _number(_route_name(t['route'])) == number]


def _joined(run: dict, legs: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """The legs before and after `run`, in running order: each starts at the station the last one ended at, within
    MAX_GAP. A train that divides takes the part leaving soonest."""
    seen, before, after = {run['id']}, [], []
    now = run
    while True:
        end, at = now['stops'][-1]['gtfsId'], now['scheduledArrivals'][-1]
        found = [t for t in legs if t['id'] not in seen and t['stops'][0]['gtfsId'] == end and 0 <= t['scheduledDepartures'][0] - at <= MAX_GAP]
        if not found:
            break
        now = min(found, key=lambda t: t['scheduledDepartures'][0])
        seen.add(now['id'])
        after.append(now)
    now = run
    while True:
        start, at = now['stops'][0]['gtfsId'], now['scheduledDepartures'][0]
        found = [t for t in legs if t['id'] not in seen and t['stops'][-1]['gtfsId'] == start and 0 <= at - t['scheduledArrivals'][-1] <= MAX_GAP]
        if not found:
            break
        now = max(found, key=lambda t: t['scheduledArrivals'][-1])
        seen.add(now['id'])
        before.insert(0, now)
    return before, after


def _row(trip: dict, i: int, kept: Optional[dict] = None) -> dict:
    """A stop outside the trip's stretch in Slovenia, as text: no coordinates, so nothing can draw it, and an id only
    for a station in Slovenia. Times by the timetable; a delay only where the feed itself reports one, never guessed.
    A live 0 counts as none: the feed marks stops abroad live at 0 in bulk, and that must not read as on time.
    `kept` (kept_delays): what the feed reported for this stop earlier, still there once it stops reporting the leg."""
    stop, delay = trip['stops'][i], trip['delays'][i]
    country = country_of(stop.get('name'), stop.get('gtfsId'))
    observed = ((kept or {}).get(trip.get('id')) or {}).get(stop.get('gtfsId'))
    return {
        'name': stop.get('name') or '',
        **({'abroad': True, **({'country': country} if country else {})} if is_abroad_stop(stop.get('name'), stop.get('gtfsId')) else {'stopId': stop.get('gtfsId')}),
        'scheduledArrival': iso(trip['scheduledArrivals'][i]), 'scheduledDeparture': iso(trip['scheduledDepartures'][i]),
        **({'effectiveArrival': iso(trip['arrivals'][i]), 'effectiveDeparture': iso(trip['departures'][i]), 'delaySeconds': delay} if delay else {}),
        **({'observedDelaySeconds': observed} if observed else {}),
    }


def _end(stop: dict) -> Optional[str]:
    return place(stop.get('name')) if is_abroad_stop(stop.get('name'), stop.get('gtfsId')) else None


def whole_run(run: dict, legs: Sequence[dict], kept: Optional[dict] = None) -> dict:
    """`run`, a timetable trip, with its other `legs` (legs_of): {'before', 'after'}, the stops either side of its
    stretch in Slovenia, and {'comes', 'goes'}, the places abroad it really starts and ends at (None in Slovenia).
    `kept`: the delays kept for the legs' stops (kept_delays)."""
    before, after = _joined(run, legs)
    a, b, _, _ = trim(run['stops'], lambda s: s.get('name'), lambda s: s.get('gtfsId'))
    return {
        'before': [_row(t, i, kept) for t in before for i in range(len(t['stops']) - 1)] + [_row(run, i, kept) for i in range(a)],
        'after': [_row(run, i, kept) for i in range(b, len(run['stops']))] + [_row(t, i, kept) for t in after for i in range(1, len(t['stops']))],
        'comes': _end((before[0] if before else run)['stops'][0]), 'goes': _end((after[-1] if after else run)['stops'][-1]),
    }


def kept_delays(legs: Sequence[dict]) -> dict[str, dict[str, int]]:
    """{trip id: {stop id: seconds}}: the delays the collector kept for these timetable trips (TripDelay, by stop
    sequence; TripStops says which stop that is), so a delay outlives the feed's report of it. A kept 0 is left out, as
    in _row: the feed's bulk 0 abroad is no measurement. Optional: without the database the live delays still stand."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from prestop_statistics.models import TripDelay, TripStops
    days = {t['id']: datetime.fromtimestamp(t['serviceDay'] + 12 * 3600, ZoneInfo('Europe/Ljubljana')).date() for t in legs}
    try:
        rows = [r for r in TripDelay.objects.filter(trip_id__in=days, service_date__in=set(days.values())) if r.service_date == days[r.trip_id]]
        stops = {s.trip_id: s.stops for s in TripStops.objects.filter(trip_id__in=[r.trip_id for r in rows])} if rows else {}
    except Exception as e:  # noqa: BLE001 - optional, see above
        logging.getLogger(__name__).warning('Kept delays unavailable: %r', e)
        return {}
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        ids = {str(s[0]): s[1] for s in stops.get(r.trip_id) or []}
        found = {ids[seq]: delay for seq, delay in r.stop_delays.items() if delay and seq in ids}
        if found:
            out[r.trip_id] = found
    return out


def learn(trips: Sequence[dict]) -> None:
    """Each train's real ends from a day's timetable, for whatever reads only a name (board rows, vehicles, lines,
    journeys: train_ends). Kept between days: a train that runs on Saturdays is still known on Monday."""
    days: dict[tuple, list[dict]] = {}
    for t in trips:
        number = _number(_route_name(t['route'])) if t['route'].get('mode') == 'RAIL' else None
        if number:
            days.setdefault((t['serviceDay'], number), []).append(t)
    for (_, number), legs in sorted(days.items(), key=lambda item: item[0][0]):
        run = main_run(legs)
        if run:
            whole = whole_run(run, legs)
            _feed_ends[number] = (whole['comes'], whole['goes'])


def crosses(route_name: Optional[str]) -> bool:
    """A train known to run abroad (learn); a domestic train needs no look at its legs."""
    return any(_feed_ends.get(_number(route_name), ()))


def scheduled_ends(trip: dict) -> tuple[Optional[str], Optional[str]]:
    """A scheduled.py run's places abroad (where it comes from, where it goes): a replacement bus's from SŽ's
    timetable (closures._timetable_bus), a train's from the table of international trains."""
    if trip.get('synthetic'):
        return trip.get('comesFrom'), trip.get('goesTo')
    from .mapping import route_name
    stops = trip.get('stops') or [{}]
    return train_ends(route_name(trip.get('route') or {}), stops[0].get('name'), stops[-1].get('name'))
