"""SŽ's replacement timetables: the PDF each closure notice links ("Vozni red nadomestnega prevoza").

A separate job (`manage.py szpdf_sync`) reads every PDF into one JSON file per PDF in
`PRESTOP_SZ_TIMETABLES_DIR`, `<sha256>.json`, and lists which notice links which file in `index.json`
(the contract is in docs/specs/2026-10-14-sz-replacement-timetables.md). This module only reads those
files: the web workers never touch a PDF.

A file holds tables of columns, one per bus ("318/2": train 318's second bus), each with its calls in
travel order, footnote numbers that say on which days it runs, and the problems the reader found. A
file the reader is sure of is "ok"; an "unsure" one has columns with problems, which are not used;
a "failed" one is not used at all. Which buses this gives on a service day is closures.py's business.

Reading is cheap but not free, and the server's disk can be slow to stat (a 9p mount locally): the
files are read again at most once a minute (RELOAD), only when index.json changed, and only by a
background thread (`load`, see warm.py); requests use what was read last (`current`).
"""
import json
import logging
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from django.conf import settings

from . import geometry
from .mapping import fold

logger = logging.getLogger(__name__)

RELOAD = 60  # s between looks at index.json
_lock = threading.Lock()
_state: dict = {'checked': None, 'stamp': None, 'tables': None, 'files': {}}


class Timetables:
    """The files of one index.json. A notice can link several (11248: 12. - 18. October and a November
    timetable): `files_for(notice)` lists them, the one index.json names first; `file_on(notice, day)` is
    the one valid that day."""

    def __init__(self, notices: dict[str, str], files: dict[str, dict], updated: Optional[str] = None):
        self.notices, self.files, self.updated = notices, files, updated
        self.by_notice: dict[str, list[dict]] = {}
        for sha, data in sorted(files.items(), key=lambda kv: ((kv[1].get('valid') or {}).get('from') or '', kv[0])):
            for notice in data.get('notices') or []:
                self.by_notice.setdefault(str(notice), []).append(data)
        for notice, sha in notices.items():
            self.by_notice[notice] = [files[sha]] + [f for f in self.by_notice.get(notice, []) if f is not files[sha]]

    def file(self, notice: Optional[str]) -> Optional[dict]:
        return self.files.get(self.notices.get(notice or '', ''))

    def files_for(self, notice: Optional[str]) -> list[dict]:
        return self.by_notice.get(notice or '', [])

    def file_on(self, notice: Optional[str], day: date) -> Optional[dict]:
        return next((f for f in self.files_for(notice) if valid_on(f, day)), None)


def directory() -> Optional[Path]:
    path = getattr(settings, 'PRESTOP_SZ_TIMETABLES_DIR', '') or ''
    return Path(path) if path else None


def reset():
    """Forget what was read (tests)."""
    with _lock:
        _state.update(checked=None, stamp=None, tables=None, files={})


def current() -> Optional[Timetables]:
    """The timetables read last; never touches the disk."""
    return _state['tables']


def load(now: Optional[float] = None) -> Optional[Timetables]:
    """The timetables, read again when index.json changed, looking at most once a minute. None when the
    directory or its index is missing (then everything behaves as without timetables)."""
    now = time.monotonic() if now is None else now
    with _lock:
        if _state['checked'] is not None and now - _state['checked'] < RELOAD:
            return _state['tables']
        _state['checked'] = now
        where = directory()
        try:
            info = os.stat(where / 'index.json') if where else None
        except OSError:
            info = None
        stamp = (info.st_mtime_ns, info.st_size) if info else None
        if stamp == _state['stamp']:
            return _state['tables']
        _state['stamp'] = stamp
        _state['tables'] = read(where, _state['files']) if stamp else None
        _state['files'] = _state['tables'].files if _state['tables'] else {}
        return _state['tables']


def read(where: Path, known: Optional[dict[str, dict]] = None) -> Optional[Timetables]:
    """The timetables in directory `where`; `known`: files already read, by checksum."""
    try:
        index = json.loads((where / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        logger.warning('SŽ timetables: index.json unreadable: %r', e)
        return None
    notices = {str(k): str(v) for k, v in (index.get('notices') or {}).items() if v}
    old, files = known or {}, {}
    for sha in set(notices.values()) | {str(s) for s in index.get('files') or [] if s}:
        if sha in old:  # a file is named by its PDF's checksum: one already read has not changed
            files[sha] = old[sha]
            continue
        try:
            data = json.loads((where / f'{sha}.json').read_text(encoding='utf-8'))
            if not isinstance(data.get('tables'), list):
                raise ValueError('no tables')
        except (OSError, ValueError, AttributeError) as e:
            logger.warning('SŽ timetables: %s.json left out: %r', sha, e)
            continue
        files[sha] = data
    return Timetables({n: s for n, s in notices.items() if s in files}, files, index.get('updated'))


# ---------------------------------------------------------------- days

def _easter(year: int) -> date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


# Slovenia's work-free public holidays ("prazniki", dela prosti dnevi): fixed days, plus Easter Monday
# (Easter and Whit Sunday fall on a Sunday anyway).
FIXED_HOLIDAYS = {(1, 1), (1, 2), (2, 8), (4, 27), (5, 1), (5, 2), (6, 25), (8, 15), (10, 31), (11, 1), (12, 25), (12, 26)}


def holiday(day: date) -> bool:
    easter = _easter(day.year)
    return (day.month, day.day) in FIXED_HOLIDAYS or day in (easter, easter + timedelta(days=1), easter + timedelta(days=49))


def _weekend(day: date) -> bool:
    return day.weekday() >= 5 or holiday(day)


# What a footnote's rule allows ("2 - Ne vozi ob sobotah, nedeljah in praznikih" is "workdays").
RULES = {
    'workdays': lambda day, note: not _weekend(day),
    'weekends_holidays': lambda day, note: _weekend(day),
    'not_saturday': lambda day, note: day.weekday() != 5,
    'sundays': lambda day, note: day.weekday() == 6,
    'info': lambda day, note: True,  # "1 - Prevoz se opravi preko mejnega prehoda Sočerga": says how, not when
    # "98 - dne 19.10. se nadomestni prevoz NE opravlja; VOZI VLAK!": that day the train runs instead.
    'train_runs_on': lambda day, note: day.isoformat() not in (note.get('dates') or []),
}
WORKDAYS_ONLY = re.compile(r'^\*\s*vozi le ob delovnikih')  # the legend of a starred extra bus ("BUS*")


def valid_on(data: dict, day: date) -> bool:
    valid = data.get('valid') or {}
    if valid.get('dates'):
        return day.isoformat() in valid['dates']
    start, end = valid.get('from'), valid.get('to')
    return bool(start and end) and start <= day.isoformat() <= end


def _star_means_workdays(data: dict) -> bool:
    return any(WORKDAYS_ONLY.match(fold(n).strip()) for n in data.get('notes') or [])


def unusable(data: dict, col: dict) -> Optional[str]:
    """Why a column cannot be used (problems the reader found, a footnote it could not read), or None."""
    if data.get('status') not in ('ok', 'unsure'):
        return f'timetable {data.get("status")}'
    if col.get('problems'):
        return '; '.join(map(str, col['problems']))
    if len(col.get('calls') or []) < 2:
        return 'fewer than two calls'
    for key in col.get('footnotes') or []:
        note = (data.get('footnotes') or {}).get(str(key))
        if not note:
            return f'footnote {key} undefined'
        if note.get('rule') not in RULES:
            return f'footnote {key} not understood ({note.get("rule")!r}: {note.get("text")!r})'
    if col.get('mark') and not _star_explained(data, col):
        return f'mark {col["mark"]!r} not understood'
    return None


def _star_explained(data: dict, col: dict) -> bool:
    """A starred bus ("BUS*"): its own footnote "*", or the legend's "*Vozi le ob delovnikih"."""
    return col.get('mark') == '*' and ('*' in (col.get('footnotes') or []) or _star_means_workdays(data))


def runs_on(data: dict, col: dict, day: date) -> bool:
    """Whether the column's bus runs on service day `day`: in the validity, on every footnote's days."""
    if not valid_on(data, day):
        return False
    notes = data.get('footnotes') or {}
    for key in col.get('footnotes') or []:
        note = notes.get(str(key)) or {}
        allows = RULES.get(note.get('rule'))
        if not allows or not allows(day, note):
            return False
    if col.get('mark') == '*' and '*' not in (col.get('footnotes') or []) and _weekend(day):
        return False
    return True


def numbers(col: dict) -> list[str]:
    """The train numbers a column can stand for, most likely first: the printed number, and where SŽ printed
    the bus's own five-digit number (Ljubljana - Logatec: "26729") the train numbers it is made from (2672)."""
    from .replacement import train_numbers
    printed = re.sub(r'\D', '', str(col.get('train') or ''))
    if not printed:
        return []
    return [printed] + (train_numbers(printed) if len(printed) >= 5 else [])


# ---------------------------------------------------------------- stations

NEAR_LINE = 1500  # m: a stop that is no railway station lies this close to the line between the bus's stations
BESIDE = 300      # m: the feed stop this close to the spot SŽ lists is where the bus stops
# Stations abroad, which no feed has: the bus ends or starts at its last stop in Slovenia.
FOREIGN = {'beljak', 'villach', 'opcine', 'villa opicina', 'trst', 'trieste', 'buzet', 'cakovec', 'durmanec', 'pliberk', 'bleiburg',
           'spilje', 'spielfeld', 'spielfeld strass', 'zagreb', 'rijeka', 'gradec', 'graz'}


def words(name: str) -> str:
    """'LESCE BLED' -> 'lesce bled', 'Ljubljana Dolgi most(Železniški)' -> 'ljubljana dolgi most'."""
    return ' '.join(re.findall(r'[a-z0-9]+', fold((name or '').split('(')[0])))


def _as_stop(s: dict, **extra) -> dict:
    return {'gtfsId': s['id'], 'name': s['name'], 'lat': s['latitude'], 'lon': s['longitude'], **extra}


class Stations:
    """Maps a timetable's printed station names onto feed stops. Railway stations by name ('LESCE BLED' is
    'Lesce-Bled', 'B. Bistrica' is 'Bohinjska Bistrica'); a stop that is no railway station, in order of
    trust: a hand-checked replacement stop (stop_overrides.csv) of a feed stop so named, SŽ's own list of
    replacement stops (szstops.py), the bus stop the timetable's stop list names ("AP mestnega prometa
    Litostrojska"), a bus stop of that name; each within NEAR_LINE of the line between the bus's stations.
    `stops`: the stop index's stops (sources.stops 'all')."""

    def __init__(self, stops: list[dict], sz_rows: Optional[list[dict]] = None, replacement_overrides: Optional[dict] = None):
        self.rail = [s for s in stops if 'rail' in (s.get('modes') or [])]
        self.other = [s for s in stops if any(m != 'rail' for m in s.get('modes') or [])]
        self._sz_rows, self._overrides = sz_rows, replacement_overrides
        self._rail_memo: dict[str, list[dict]] = {}

    @property
    def sz_rows(self) -> list[dict]:
        if self._sz_rows is None:
            from . import szstops
            return szstops.rows()
        return self._sz_rows

    @property
    def overrides(self) -> dict:
        if self._overrides is None:
            from . import stopfix
            return stopfix.tables()[0]['replacement']
        return self._overrides

    def railway(self, name: str) -> list[dict]:
        if name not in self._rail_memo:
            from .closures import names_match
            self._rail_memo[name] = [s for s in self.rail if names_match(name, s['name'])]
        return self._rail_memo[name]

    def resolve(self, data: dict, col: dict) -> tuple[Optional[list[dict]], Optional[str]]:
        """The column's calls in Slovenia, each with its `stop` (a feed stop: gtfsId, name, lat, lon, and for a
        stop that is no railway station where the bus stops, `replacementLabel`), or (None, why not)."""
        calls = [{**c, '_found': self.railway(c.get('station') or '')} for c in col.get('calls') or []]
        calls = [c for c in calls if c['_found'] or not abroad(c.get('station') or '', data)]
        for c in calls:
            if len(c['_found']) == 1:
                c['stop'] = _as_stop(c['_found'][0])
        for c in calls:  # a name several stations share: the one nearest the others
            if len(c['_found']) > 1:
                known = [[k['stop']['lon'], k['stop']['lat']] for k in calls if k.get('stop')]
                c['stop'] = _as_stop(min(c['_found'], key=lambda s: min((geometry.distance(p, [s['longitude'], s['latitude']]) for p in known),
                                                                           default=0)))
        for i, c in enumerate(calls):
            if not c.get('stop'):
                line = [k['stop'] for k in calls[:i] if k.get('stop')][-1:] + [k['stop'] for k in calls[i + 1:] if k.get('stop')][:1]
                c['stop'] = self.elsewhere(c.get('station') or '', data, line)
                if not c['stop']:
                    return None, f'stop {c.get("station")!r} not found'
        if len(calls) < 2:
            return None, 'fewer than two calls in Slovenia'
        out = [{k: v for k, v in c.items() if k in ('station', 'stop', 'arr', 'dep')} for c in calls]
        first, last = out[0], out[-1]
        first.setdefault('dep', first.get('arr'))
        first.pop('arr', None)
        last.setdefault('arr', last.get('dep'))
        last.pop('dep', None)
        return out, None

    def elsewhere(self, name: str, data: dict, line: list[dict]) -> Optional[dict]:
        """A stop that is no railway station (see the class notes), or None."""
        from .closures import names_match
        from .szstops import APPROXIMATE, same_station
        pts = [[s['lon'], s['lat']] for s in line]
        if not pts:
            return None

        def off(lat: float, lon: float) -> float:
            if len(pts) == 1:
                return geometry.distance(pts[0], [lon, lat])
            return geometry.project_stops(pts, [{'lat': lat, 'lon': lon}])[0][1]
        named = [s for s in self.other if names_match(name, s['name'])]
        for s in named:
            for r in self.overrides.get(s['id']) or []:
                if off(r['lat'], r['lon']) <= NEAR_LINE:
                    return _as_stop(s, lat=r['lat'], lon=r['lon'], replacementLabel=r.get('label') or '')
        listed = sorted(((off(r['lat'], r['lon']), n, r) for n, r in enumerate(self.sz_rows) if same_station(r['station'], name)),
                        key=lambda x: x[:2])
        if listed and listed[0][0] <= NEAR_LINE:
            r = listed[0][2]
            here = [r['lon'], r['lat']]
            beside = min(self.other, key=lambda s: geometry.distance(here, [s['longitude'], s['latitude']]), default=None)
            if beside and geometry.distance(here, [beside['longitude'], beside['latitude']]) <= BESIDE:
                return _as_stop(beside, lat=r['lat'], lon=r['lon'], replacementLabel=r.get('label') or '',
                                unverified=r.get('source') in APPROXIMATE)
        lats, lons = [p[1] for p in pts], [p[0] for p in pts]
        box = [s for s in self.other if min(lats) - 0.02 < s['latitude'] < max(lats) + 0.02 and min(lons) - 0.03 < s['longitude'] < max(lons) + 0.03]
        near = [s for s in box if off(s['latitude'], s['longitude']) <= NEAR_LINE]
        text = next((st.get('text') or '' for st in data.get('stops') or [] if words(st.get('station')) == words(name)), '')
        said = f' {words(text)} '
        spoken = [s for s in near if words(s['name']) and f' {words(s["name"])} ' in said]
        if spoken:
            best = max(spoken, key=lambda s: (len(words(s['name'])), -off(s['latitude'], s['longitude'])))
            return _as_stop(best, replacementLabel=text)
        alike = [s for s in near if any(s is n for n in named)]
        if alike:
            best = min(alike, key=lambda s: (words(s['name']) != words(name), off(s['latitude'], s['longitude'])))
            return _as_stop(best, **({'replacementLabel': text} if text else {}))
        return None


def abroad(name: str, data: dict) -> bool:
    """A station outside Slovenia: a known one (Beljak/Villach, Opčine, Buzet, ...), or one the title or a table
    marks with its country ("Sežana - Opčine (I)")."""
    w = words(name)
    if not w:
        return False
    if w in FOREIGN:
        return True
    said = ' '.join(fold(t) for t in [data.get('title') or ''] + [t.get('direction') or '' for t in data.get('tables') or []])
    return bool(re.search(rf'\b{re.escape(w)}\b[^-()]*\((?:a|i|hr)\)', said))
