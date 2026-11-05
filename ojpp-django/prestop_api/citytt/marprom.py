"""Marprom's (Maribor) timetables as they publish them ahead of a change: one PDF per line and direction, one page per stop.

    G1   Avtobusna postaja                          | ◆ Avtobusna postaja
         Smer → Tezenska Dobrava          ID: 001   | ∨ City - zdravstveni dom
    Ime linije: Tezno                               | ∨ …                         (the stops from this one on)
    Ponedeljek – Petek            velja od 01.09.2026 | ● Tezenska Dobrava
    04 05 06 …  23                                  (hour columns, the minutes stacked under each)
    Sobota · Nedelja in prazniki · Ponedeljek – Petek (ŠP)   (the same block)
    (ŠP) – šolske počitnice … od 28.12.2026 do 31.12.2026, od 28.4.2027 do 30.4.2027 in od 26.6.2027 do 31.8.2027
    * Vozi do Lesarske šole.

A page is one stop's departures, so a trip has to be put together from the pages of the stops it passes (`chain`).
Every file has the same layout (778 pages checked 2026-11-04), so words are read by position: the minutes go to the hour
column nearest them, never by their order. Two things on the pages are not departures:
- `<>` in Calibri, white or in the colour of the field it sits under (hour 19's header reads "<1>9" in plain text): the
  template's empty merge fields. They are placed over the header text, never drawn (not in a rendering of the page, and
  the stop's name, direction and ID are the real fields beside them), and no digit sits in them. Dropped.
- `*` after a minute (`15*`, set a size smaller to fit the cell) is a line variant, explained by a legend line at the foot
  of the page (G4: "* Vozi do Lesarske šole."): those trips pass a stop the others skip. Kept as the departure's mark.

Some pages are blank, and some published weekend tables differ from what Marprom runs, so the PDFs give each direction's
stops in order, their school holidays and marks, and the times come from Marprom's interactive timetable
(vozniredi.marprom.si, user 2026-11-05): one page per stop and date lists every line's departures there. A build reads it
for a school weekday, a weekday in ŠP, a Saturday and a Sunday ahead (`from_site`); a line whose weekend there differs
from the published feed's gets its weekend trips rebuilt from it too (`compose`, `weekendFromSite` in the status).
"""
import collections
import csv
import hashlib
import html
import io
import re
import statistics
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta

import pdfplumber
import requests

from .. import geometry, supplement
from ..sztimetables import holiday
from . import City, build

SIDE_X = 655           # pt: the stop list on the right starts here, the timetable ends before it
TITLES = {'Ponedeljek': 'weekday', 'Sobota': 'saturday', 'Nedelja': 'sunday'}
NAME_X = 688           # pt: a stop's name in the stop list starts here (its marker is left of it)
MARKERS = '◆∨●'
CELL = re.compile(r'^(\d\d)(\*?)$')
PLACEHOLDER = re.compile(r'[<>]+')
VALID = re.compile(r'velja\s+od\s+(\d{1,2})\.(\d{1,2})\.(\d{4})')
RANGE = re.compile(r'od\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s+do\s+(\d{1,2})\.(\d{1,2})\.(\d{4})')


class ReadError(ValueError):
    pass


def extract(page) -> list[dict]:
    """A pdfplumber page's words with the font, size and colour that tell the fields apart."""
    return [{'text': w['text'], 'x0': w['x0'], 'x1': w['x1'], 'top': w['top'], 'bottom': w['bottom'],
             'font': w['fontname'].split('+')[-1], 'size': w['size'], 'color': w['non_stroking_color']}
            for w in page.extract_words(extra_attrs=['fontname', 'size', 'non_stroking_color'])]


def parse(path) -> list[dict]:
    """Every page of a direction's PDF, read."""
    try:
        with pdfplumber.open(path) as pdf:
            return [read(extract(page)) for page in pdf.pages]
    except ReadError:
        raise
    except Exception as e:  # pdfminer raises many kinds for a file that is not a PDF
        raise ReadError(f'not a readable PDF: {e!r}') from e


def _clean(words: list[dict]) -> list[dict]:
    """The words without the template's empty merge fields."""
    out = []
    for w in words:
        if PLACEHOLDER.fullmatch(w['text']):
            continue
        text = PLACEHOLDER.sub('', w['text']) if re.search(r'\d', w['text']) else w['text']
        out.append({**w, 'text': text})
    return out


def _rows(words: list[dict], gap: float = 4.0) -> list[list[dict]]:
    out: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if out and abs(w['top'] - out[-1][0]['top']) <= gap:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(r, key=lambda w: w['x0']) for r in out]


def _text(words: list[dict]) -> str:
    return ' '.join(w['text'] for w in sorted(words, key=lambda w: w['x0']))


def read(source) -> dict:
    """One page (its words, or a one-page PDF's path) -> {line, name, headsign, line_name, stop_code, valid_from,
    stops_in_order, tables, holiday_ranges, legend}. `tables` maps weekday, saturday, sunday and weekday_holiday
    (ŠP) to a list of (HH:MM, mark): minutes bound to the hour column above them, past midnight as 24:xx."""
    if not isinstance(source, list):
        pages = parse(source)
        if len(pages) != 1:
            raise ReadError(f'{len(pages)} pages, one expected')
        return pages[0]
    words = _clean(source)
    side = [w for w in words if w['x0'] >= SIDE_X]
    body = [w for w in words if w['x0'] < SIDE_X]
    names, position = _stops(side)
    doc = {**_header(body), 'stops_in_order': names, 'position': position}
    doc['tables'], doc['valid_from'] = _tables(body)
    text = _text_of(body)
    doc['holiday_ranges'] = sorted({(date(int(y1), int(m1), int(d1)), date(int(y2), int(m2), int(d2)))
                                    for d1, m1, y1, d2, m2, y2 in RANGE.findall(text)})
    doc['legend'] = {r[0]['text']: _text(r[1:]) for r in _rows(body) if r[0]['text'] == '*' and len(r) > 1}
    return doc


def _text_of(words: list[dict]) -> str:
    return '\n'.join(_text(r) for r in _rows(words))


def _header(body: list[dict]) -> dict:
    head = [w for w in body if w['top'] < _timetable_top(body)]
    line = [w for w in head if w['x0'] < 100 and w['size'] > 30]
    if len(line) != 1:
        raise ReadError(f'{len(line)} line codes in the header')
    rows = [r for r in _rows([w for w in head if w is not line[0]])]
    ident = next((w for r in rows for w in r if w['text'] == 'ID:'), None)
    number = next((w['text'] for r in rows for w in r if ident and w['x0'] > ident['x0'] and abs(w['top'] - ident['top']) <= 4 and w['text'].isdigit()), None)
    if number is None:
        raise ReadError('no "ID:" in the header')
    direction = next((r for r in rows if r[0]['text'] == 'Smer'), None) or next((r for r in rows if any(w['text'] == 'Smer' for w in r)), None)
    if direction is None:
        raise ReadError('no "Smer" in the header')
    # The stop's name is the large print above the direction; a P+R sign's caption (small) sits beside it.
    name_rows = [[w for w in r if w['x0'] < 590 and w['size'] >= 20] for r in rows if r[0]['top'] < direction[0]['top'] - 5]
    line_name = next((r for r in rows if r[0]['text'] == 'Ime'), None)
    return {
        'line': line[0]['text'], 'stop_code': f's{int(number)}',
        'name': ' '.join(_text(r) for r in name_rows if r),
        'headsign': _text([w for w in direction if w['x0'] < 590 and w['text'] not in ('Smer', '→')]),
        'line_name': _text([w for w in line_name if w['text'] not in ('Ime', 'linije:')]) if line_name else '',
    }


def _timetable_top(body: list[dict]) -> float:
    titles = [w['top'] for w in body if w['x0'] < 40 and w['text'] in TITLES]
    if not titles:
        raise ReadError('no timetable on the page')
    return min(titles) - 5


def _stops(side: list[dict]) -> tuple[list[str], int]:
    """The stop list on the right, the whole direction on every page: a marker (◆ this page's stop, ∨ between, ● the
    ends and the stops where a variant ends) then the name, which may wrap. Returns the names and the ◆'s index."""
    marks = sorted((w for w in side if w['text'] in tuple(MARKERS) and w['x0'] < NAME_X), key=lambda w: w['top'])
    names: list[list[dict]] = [[] for _ in marks]
    for w in side:
        if w['x0'] < NAME_X or not marks:
            continue
        owner = max((i for i, m in enumerate(marks) if m['top'] <= w['top'] + 3), default=None)
        if owner is not None:
            names[owner].append(w)
    here = [i for i, m in enumerate(marks) if m['text'] == '◆']
    # A loop line has its first stop again as the last: that one is the end of the run, the page is the start's.
    if not here or here[1:] not in ([], [len(marks) - 1]):
        raise ReadError(f'{len(here)} ◆ in the stop list')
    return [' '.join(_text(r) for r in _rows(n)) for n in names], here[0]


def _tables(body: list[dict]) -> tuple[dict, date | None]:
    titles = sorted((w for w in body if w['x0'] < 40 and w['text'] in TITLES), key=lambda w: w['top'])
    valid = VALID.search(_text_of(body))
    tables = {k: [] for k in ('weekday', 'saturday', 'sunday', 'weekday_holiday')}
    seen = set()
    for i, title in enumerate(titles):
        kind = TITLES[title['text']]
        end = titles[i + 1]['top'] if i + 1 < len(titles) else float('inf')
        if kind == 'weekday' and any(w['text'] == '(ŠP)' and abs(w['top'] - title['top']) < 14 and w['x0'] < 650 for w in body):
            kind = 'weekday_holiday'
        if kind in seen:
            raise ReadError(f'two {kind} tables')
        seen.add(kind)
        cells = [w for w in body if title['top'] + 10 < w['top'] < end and CELL.match(w['text'])]
        if not cells:
            continue
        top = min(w['top'] for w in cells)
        header = sorted((w for w in cells if abs(w['top'] - top) <= 4), key=lambda w: w['x0'])
        hours = _hours(header)
        pitch = min(b['x0'] - a['x0'] for a, b in zip(header, header[1:])) if len(header) > 1 else 31.0
        found = []
        for w in cells:
            if abs(w['top'] - top) <= 4:
                continue
            centre = (w['x0'] + w['x1']) / 2
            col = min(range(len(header)), key=lambda c: abs((header[c]['x0'] + header[c]['x1']) / 2 - centre))
            if abs((header[col]['x0'] + header[col]['x1']) / 2 - centre) > pitch * 0.6:
                raise ReadError(f'{kind}: "{w["text"]}" at x={w["x0"]:.0f} is under no hour column')
            minute, mark = CELL.match(w['text']).groups()
            if int(minute) > 59:
                raise ReadError(f'{kind}: minute {w["text"]}')
            found.append((hours[col], int(minute), mark))
        tables[kind] = [(f'{h:02d}:{m:02d}', mark) for h, m, mark in sorted(found)]
    return tables, date(int(valid.group(3)), int(valid.group(2)), int(valid.group(1))) if valid else None


def _hours(header: list[dict]) -> list[int]:
    """The header's hours, a column that is earlier than the one before it being after midnight (24:xx)."""
    hours, day = [], 0
    for w in header:
        h = int(w['text'].rstrip('*'))
        if h > 24:
            raise ReadError(f'hour column {w["text"]}')
        if hours and h + day < hours[-1]:
            day += 24
        hours.append(h + day)
    return hours


# ---------------------------------------------------------------- a direction: its pages, then its trips

KINDS = ('weekday', 'saturday', 'sunday', 'weekday_holiday')
TOLERANCE = 2   # min: a departure may differ this much from where the run time expects the trip
SKIP = 40       # stops a trip may skip between two calls (the stops of the variants it does not take)
SPAN = 14       # stops apart that published run times are kept for


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def direction(pages: list[dict]) -> dict:
    """One file's pages -> {line, headsign, valid_from, holiday_ranges, legend, stops, tables}. `stops` is every
    stop of the direction in order as (stop_code or None, name): the stop list is printed on each page, a page is
    its ◆ stop's, and the last stop has no page (nothing departs from it) so no code (`no_page` lists any other). `tables[kind][i]` is stop i's
    departures as (minute of the day, mark), sorted."""
    if not pages:
        raise ReadError('no pages')
    first = pages[0]
    for p in pages:
        for key in ('line', 'stops_in_order', 'valid_from', 'holiday_ranges'):
            if p[key] != first[key]:
                raise ReadError(f'page "{p["name"]}" has another {key} than page "{first["name"]}"')
    names = first['stops_in_order']
    stops: list = [[None, n] for n in names]
    tables = {k: [[] for _ in names] for k in KINDS}
    for p in pages:
        at = p['position']
        if stops[at][0] is not None:
            raise ReadError(f'two pages for stop {at + 1} "{names[at]}"')
        stops[at][0] = p['stop_code']
        for k in KINDS:
            tables[k][at] = sorted((minutes(t), mark) for t, mark in p['tables'][k])
    return {'line': first['line'], 'headsign': first['headsign'], 'valid_from': first['valid_from'],
            'holiday_ranges': first['holiday_ranges'], 'legend': {k: v for p in pages for k, v in p['legend'].items()},
            'stops': [tuple(s) for s in stops], 'tables': tables,
            'no_page': [names[i] for i, (code, _) in enumerate(stops[:-1]) if code is None]}


def run_times(stop_ids: list, trips: list[tuple], deps: list[list[tuple]]):
    """`run(i, j)`: the minutes a bus may take from stop i to stop j of the direction (a list, or None). From the
    published trips ((service, [(stop_id, minute)]) each, which show the pattern between the stops they call at, whatever
    the variant): the median of each service's trips that call at both, since a layover differs from weekday to weekend
    (G3 waits 3 min more at the university on weekends); else the sum of the steps between; else, between neighbours with
    as many departures each, the median gap of the two sorted lists zipped."""
    seen: dict[tuple, dict] = {}
    for service, trip in trips:
        for x, (a, ta) in enumerate(trip):
            for b, tb in trip[x + 1:x + 1 + SPAN]:
                seen.setdefault((a, b), {}).setdefault(service, []).append(tb - ta)
    cache: dict[tuple, object] = {}

    def run(i: int, j: int):
        if (i, j) in cache:
            return cache[i, j]
        found = seen.get((stop_ids[i], stop_ids[j]))
        if found:
            value = {s: statistics.median(g) for s, g in found.items()}
        elif j - i > 1:
            steps = [run(k, k + 1) for k in range(i, j)]
            services = set.intersection(*(set(s) for s in steps if s)) if all(steps) else set()
            value = {s: sum(step[s] for step in steps) for s in services}
        elif len(deps[i]) and len(deps[i]) == len(deps[j]):
            value = {'zip': statistics.median(b[0] - a[0] for a, b in zip(deps[i], deps[j]))}
        else:
            value = None
        value = sorted(set(value.values())) if value else None
        cache[i, j] = value
        return value

    return run


def chain(deps: list[list[tuple]], run, tolerance: float = TOLERANCE, skip: int = SKIP) -> list[list[tuple]]:
    """Trips out of per-stop departures. `deps[i]` is stop i's sorted (minute, mark); `run(i, j)` the run times to expect
    between two stops (a list of minutes, None: unknown). Walking the stops in order, each trip so far is matched to the departure at the
    next stop that its time plus the run time expects, within `tolerance`: in order, no two trips swapping places,
    as many matches as possible, the smallest differences among those. A mark `*` (a variant) only goes on from a trip
    that already had one. A trip may skip up to `skip` stops that have departures (the variant's stops the others pass
    by) and passes by a stop with none. A departure nothing continues ends its trip; one nothing led up to starts a
    new trip (short and depot runs). No time is made up: a trip's stops are the printed departures. A trip is a list
    of (stop index, minute, mark)."""
    seq = [i for i, d in enumerate(deps) if d]
    trips: list[dict] = []
    active: list[dict] = []
    for at, i in enumerate(seq):
        arrivals = deps[i]
        wanted = []
        for t in active:
            if at - t['at'] > skip:
                continue
            r = run(t['calls'][-1][0], i)
            if r:
                wanted.append(([t['calls'][-1][1] + g for g in r], t))
        wanted.sort(key=lambda w: sum(w[0]) / len(w[0]))
        match = _align([w[0] for w in wanted], [(w[1]['calls'][-1][1], w[1]['marked']) for w in wanted], arrivals, tolerance)
        taken = set(match.values())
        for k, d in match.items():
            t = wanted[k][1]
            t['calls'].append((i, *arrivals[d]))
            t['at'] = at
            t['marked'] = t['marked'] or arrivals[d][1] == '*'
        for d, (minute, mark) in enumerate(arrivals):
            if d not in taken:
                t = {'calls': [(i, minute, mark)], 'at': at, 'marked': mark == '*'}
                trips.append(t)
                active.append(t)
        active = [t for t in active if at - t['at'] < skip]
    return [t['calls'] for t in sorted(trips, key=lambda t: (t['calls'][0][1], t['calls'][0][0]))]


def steps_of(history: list[tuple], last_only: bool = False) -> dict:
    """{stop: {next stop: [(service, minutes)]}} over published trips ((service, [(stop_id, minute)]) each): every step, or
    with `last_only` only the step that ends each trip."""
    out: dict = {}
    for service, trip in history:
        for (a, ta), (b, tb) in zip(trip[-2:-1] if last_only else trip, trip[-1:] if last_only else trip[1:]):
            out.setdefault(a, {}).setdefault(b, []).append((service, tb - ta))
    return out


def _same_name(a: str, b: str) -> bool:
    return re.sub(r'\W+', '', a).lower() == re.sub(r'\W+', '', b).lower()


def last_call(stop: str, final, ends: dict, steps: dict, names: dict, weekday: set):
    """The stop a trip whose last printed departure is at `stop` arrives at, with the minutes to it, or None. Nothing departs
    from it, so it has no page and no printed time: the time is the published run time. `ends` (steps_of, last_only): the line's
    published trips that end right after `stop` say which stop, one named as the page says first, then most trips. `final`: the
    direction's last stop's name, when `stop` is the last with a page; there, any line's published step to a stop of that name
    also counts (P18's Turnerjeva). The run time is the median of the published weekday tables (`weekday`), else of all."""
    found = ends.get(stop)
    if not found and final:
        found = {b: g for b, g in steps.get(stop, {}).items() if _same_name(names.get(b, ''), final)}
    if not found:
        return None
    best = min(found, key=lambda b: (not (final and _same_name(names.get(b, ''), final)), -len(found[b]), b))
    gaps = found[best]
    return best, round(statistics.median([g for s, g in gaps if s in weekday] or [g for _, g in gaps]))


def _align(expected: list[list[float]], trips: list[tuple], arrivals: list[tuple], tolerance: float) -> dict[int, int]:
    """Candidate index -> departure index: the order-keeping pairing with the most pairs, then the least difference.
    `trips` is each candidate's (last minute, marked). Pairs differ by at most `tolerance` minutes from one of the
    expected times and never go back in time; a departure marked `*` pairs only with a candidate that was marked."""
    n, m = len(expected), len(arrivals)

    def cost(a, b):
        gap = min(abs(arrivals[b][0] - e) for e in expected[a])
        last, marked = trips[a]
        if gap > tolerance or arrivals[b][0] < last or (arrivals[b][1] == '*' and not marked):
            return None
        return gap + (0.0 if arrivals[b][1] == '*' or not marked else 0.01)

    best = [[(0, 0.0)] * (m + 1) for _ in range(n + 1)]
    for a in range(1, n + 1):
        for b in range(1, m + 1):
            top = max(best[a - 1][b], best[a][b - 1])
            c = cost(a - 1, b - 1)
            if c is not None:
                pairs, spent = best[a - 1][b - 1]
                top = max(top, (pairs + 1, spent - c))
            best[a][b] = top
    out, a, b = {}, n, m
    while a and b:
        if best[a][b] == best[a - 1][b]:
            a -= 1
        elif best[a][b] == best[a][b - 1]:
            b -= 1
        else:
            out[a - 1] = b - 1
            a, b = a - 1, b - 1
    return out


# ---------------------------------------------------------------- the feed

GTFS_URL = 'https://vozniredi.marprom.si/GTFS/gtfs.zip'
DELAY = 1.1                    # s between two requests to marprom.si
WEEKDAY, HOLIDAY = 'pdf-weekday', 'pdf-holiday'   # Monday–Friday; Monday–Friday in the school holidays (ŠP)
SATURDAY, SUNDAY = 'site-saturday', 'site-sunday'      # a line's weekend, rebuilt from the site where the published one differs
SERVICES = {'weekday': WEEKDAY, 'weekday_holiday': HOLIDAY, 'saturday': SATURDAY, 'sunday': SUNDAY}
TAGS = {'weekday': 'wd', 'weekday_holiday': 'sp', 'saturday': 'sa', 'sunday': 'su'}
EXTEND_AT = 0.995              # share of equal stop departures (of both sides) that lets Saturday and Sunday run on
OFF_SHAPE = 50                 # m: a published shape passes a stop this close to count as passing it
WEEK = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')
TRIP_KEYS = ('route_id', 'service_id', 'trip_id', 'trip_headsign', 'trip_short_name', 'direction_id', 'shape_id')
GTFS_FILES = ('agency', 'routes', 'stops', 'trips', 'stop_times', 'calendar', 'calendar_dates', 'shapes')


@dataclass
class Fetched:
    """What a build reads: the published GTFS zip and the timetable PDFs ({'url', 'name', 'line', 'dir', 'data'})."""
    gtfs: bytes
    files: list = field(default_factory=list)


class _Pace:
    """One request at a time, DELAY seconds apart, through build._get."""

    def __init__(self):
        self.last = float('-inf')

    def __call__(self, url: str) -> bytes:
        wait = self.last + DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return build._get(url)
        except requests.RequestException as e:
            raise build.BuildError(f'{url}: {e!r}') from e
        finally:
            self.last = time.monotonic()


def _published(data: bytes) -> dict[str, list[dict]]:
    """The published GTFS zip's text files as rows."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        return {f'{n}.txt': list(csv.DictReader(io.TextIOWrapper(z.open(f'{n}.txt'), 'utf-8-sig'))) for n in GTFS_FILES}
    except (zipfile.BadZipFile, KeyError) as e:
        raise build.BuildError(f'the published GTFS is not usable: {e!r}') from e


def fetch(city: City, today: date, pace=None) -> Fetched:
    """The published feed, then each line's page and the two timetable PDFs it links, one request after another. A new
    date in a file name still works: the newest file in force today, else the next one to come."""
    pace = pace or _Pace()
    gtfs = pace(GTFS_URL)
    now = today.strftime('%Y%m%d')
    files = []
    for line in [r['route_short_name'] for r in _published(gtfs)['routes.txt']]:
        url = city.page.replace('{line}', line.lower())
        page = html.unescape(pace(url).decode('utf-8', 'replace'))
        found: dict[str, dict[str, str]] = {}
        for link, day, which in re.findall(city.links.replace('{line}', re.escape(line)), page):
            found.setdefault(which, {})[day] = link
        for which in ('plus', 'minus'):
            if not found.get(which):
                raise build.BuildError(f'{line}: no "{which}" timetable linked on {url}')
            days = sorted(found[which])
            current = [d for d in days if d <= now]
            link = found[which][current[-1] if current else days[0]]
            files.append({'url': link, 'name': link.rsplit('/', 1)[-1], 'line': line, 'dir': which, 'data': pace(link)})
    return Fetched(gtfs, files)


def read_pdf(data: bytes) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
        tmp.write(data)
        tmp.flush()
        return parse(tmp.name)


def _trips_of(published: dict) -> dict[str, dict]:
    """Published trips by id: {'route', 'service', 'headsign', 'shape', 'direction', 'row', 'stops': [(stop_id, minute)]}."""
    times: dict[str, list] = {}
    for r in published['stop_times.txt']:
        h, m, _ = r['departure_time'].split(':')
        times.setdefault(r['trip_id'], []).append((int(r['stop_sequence']), r['stop_id'], int(h) * 60 + int(m)))
    out = {}
    for t in published['trips.txt']:
        stops = [(s, m) for _, s, m in sorted(times.get(t['trip_id'], []))]
        out[t['trip_id']] = {'route': t['route_id'], 'service': t['service_id'], 'headsign': t['trip_headsign'], 'shape': t['shape_id'],
                             'direction': t['direction_id'], 'row': t, 'stops': stops, 'seq': [s for s, _ in stops]}
    return out


def agreement(directions: list[dict], by_code: dict, routes: dict, published: dict[str, dict], services: dict[str, str]) -> dict:
    """How far the PDFs' Saturday and Sunday tables equal the published trips of those days, as stop departures
    (line, stop, minute) present on both sides, in total and per line. A published trip's last call is an arrival and the
    PDF has no page for a direction's last stop, so neither is counted."""
    out = {}
    line_of = {route: line for line, route in routes.items()}
    for kind, service in services.items():
        theirs, mine = collections.Counter(), collections.Counter()
        pages: dict[str, set] = {}
        for d in directions:
            for (code, _), deps in zip(d['doc']['stops'], d['doc']['tables'][kind]):
                if code in by_code:
                    pages.setdefault(d['line'], set()).add(by_code[code])
                    mine.update((d['line'], by_code[code], m) for m, _ in deps)
        for t in published.values():
            line = line_of.get(t['route'])
            if t['service'] == service and line:
                theirs.update((line, s, m) for s, m in t['stops'][:-1] if s in pages.get(line, ()))
        lines = {}
        for line in sorted({k[0] for k in theirs} | {k[0] for k in mine}):
            a = {k: v for k, v in theirs.items() if k[0] == line}
            b = {k: v for k, v in mine.items() if k[0] == line}
            lines[line] = {'equal': sum(min(v, b.get(k, 0)) for k, v in a.items()), 'published': sum(a.values()), 'pdf': sum(b.values())}
        equal, pub, pdf = (sum(v[k] for v in lines.values()) for k in ('equal', 'published', 'pdf'))
        out[kind] = {'equal': equal, 'published': pub, 'pdf': pdf, 'lines': lines,
                     'agrees': bool(pub and pdf and equal / pub >= EXTEND_AT and equal / pdf >= EXTEND_AT)}
    return out


def _slice(small: list, big: list) -> int:
    """Where `small` runs as a contiguous part of `big`, else -1."""
    for at in range(len(big) - len(small) + 1):
        if big[at:at + len(small)] == small:
            return at
    return -1


class _Shapes:
    """Which shape, headsign and direction a new trip takes: those of a published trip on the route that calls at the
    same stops (give or take its last one, when ours ends a stop earlier), else of the one whose stops contain ours with the
    fewest more, else the shape of the published trip sharing most stops with ours that passes them all in order (its
    headsign too), else none (supplement.py routes such a trip on the roads)."""

    def __init__(self, published: dict, stops: dict, trips: dict):
        self.trips, self.stops = trips, stops
        self.coords: dict[str, list] = {}
        for r in sorted(published['shapes.txt'], key=lambda r: (r['shape_id'], int(r['shape_pt_sequence']))):
            self.coords.setdefault(r['shape_id'], []).append([float(r['shape_pt_lon']), float(r['shape_pt_lat'])])
        self.cache: dict[tuple, tuple] = {}
        self.counts: collections.Counter = collections.Counter()

    def of(self, route: str, ids: tuple) -> tuple[str, str, str]:
        key = (route, ids)
        if key not in self.cache:
            self.cache[key] = self._find(route, list(ids))
        self.counts[self.cache[key][3]] += 1
        return self.cache[key][:3]

    def _find(self, route: str, ids: list) -> tuple:
        same, within = [], []
        for t in self.trips.values():
            if t['route'] == route:
                at = _slice(ids, t['seq'])
                if at == 0 and len(t['seq']) - len(ids) <= 1:
                    same.append(t)
                elif at >= 0:
                    within.append((len(t['seq']) - len(ids), t))
        pick, how = same, 'published trip'
        if not pick and within:
            fewest = min(extra for extra, _ in within)
            pick, how = [t for extra, t in within if extra == fewest], 'published trip with more stops'
        if pick:
            top = collections.Counter((t['shape'], t['headsign'], t['direction']) for t in pick).most_common(1)[0][0]
            return (*top, how)
        points = [{'lat': float(self.stops[s]['stop_lat']), 'lon': float(self.stops[s]['stop_lon'])} for s in ids]
        ranked = sorted((t for t in self.trips.values() if t['route'] == route and t['shape']),
                        key=lambda t: (-len(set(ids) & set(t['seq'])), t['row']['trip_id']))
        tried = set()
        for t in ranked:   # the shape of the published trip that shares most stops with ours, if it passes them all
            if t['shape'] in tried:
                continue
            tried.add(t['shape'])
            coords = self.coords.get(t['shape']) or []
            if len(coords) > 1 and all(off <= OFF_SHAPE for _, off in geometry.project_stops(coords, points)):
                return t['shape'], t['headsign'], t['direction'], 'published shape'
        return '', '', '', 'no shape'


def _time(minute: int) -> str:
    return f'{minute // 60:02d}:{minute % 60:02d}:00'


def compose(city: City, directions: list[dict], published: dict, today: date, site_used: bool = False) -> tuple[dict[str, list[dict]], dict, list[str]]:
    """GTFS rows per file name, the facts about the build, and the problems found. `directions`: [{'line', 'dir',
    'doc'}] (`direction()`'s result per PDF). Weekday trips come from the PDFs' tables (chain); Saturday and Sunday keep
    the published trips, which run on to the PDFs' end only when the PDFs agree with them; the summer tables are dropped."""
    docs = [d['doc'] for d in directions]
    valid = {d['valid_from'] for d in docs}
    ranges = {tuple(d['holiday_ranges']) for d in docs}
    if len(valid) != 1 or None in valid:
        return {}, {}, [f'the timetables start on {", ".join(sorted(str(v) for v in valid))}: one date expected']
    if len(ranges) != 1:
        return {}, {}, ['the files list different school holidays (ŠP)']
    start, holidays = next(iter(valid)), list(next(iter(ranges)))
    end = max([b for _, b in holidays] + [start])
    day = lambda d: d.strftime('%Y%m%d')  # noqa: E731
    problems: list[str] = []
    stops = {r['stop_id']: r for r in published['stops.txt']}
    by_code = {r['stop_code']: r['stop_id'] for r in published['stops.txt'] if r.get('stop_code')}
    routes = {r['route_short_name']: r['route_id'] for r in published['routes.txt']}
    trips = _trips_of(published)
    calendar = {r['service_id']: r for r in published['calendar.txt']}
    ended = {s for s, r in calendar.items() if r['end_date'] < day(start)}
    keep = [s for s in calendar if s not in ended]
    problems += [f'the published feed runs weekday service {s} again after {start}: this feed is not needed any more'
                 for s in keep if any(calendar[s][d] == '1' for d in WEEK)]
    services = {kind: next((s for s in sorted(keep) if calendar[s][kind] == '1'), None) for kind in ('saturday', 'sunday')}
    services = {k: v for k, v in services.items() if v}
    weekend = agreement(directions, by_code, routes, trips, services)
    rebuilt = {kind: sorted(line for line, v in weekend[kind]['lines'].items() if not _line_agrees(v))
               for kind in services} if site_used else {}

    new, stop_rows, unknown = [], [], collections.defaultdict(set)
    names = {sid: r['stop_name'] for sid, r in stops.items()}
    all_steps = steps_of([(t['service'], t['stops']) for t in trips.values()])
    no_last: set = set()
    shapes, ids_used, per_line, alone = _Shapes(published, stops, trips), set(), collections.Counter(), collections.Counter()
    for d in directions:
        line, doc = d['line'], d['doc']
        if line not in routes:
            problems.append(f'line {line} is not in the published feed')
            continue
        ids = []
        for code, name in doc['stops']:
            if code and code not in by_code:
                unknown[line].add(f'{code} {name}')
            ids.append(by_code.get(code, ''))
        if unknown[line]:
            continue
        route = routes[line]
        history = [(t['service'], t['stops']) for t in trips.values() if t['route'] == route]
        line_ends = steps_of(history, last_only=True)
        last_page = max(i for i, (code, _) in enumerate(doc['stops']) if code)
        for kind in ('weekday', 'weekday_holiday', *(k for k in ('saturday', 'sunday') if line in rebuilt.get(k, ()))):
            deps = doc['tables'][kind]
            for trip in chain(deps, run_times(ids, history, deps)):
                at = trip[-1][0]
                final = doc['stops'][-1][1] if at == last_page and at < len(ids) - 1 else None
                arrival = last_call(ids[at], final, line_ends, all_steps, names, ended)
                if final and not arrival:
                    no_last.add(f'{line} {d["dir"]}: {final}')
                if len(trip) < 2 and not arrival:
                    alone[line] += 1
                    continue
                call_ids = [ids[i] for i, _, _ in trip] + ([arrival[0]] if arrival else [])
                shape, headsign, direction_id = shapes.of(route, tuple(call_ids))
                base = f'{line}-{d["dir"]}-{TAGS[kind]}-{doc["stops"][trip[0][0]][0]}-{trip[0][1] // 60:02d}{trip[0][1] % 60:02d}'
                tid, copy = base, 1
                while tid in ids_used:
                    copy += 1
                    tid = f'{base}-{copy}'
                ids_used.add(tid)
                service = SERVICES[kind]
                per_line[line] += service == WEEKDAY
                new.append({'route_id': route, 'service_id': service, 'trip_id': tid, 'trip_headsign': headsign or doc['headsign'],
                            'trip_short_name': line, 'direction_id': direction_id or ('0' if d['dir'] == 'plus' else '1'), 'shape_id': shape})
                stop_rows += [{'trip_id': tid, 'arrival_time': _time(m), 'departure_time': _time(m), 'stop_id': ids[i],
                               'stop_sequence': str(seq + 1), 'timepoint': '1'} for seq, (i, m, _) in enumerate(trip)]
                if arrival:  # the last stop: no page, so the published run time and not a printed time
                    clock = _time(trip[-1][1] + arrival[1])
                    stop_rows.append({'trip_id': tid, 'arrival_time': clock, 'departure_time': clock, 'stop_id': arrival[0],
                                      'stop_sequence': str(len(trip) + 1), 'timepoint': '0'})
    problems += [f'{line}: stop codes not in the published feed: {", ".join(sorted(names))}' for line, names in sorted(unknown.items()) if names]
    problems += [f'line {line} has no weekday trips' for line in routes if not per_line[line] and not unknown.get(line)]
    if problems:
        return {}, {}, problems

    cal_rows = [dict(r) for r in published['calendar.txt'] if r['service_id'] in keep]
    for r in cal_rows:   # with the site, a line that disagrees is rebuilt, so the rest agrees
        kind = next((k for k, s in services.items() if s == r['service_id']), None)
        if kind and (weekend[kind]['agrees'] or site_used):
            r['end_date'] = day(end)
    cal_rows += [{'service_id': WEEKDAY, **{x: '1' for x in WEEK}, 'saturday': '0', 'sunday': '0', 'start_date': day(start), 'end_date': day(end)},
                 {'service_id': HOLIDAY, **{x: '0' for x in (*WEEK, 'saturday', 'sunday')}, 'start_date': day(start), 'end_date': day(end)}]
    cal_rows += [{'service_id': SERVICES[kind], **{x: '0' for x in WEEK}, 'saturday': str(int(kind == 'saturday')), 'sunday': str(int(kind == 'sunday')),
                  'start_date': day(start), 'end_date': day(end)} for kind in ('saturday', 'sunday') if rebuilt.get(kind)]
    alike = {k: [s for s in (services.get(k), rebuilt.get(k) and SERVICES[k]) if s] for k in ('saturday', 'sunday')}
    ends = {r['service_id']: r['end_date'] for r in cal_rows}
    dates = {(r['service_id'], r['date']): r for r in published['calendar_dates.txt'] if r['service_id'] in keep}

    def exception(service: str, d: date, kind: str) -> None:
        dates[service, day(d)] = {'service_id': service, 'date': day(d), 'exception_type': kind}

    d = start
    while d <= end:  # a public holiday is a Sunday, whatever the weekday; ŠP days run their own table
        if d.weekday() < 5 and holiday(d):
            exception(WEEKDAY, d, '2')
        elif d.weekday() < 5 and any(a <= d <= b for a, b in holidays):
            exception(WEEKDAY, d, '2')
            exception(HOLIDAY, d, '1')
        if holiday(d) and d.weekday() < 6:
            for s in alike['sunday']:
                if day(d) <= ends[s]:
                    exception(s, d, '1')
            for s in alike['saturday'] if d.weekday() == 5 else ():
                if day(d) <= ends[s]:
                    exception(s, d, '2')
        d += timedelta(days=1)

    line_of = {route: line for line, route in routes.items()}
    gone = {(services[k], line) for k, lines in rebuilt.items() for line in lines}   # published weekend trips the site's replace
    kept = [t['row'] for t in trips.values() if t['service'] in keep and (t['service'], line_of.get(t['route'])) not in gone]
    kept_ids = {r['trip_id'] for r in kept}
    all_trips = [{k: r.get(k, '') for k in TRIP_KEYS} for r in kept] + new
    used = {r['shape_id'] for r in all_trips if r['shape_id']}
    files = {
        'agency.txt': published['agency.txt'], 'routes.txt': published['routes.txt'], 'stops.txt': published['stops.txt'],
        'trips.txt': all_trips, 'stop_times.txt': [r for r in published['stop_times.txt'] if r['trip_id'] in kept_ids] + stop_rows,
        'calendar.txt': cal_rows, 'calendar_dates.txt': sorted(dates.values(), key=lambda r: (r['service_id'], r['date'])),
        'shapes.txt': [r for r in published['shapes.txt'] if r['shape_id'] in used],
    }
    last = min(ends[s] for s in (WEEKDAY, HOLIDAY, *services.values()))
    facts = {'end': f'{last[:4]}-{last[4:6]}-{last[6:]}', 'lines': dict(sorted(per_line.items())), 'weekend': weekend,
             'shapes': dict(shapes.counts), 'aloneDepartures': dict(alone), 'noLastStop': sorted(no_last), 'dropped': sorted(ended),
             'shapesInPublished': len({r['shape_id'] for r in published['shapes.txt']}), 'shapesKept': len(used),
             'weekendFromSite': {k: v for k, v in rebuilt.items() if v}}
    return files, facts, problems


def _line_agrees(v: dict) -> bool:
    """One line's weekend agreement: no departures on either side, or equal at EXTEND_AT of both."""
    if not v['published'] and not v['pdf']:
        return True
    return bool(v['published'] and v['pdf'] and v['equal'] / v['published'] >= EXTEND_AT and v['equal'] / v['pdf'] >= EXTEND_AT)


def check(files: dict[str, str], today: date) -> list[str]:
    """Problems with the written files as supplement.py reads them."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in files.items():
            z.writestr(name, text)
    feed = supplement.parse('MARPROM', buf.getvalue())
    problems = []
    expected = len({r['trip_id'] for r in csv.DictReader(io.StringIO(files['stop_times.txt']))})
    if len(feed['trips']) != expected:
        problems.append(f'{len(feed["trips"])} trips read back, {expected} written')
    for trip in feed['trips'].values():
        deps = [s['departure'] for s in trip['stops']]
        if deps != sorted(deps):
            problems.append(f'{trip["id"]}: times not in order')
    if not any(supplement.runs(feed, WEEKDAY, today + timedelta(days=n)) for n in range(14)):
        problems.append(f'the weekday service does not run in the 14 days from {today}')
    return problems


SITE_URL = 'https://vozniredi.marprom.si/?stop={stop}&datum={day}'
SITE_LINE = re.compile(r'Naslednji odhodi za linijo <span[^>]*>\s*(\w+)\s*</span>(.*?)</table>', re.S)
SITE_ROW = re.compile(r'<td class="tdWidth">\s*(.*?)\s*</td>\s*<td>(.*?)</td>', re.S)
SITE_DAY = re.compile(r'id="datum"[^>]*value="(\d{4}-\d\d-\d\d)"')
SITE_AHEAD = 56   # days ahead a sample day is looked for


def site_departures(text: str, day: date) -> dict[str, list[tuple[str, list[int]]]] | None:
    """One page of vozniredi.marprom.si (a stop on a date: every line's departures there, per variant) -> {line:
    [(variant, [minute of the day])]}; None when the site shows another date than asked (past the dates it has). The
    times are in the day's order, so one earlier than the one before it is after midnight."""
    shown = SITE_DAY.search(text)
    if not shown or shown.group(1) != day.isoformat():
        return None
    out: dict[str, list] = {}
    for line, body in SITE_LINE.findall(text):
        for label, cells in SITE_ROW.findall(body):
            mins, prev = [], -1
            for t in re.findall(r'\b(\d\d):(\d\d)\b', cells):
                m = int(t[0]) * 60 + int(t[1])
                while m < prev:
                    m += 1440
                mins.append(m)
                prev = m
            out.setdefault(line, []).append((html.unescape(re.sub(r'\s+', ' ', label)).strip(), mins))
    return out


def sample_days(today: date, holidays: list[tuple[date, date]]) -> dict[str, date]:
    """The first day after today of each table: a school weekday, a weekday in the school holidays (ŠP), a Saturday and
    a Sunday that are no public holiday, within SITE_AHEAD days."""
    out: dict[str, date] = {}
    for n in range(1, SITE_AHEAD + 1):
        d = today + timedelta(days=n)
        if holiday(d):
            continue
        kind = ('saturday' if d.weekday() == 5 else 'sunday' if d.weekday() == 6 else
                'weekday_holiday' if any(a <= d <= b for a, b in holidays) else 'weekday')
        out.setdefault(kind, d)
    return out


def from_site(directions: list[dict], by_code: dict, site, days: dict[str, date]) -> dict:
    """Each PDF page's tables replaced by the site's departures at that stop on a sample day of the table (some PDF pages
    are blank, the site is what Marprom runs now). The site lists a stop's departures per variant, not per PDF file: a stop
    only one direction of the line has a page at takes all of the line's; at one both have (a turning point), a variant
    goes where it went at the stops only one direction has. A variant is a `*` one when the PDFs mark most of its
    departures. A table the site has no day for keeps the PDF's. Returns what changed."""
    pages: dict[tuple, list] = collections.defaultdict(list)   # (line, stop id) -> [(direction, stop index)]
    for d in directions:
        for i, (code, _) in enumerate(d['doc']['stops']):
            if code in by_code:
                pages[d['line'], by_code[code]].append((d, i))
    stop_ids = sorted({sid for _, sid in pages})
    answers = {(sid, kind): site(sid, day) for sid in stop_ids for kind, day in days.items()}
    # the site shows its school-day table in the school holidays too (all stops, 2026-11-05): then the PDFs' ŠP stays
    holiday_as_weekday = 'weekday_holiday' in days and 'weekday' in days and all(
        answers[s, 'weekday_holiday'] == answers[s, 'weekday'] for s in stop_ids)
    used = {k: v for k, v in days.items() if not (holiday_as_weekday and k == 'weekday_holiday')}
    side: dict[tuple, str] = {}                     # (line, variant) -> direction
    stars: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for (line, sid), here in pages.items():
        if len(here) != 1:
            continue
        d, i = here[0]
        for kind in used:
            pdf = dict(d['doc']['tables'][kind][i])
            for label, mins in (answers[sid, kind] or {}).get(line, []):
                side.setdefault((line, label), d['dir'])
                stars[line, label].update(pdf[m] == '*' for m in mins if m in pdf)
    starred = {k for k, c in stars.items() if c[True] > c[False]}
    changed, filled, unplaced = collections.Counter(), collections.Counter(), set()
    for (line, sid), here in sorted(pages.items(), key=lambda kv: kv[0]):
        for kind in used:
            got = answers[sid, kind]
            if got is None:
                continue
            for d, i in here:
                pdf = dict(d['doc']['tables'][kind][i])
                deps = []
                for label, mins in got.get(line, []):
                    if len(here) > 1 and side.get((line, label)) != d['dir']:
                        if (line, label) not in side:
                            unplaced.add(f'{line} {sid}: {label}')
                        continue
                    mark = '*' if (line, label) in starred else ''
                    deps += [(m, mark or pdf.get(m, '')) for m in mins]
                deps.sort()
                if deps != sorted(d['doc']['tables'][kind][i]):
                    changed[line] += 1
                    filled[line] += not d['doc']['tables'][kind][i]
                d['doc']['tables'][kind][i] = deps
    return {'days': {k: v.isoformat() for k, v in sorted(days.items())},
            'missing': sorted(k for k in days if all(answers[s, k] is None for s in stop_ids)),
            'holidayAsWeekday': holiday_as_weekday,
            'changedPages': dict(sorted(changed.items())), 'blankPagesFilled': dict(sorted(filled.items())), 'unplaced': sorted(unplaced)}


class Site:
    """vozniredi.marprom.si, one page at a time through the same pace; keeps every answer's hash for the status."""

    def __init__(self, pace):
        self.pace, self.hashes = pace, {}

    def __call__(self, stop: str, day: date):
        data = self.pace(SITE_URL.format(stop=stop, day=day.isoformat()))
        self.hashes[stop, day.isoformat()] = hashlib.sha256(data).hexdigest()
        return site_departures(data.decode('utf-8', 'replace'), day)


def make(city: City, src: Fetched, today: date, read=read_pdf, site=None) -> tuple[dict[str, str], dict]:
    """The feed's files (name -> text) and its status from what was fetched; raises BuildError with every problem.
    `site(stop id, day)`: the site's departures there (site_departures), which replace the PDFs' tables (from_site)."""
    published = _published(src.gtfs)
    directions, problems = [], []
    for f in src.files:
        try:
            doc = direction(read(f['data']))
        except ReadError as e:
            problems.append(f'{f["name"]}: {e}')
            continue
        if doc['line'] != f['line']:
            problems.append(f'{f["name"]} is the timetable of line {doc["line"]}, not {f["line"]}')
        directions.append({'line': f['line'], 'dir': f['dir'], 'doc': doc})
    keys = [(d['line'], d['dir']) for d in directions]
    problems += [f'{line} {which} read from two files' for line, which in sorted({k for k in keys if keys.count(k) > 1})]
    if problems:
        raise build.BuildError('\n'.join(problems))
    filled = None
    if site and directions:
        by_code = {r['stop_code']: r['stop_id'] for r in published['stops.txt'] if r.get('stop_code')}
        filled = from_site(directions, by_code, site, sample_days(today, directions[0]['doc']['holiday_ranges']))
        if 'weekday' in filled['missing'] or 'weekday' not in filled['days']:
            problems.append(f'the site has no weekday day in the {SITE_AHEAD} days from {today}')
        if problems:
            raise build.BuildError('\n'.join(problems))
    rows, facts, found = compose(city, directions, published, today, site_used=filled is not None)
    problems += found
    files = {name: build.to_text(r) for name, r in rows.items()}
    if not problems:
        problems += check(files, today)
    if problems:
        raise build.BuildError('\n'.join(problems))
    hashes = [{'file': 'gtfs.zip', 'url': GTFS_URL, 'sha256': hashlib.sha256(src.gtfs).hexdigest()}] + [
        {'file': f['name'], 'url': f['url'], 'sha256': hashlib.sha256(f['data']).hexdigest()} for f in src.files]
    version = hashlib.sha256(''.join(files[k] for k in sorted(files)).encode()).hexdigest()[:12]
    first = min(r['start_date'] for r in rows['calendar.txt'])
    files['feed_info.txt'] = build.to_text([{'feed_publisher_name': 'KamGre', 'feed_publisher_url': 'https://kamgre.si', 'feed_lang': 'sl',
                                             'feed_start_date': first, 'feed_end_date': facts['end'].replace('-', ''), 'feed_version': version}])
    status = {'status': 'ok', 'version': version, 'end': facts['end'], 'source': city.page.split('{line}')[0], 'files': hashes,
              'lines': facts['lines'], 'weekend': facts['weekend'], 'shapes': facts['shapes'], 'aloneDepartures': facts['aloneDepartures'], 'noLastStop': facts['noLastStop'],
              'weekendFromSite': facts['weekendFromSite']}
    if filled is not None:
        pages = getattr(site, 'hashes', {})
        status['site'] = {'url': SITE_URL.split('?')[0], 'pages': len(pages),
                          'sha256': hashlib.sha256(''.join(f'{k}{v}' for k, v in sorted(pages.items())).encode()).hexdigest(), **filled}
    return files, status


def run(city: City, today: date) -> tuple[dict[str, str], dict]:
    """Fetch (politely, one file at a time) and build; what manage.py city_timetables calls for this city. The site's
    pages (one per stop and sample day, about 1,800) take some 35 minutes at this pace."""
    pace = _Pace()
    return make(city, fetch(city, today, pace), today, site=Site(pace))
