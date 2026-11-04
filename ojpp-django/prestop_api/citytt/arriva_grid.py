"""Arriva's Piran city-line timetables: grids saved as PDF with a text layer, one column per bus run.

    Linija 1.1.1 Piran AP-Beli Križ-Lucija AP-…              (1.1.1: a page holds two grids, out and back)
    Avtobusna  D*    D*    PESO   …                           day code of each run
    postajališča 1   2     3      …                           run number (printed out of order sometimes)
    Piran            05:30 06:00  …
    Lucija AP                                                 (twice: arrival row, departure row)
    TC Tuš     06:19 Krka  06:50  …                           "Krka": this bus goes on as line 1.1.2

Line 1.1.2 prints its run numbers ("postaje 1 2 …") above the codes, a stray stop number after each name and "-" for
no call. Columns come from the x positions of the run numbers, never from their values, and a time goes to the column
nearest it: a stop a run skips has an empty cell, a time between two columns (a column with a code but no number,
printed with made-up times 00:01…) is dropped and noted. The Saturday file prints its row names on page 1 only: the
next pages' rows are matched to them by height. A grid goes on over pages; a page with no grid is skipped.

Per run: a call at the same minute as the one before is the bypass by Beli Križ (the bus passes Pirat … Portorož H
without stopping) and is dropped, the first of the group stays; a time more than 60 minutes from its neighbours is a
stray cell and is dropped; "Lucija AP" printed twice is one stop (departure time, else arrival). `parse` returns one
table per (line, direction, service); `combine` then joins the two files' copies of the same bus.
"""
import re
import statistics

import pdfplumber

from .arriva import ReadError, _lines, _text

TITLE = re.compile(r'^(?:Linija|Line)\s+(\d+(?:\.\d+)+)\s+(.+)$', re.I)
CLOCK = r'(?:[01]?\d|2[0-4]):[0-5]\d'
TIMES = re.compile(rf'^(?:{CLOCK})+$')  # several run together: "23:500:15"
ONE = re.compile(CLOCK)
CODE = re.compile(r'^\*{0,2}[A-Z]{1,5}\*{0,2}$')
LABELS = {'Avtobusna', 'postajališča', 'postaje', 'BUS', 'STOP'}   # the row names' heading, not codes
FOOTER = ('Opomba', 'Remarks', 'Vozni')
DASH = {'-', '–', '—'}
HEADER_GAP = 16   # pt: the codes row is at most this far from the run numbers
MAX_JUMP = 60     # minutes between two calls of a run; more is a stray cell
SAME_ROW = 3.5    # pt: a row of a page without names is the named row this close to its height
KRKA = 'Krka'

# Day code -> service (declared on the City). None: runs only 25 Jun - 31 Aug, outside the timetable's window.
SERVICES = {'D*': 'D', 'PESO': 'FRI', 'SO': 'SO', 'NP': 'NP', 'NP**': 'NP', '**NP': None, 'V': 'V', '**V': None, 'SONP': 'SONP'}
REQUIRED = {'1.1.1': ('D', 'SO', 'NP'), '1.1.2': ('V',)}   # a file that vanished from the page must not pass silently
KRKA_LINE = '1.1.2'


def parse(path) -> list[dict]:
    """[{'line', 'title', 'stops', 'runs': [[time or None per stop] per run], 'direction': 0|1, 'service', 'notes': [text],
    'krka': [bool per run]}] one per (line, direction, service)."""
    with pdfplumber.open(path) as pdf:
        return read([p.extract_words() for p in pdf.pages])


def _numbers(line: list[dict]) -> bool:
    ints = [w for w in line if w['text'].isdigit()]
    return len(ints) >= 3 and all(w['text'] in LABELS for w in line if not w['text'].isdigit())


def _codes(line: list[dict]) -> bool:
    codes = [w for w in line if CODE.match(w['text']) and w['text'] not in LABELS]
    return bool(codes) and all(w['text'] in LABELS for w in line if w not in codes)


def _centre(w: dict) -> float:
    return (w['x0'] + w['x1']) / 2


def _blocks(lines: list[list[dict]]) -> list[dict]:
    """The page's grids: the run numbers and day codes (above or below them), the lines of their rows."""
    heads = []
    for i, line in enumerate(lines):
        if _numbers(line):
            near = [j for j in range(max(0, i - 3), min(len(lines), i + 4))
                    if j != i and _codes(lines[j]) and abs(lines[j][0]['top'] - line[0]['top']) <= HEADER_GAP]
            if not near:
                raise ReadError(f'run numbers without day codes: {_text(line)!r}')
            j = min(near, key=lambda j: abs(lines[j][0]['top'] - line[0]['top']))
            heads.append((i, j, min(i, j), max(i, j)))
    out = []
    for n, (i, j, first, last) in enumerate(heads):
        end = heads[n + 1][2] if n + 1 < len(heads) else len(lines)
        rows = []
        for line in lines[last + 1:end]:
            text = _text(line)
            if text.startswith(FOOTER) or (CODE.match(line[0]['text']) and len(line) > 1 and line[1]['text'] in DASH):
                break
            if rows and line[0]['top'] - rows[-1][0]['top'] > 1.5 * (statistics.median(b[0]['top'] - a[0]['top'] for a, b in zip(rows, rows[1:])) if len(rows) > 1 else 14):
                break
            rows.append(line)
        out.append({'numbers': lines[i], 'codes': lines[j], 'rows': rows})
    return out


def _clock(text: str) -> str:
    h, m = text.split(':')
    return f'{int(h):02d}:{m}'


def _row(line: list[dict], cols: list[float], pitch: float, page: int) -> dict:
    """{'label', 'top', 'times': {column: 'HH:MM'}, 'krka': {column}, 'orphans': [(centre, 'HH:MM')]}."""
    left = cols[0] - pitch / 2
    row = {'label': [], 'top': line[0]['top'], 'times': {}, 'krka': set(), 'orphans': []}
    near = lambda c: min(range(len(cols)), key=lambda j: abs(cols[j] - c))  # noqa: E731
    for w in line:
        text = w['text']
        if TIMES.match(text):
            found = [m for m in ONE.finditer(text)]
            if ''.join(m.group() for m in found) != text:
                raise ReadError(f'page {page}: cannot split the times in {text!r}')
            for m in found:  # run together: each time's place is by its characters
                c = w['x0'] + (w['x1'] - w['x0']) * (m.start() + m.end()) / (2 * len(text))
                j = near(c)
                if abs(cols[j] - c) > pitch / 2:
                    row['orphans'].append((c, _clock(m.group())))
                elif j in row['times']:
                    raise ReadError(f'page {page}: two times in one cell near {text!r}')
                else:
                    row['times'][j] = _clock(m.group())
        elif text in DASH:
            continue
        elif _centre(w) < left:
            if not text.isdigit():  # 1.1.2 prints a stop number after the name
                row['label'].append(text)
        elif text == KRKA and abs(cols[near(_centre(w))] - _centre(w)) <= pitch * 0.6:
            row['krka'].add(near(_centre(w)))
        else:
            raise ReadError(f'page {page}: unexpected {text!r} among the times')
    row['label'] = re.sub(r'\s+', ' ', ' '.join(row['label'])).strip()
    return row


class _Grid:
    def __init__(self, line: str, title: str, direction: int):
        self.line, self.title, self.direction = line, title, direction
        self.labels: list[str] = []   # the named rows, in order
        self.tops: list[float] = []   # each row's height under the run numbers
        self.columns: list[dict] = []
        self.notes: list[str] = []


def read(pages: list[list[dict]]) -> list[dict]:
    """The tables of a file from each page's words ({'text', 'x0', 'x1', 'top'}), as `parse` returns them."""
    grids: list[_Grid] = []
    slots: dict[int, _Grid] = {}   # the grid each position on a page last continued
    line = title = None
    for p, words in enumerate(pages, start=1):
        lines = _lines(words)
        titled = [(i, TITLE.match(_text(w))) for i, w in enumerate(lines) if TITLE.match(_text(w))]
        blocks = _blocks(lines)
        if not blocks:
            if any(TIMES.match(w['text']) for w in words):
                raise ReadError(f'page {p}: times but no run numbers and day codes')
            continue
        if titled:
            first, found = titled[0]
            line = found.group(1)
            extra = [_text(w) for w in lines[first + 1:] if w[0]['top'] < blocks[0]['numbers'][0]['top'] - 1 and not _numbers(w) and not _codes(w)
                     and not all(x['text'] in LABELS for x in w) and not re.search(r'obratuje|operating', _text(w))]
            title = ' / '.join([found.group(2).strip()] + extra)
        if line is None:
            raise ReadError(f'page {p}: no "Linija …" title')
        for slot, block in enumerate(blocks):
            numbers = block['numbers']
            ints = sorted((w for w in numbers if w['text'].isdigit()), key=lambda w: w['x0'])
            cols = [_centre(w) for w in ints]
            pitch = statistics.median(b - a for a, b in zip(cols, cols[1:])) if len(cols) > 1 else 30
            codes = [None] * len(cols)
            orphan_codes = []
            for w in block['codes']:
                if w['text'] in LABELS:
                    continue
                j = min(range(len(cols)), key=lambda j: abs(cols[j] - _centre(w)))
                if abs(cols[j] - _centre(w)) > pitch / 2:
                    orphan_codes.append(w['text'])
                elif codes[j] is not None:
                    raise ReadError(f'page {p}: two day codes over run number {ints[j]["text"]}')
                else:
                    codes[j] = w['text']
            if None in codes:
                raise ReadError(f'page {p}: a run number without a day code')
            rows = [_row(r, cols, pitch, p) for r in block['rows']]
            top0 = numbers[0]['top']

            def rows_of(g):  # the rows of a grid these are, by height, or None when a name differs
                got = []
                for r in rows:
                    k = min(range(len(g.tops)), key=lambda k: abs(g.tops[k] - (r['top'] - top0)))
                    if abs(g.tops[k] - (r['top'] - top0)) > SAME_ROW or k in got or (r['label'] and r['label'].casefold() != g.labels[k].casefold()):
                        return None
                    got.append(k)
                return got

            grid = index = None
            for g in ([slots[slot]] if slot in slots and not any(r['label'] for r in rows) else [g for g in grids if g.line == line]):
                index = rows_of(g)
                if index is not None:
                    grid = g
                    break
            if grid is None:
                if not all(r['label'] for r in rows):
                    raise ReadError(f'page {p}: rows without names that match no grid of line {line}')
                if sum(1 for g in grids if g.line == line) >= 2:
                    raise ReadError(f'page {p}: a third grid of line {line}')
                grid = _Grid(line, title, sum(1 for g in grids if g.line == line))
                grid.labels, grid.tops = [r['label'] for r in rows], [r['top'] - top0 for r in rows]
                grids.append(grid)
                index = list(range(len(rows)))
            slots[slot] = grid
            for j, code in enumerate(codes):
                cells = {index[k]: t for k, r in enumerate(rows) for c, t in r['times'].items() if c == j}
                krka = any(j in r['krka'] for r in rows)
                grid.columns.append({'code': code, 'cells': cells, 'krka': krka, 'number': ints[j]['text'], 'page': p})
            orphans = sorted((c, t) for r in rows for c, t in r['orphans'])
            if orphans:
                grid.notes.append(f'page {p}: a column with no run number{" (code " + ", ".join(orphan_codes) + ")" if orphan_codes else ""} '
                                  f'and {len(orphans)} times ({orphans[0][1]}…) left out')
    if not grids:
        raise ReadError('no timetable grid in the file')
    return [t for g in grids for t in _tables(g)]


def _tables(grid: _Grid) -> list[dict]:
    groups: list[tuple[str, list[int]]] = []   # (stop name, its rows): a name printed twice in a row is one stop
    for i, label in enumerate(grid.labels):
        if groups and groups[-1][0].casefold() == label.casefold():
            groups[-1][1].append(i)
        else:
            groups.append((label, [i]))
    stops = [name for name, _ in groups]
    by_service: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    for col in grid.columns:
        if col['code'] not in SERVICES:
            raise ReadError(f'line {grid.line}: unknown day code {col["code"]!r} over run {col["number"]} (page {col["page"]}): '
                            f'look at the timetable and add it to SERVICES')
        service = SERVICES[col['code']]
        if service is None:
            skipped[col['code']] = skipped.get(col['code'], 0) + 1
            continue
        run = [next((v for v in (col['cells'].get(i) for i in reversed(rows)) if v), None) for _, rows in groups]
        if not any(run):
            continue
        table = by_service.setdefault(service, {'line': grid.line, 'title': grid.title, 'stops': stops, 'runs': [], 'direction': grid.direction,
                                                'service': service, 'notes': [] if by_service else list(grid.notes), 'krka': []})
        run = _strays(run, stops, table['notes'], f'page {col["page"]} run {col["number"]}')
        table['runs'].append(run)
        table['krka'].append(col['krka'])
    for table in by_service.values():
        done = [_detour(r) for r in table['runs']]
        table['runs'] = [r for r, _ in done]
        if any(d for _, d in done):
            per = {}
            for _, d in done:
                for i in d:
                    per[stops[i]] = per.get(stops[i], 0) + 1
            table['notes'].append(f'{sum(per.values())} calls at the same minute as the call before dropped in {sum(1 for _, d in done if d)} runs: '
                                  + ', '.join(f'{n} {k}' for k, n in per.items()))
    for code, n in skipped.items():
        for table in by_service.values():
            table['notes'].append(f'{n} runs coded {code} (summer only) left out')
            break
    return list(by_service.values())


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def _jump(a: str, b: str) -> int:
    """Minutes from a to b round the clock: 23:59 -> 00:02 is 3, going back is nearly 1440."""
    return (_minutes(b) - _minutes(a)) % 1440


def _strays(run: list, stops: list[str], notes: list[str], where: str) -> list:
    """The run without the one cell that breaks it: a time more than MAX_JUMP minutes after the call before (a stray
    00:02 at the last stop) or before it (Lucija Š two minutes before the stop it follows). No single cell to blame: error."""
    run = list(run)
    calls = [i for i, v in enumerate(run) if v]
    ok = lambda ids: all(_jump(run[a], run[b]) <= MAX_JUMP for a, b in zip(ids, ids[1:]))  # noqa: E731
    if ok(calls):
        return run
    culprits = [c for c in calls if ok([i for i in calls if i != c])]
    if len(culprits) != 1:
        raise ReadError(f'{where}: cannot tell which time is wrong: {[(stops[i], run[i]) for i in calls]}')
    notes.append(f'{where}: {run[culprits[0]]} at {stops[culprits[0]]} dropped, it does not follow the calls around it '
                 f'(more than {MAX_JUMP} minutes off, or before the call before)')
    run[culprits[0]] = None
    return run


def _detour(run: list) -> tuple[list, list[int]]:
    """The run without calls at the same minute as the call before (the bypass by Beli Križ: the bus passes them without
    stopping), and the indexes dropped."""
    out, last, dropped = list(run), None, []
    for i, v in enumerate(run):
        if not v:
            continue
        if v == last:
            out[i] = None
            dropped.append(i)
        else:
            last = v
    return out, dropped


# ---------------------------------------------------------------- one bus printed in two files

def _days(city, service: str) -> frozenset:
    """The (weekday, public holiday) pairs a City's service runs on."""
    for sid, weekdays, holidays in city.services:
        if sid == service:
            return frozenset((w, False) for w in range(7) if weekdays[w]) | frozenset((w, True) for w in range(7) if holidays)
    raise ReadError(f'service {service!r} is not declared for {city.name}')


def _calls(table: dict, run: list) -> list[tuple[str, str]]:
    return [(table['stops'][i].casefold(), v) for i, v in enumerate(run) if v]


def _label(table: dict, k: int) -> str:
    run = table['runs'][k]
    first = next(i for i, v in enumerate(run) if v)
    return f'{table["line"]} {"out" if table["direction"] == 0 else "back"} {table["service"]} {table["stops"][first]} {run[first]}'


def combine(tables: list[dict], city) -> tuple[list[dict], list[str]]:
    """Line 1.1.1's run marked "Krka" is the same bus as the 1.1.2 run that calls at its first stop at its first time
    (and agrees on every stop they share): the 1.1.2 trip stays, the 1.1.1 trip goes for the days they overlap. A
    marked run no 1.1.2 run matches stays. An unmarked run printed beside the marked one with the same times as the
    1.1.2 run that took it is that bus again (Saturday and Sunday print Piran 06:15 and 09:00 twice) and goes too.
    Returns the tables and the notes (merged, twice, unmatched, and the pairs left for a person to decide: same times
    Piran - Lucija AP, no marker)."""
    for line, services in REQUIRED.items():
        for direction in (0, 1):
            have = {t['service'] for t in tables if t['line'] == line and t['direction'] == direction}
            if not set(services) <= have:
                raise ReadError(f'line {line} has no timetable for {", ".join(sorted(set(services) - have))} ({"out" if direction == 0 else "back"}): '
                                f'a file may be missing from the page')
    notes: list[str] = []
    long = [t for t in tables if t['line'] == KRKA_LINE]
    moved: list[tuple[dict, list, bool, str]] = []
    taken: set[tuple[int, int, int]] = set()  # (1.1.2 table, its run, the 1.1.1 table whose marked run it took)
    for t in [t for t in tables if t['line'] != KRKA_LINE]:
        keep_runs, keep_krka = [], []
        for k, run in enumerate(t['runs']):
            if not t['krka'][k]:
                keep_runs.append(run)
                keep_krka.append(False)
                continue
            calls = _calls(t, run)
            days, left = _days(city, t['service']), _days(city, t['service'])
            hits = []
            for u in long:
                if u['direction'] != t['direction'] or not _days(city, u['service']) & days:
                    continue
                for m, other in enumerate(u['runs']):
                    theirs = dict(_calls(u, other))
                    if calls[0][1] == theirs.get(calls[0][0]) and all(theirs[n] == v for n, v in calls if n in theirs):
                        hits.append(f'{_label(u, m)} (service {u["service"]})')
                        taken.add((id(u), m, id(t)))
                        left = left - _days(city, u['service'])
            if not hits:
                notes.append(f'UNMATCHED: {_label(t, k)} is marked Krka and no 1.1.2 run matches: kept')
                keep_runs.append(run)
                keep_krka.append(True)
                continue
            if left:
                service = next((sid for sid, _, _ in city.services if _days(city, sid) == left), None)
                if service is None:
                    raise ReadError(f'{_label(t, k)} is on {t["service"]} and the 1.1.2 run covers only part of it: no service for the rest')
                moved.append((t, run, True, service))
            notes.append(f'MERGED: {_label(t, k)} = {" + ".join(hits)}' + (f'; kept on {service}' if left else '; dropped'))
        t['runs'], t['krka'] = keep_runs, keep_krka
    for t, run, krka, service in moved:
        other = next((x for x in tables if (x['line'], x['direction'], x['service']) == (t['line'], t['direction'], service)), None)
        if other is None:
            other = {**t, 'service': service, 'runs': [], 'krka': [], 'notes': []}
            tables.append(other)
        other['runs'].append(run)
        other['krka'].append(krka)
    for t in tables:
        if t['line'] == KRKA_LINE:
            continue
        twice: set[int] = set()
        for k, run in enumerate(t['runs']):
            if t['krka'][k]:
                continue
            ends = ('piran', 'lucija ap') if t['direction'] == 0 else ('lucija ap', 'piran')
            mine = dict(_calls(t, run))
            if not all(e in mine for e in ends):
                continue
            for u in long:
                if u['direction'] != t['direction'] or not _days(city, u['service']) & _days(city, t['service']):
                    continue
                for m, other in enumerate(u['runs']):
                    theirs = dict(_calls(u, other))
                    if all(e in theirs for e in ends) and all(theirs[n] == v for n, v in mine.items() if n in theirs and _between(t, n, ends)):
                        if (id(u), m, id(t)) in taken:
                            twice.add(k)
                            notes.append(f'TWICE: {_label(t, k)} is {_label(u, m)} printed again beside its Krka run: dropped')
                        else:
                            notes.append(f'DECIDE: {_label(t, k)} and {_label(u, m)} have the same times {ends[0]} - {ends[1]}, no marker: both kept')
        if twice:
            t['runs'] = [r for k, r in enumerate(t['runs']) if k not in twice]
            t['krka'] = [x for k, x in enumerate(t['krka']) if k not in twice]
    return tables, notes


def _between(table: dict, name: str, ends: tuple) -> bool:
    names = [s.casefold() for s in table['stops']]
    return names.index(ends[0]) <= names.index(name) <= names.index(ends[1])
