"""Arriva's Koper city-line timetables: grids saved as PDF with a text layer, one column per bus run.

    Line 9 Koper AP-Potniški terminal-Koper AP   Valid 18.11.2022   Remarks: …
    D       D       D   …                      day code of each run (line 9 prints them on the header row itself)
    BUS STOPS     Km
                  1       2       3   …        run number
    Koper    0,0  05:20   05:35   05:50 …      one row per stop: km, then one time per run, empty where it skips
    Prisoje  4,9  05:38   A       06:08 …      "2" above "A" down a column: that run is line 2A (line 2's file prints them)

A page holds one or two tables, each starting at its "BUS STOPS" header; a table with the stops of an earlier one goes
on with it (later pages, or line 9's second half of the day), another stop list is the other direction. Columns come
from the x of the run numbers and every time goes to the nearest one. A time must sit on a stop's row: some Koper pages
print their last columns half a row up (docs/research/2026-11-04-city-timetables.md), and such a page fails rather
than be read one row off. `parse` returns one table per (line, direction, service), as arriva_grid does.
"""
import re

import pdfplumber

from .arriva import _lines, _text

TITLE = re.compile(r'^Line\s+(\w+):?\s+(.+)$', re.I)
CLOCK = re.compile(r'^([01]?\d|2[0-4]):[0-5]\d$')
NUMBER = re.compile(r'^\d{1,3}$')
KM = re.compile(r'^\d{1,2},\d$')
CODE = re.compile(r'^\*{0,2}[A-Z]{1,5}\*{0,2}$')
TITLE_END = {'Valid', 'Valid:', 'Remarks:'}   # the title line also holds the validity and remarks, further right
SERVICES = {'D': 'D', 'D*': 'D'}   # working days; other codes are other files (Saturday, Sunday) and fail here
HEADER_GAP = 20   # pt: the run numbers and the Km heading are at most this far below the "BUS STOPS" heading
CODES_GAP = 16    # pt: the day codes are at most this far above the run numbers
COLUMN = 12       # pt: a time this far from every run number's centre belongs to no column


def parse(path) -> list[dict]:
    """[{'line', 'title', 'stops', 'runs': [[time or None per stop] per run], 'direction': 0|1, 'service'}] one per
    (line, direction, service)."""
    with pdfplumber.open(path) as pdf:
        return read([p.extract_words() for p in pdf.pages])


def _centre(w: dict) -> float:
    return (w['x0'] + w['x1']) / 2


def _title(lines: list[list[dict]]) -> tuple[str, str]:
    for line in lines:
        words = []
        for w in line:
            if w['text'] in TITLE_END:
                break
            words.append(w)
        m = TITLE.match(_text(words))
        if m:
            return m.group(1), m.group(2).strip()
    raise ValueError('no "Line N" title')


def _table(lines: list[list[dict]], at: int, page: int) -> tuple[dict, int]:
    """The table whose "BUS STOPS" heading is lines[at]: its stops, the runs' columns and codes; and the index of the
    first line after it."""
    head = lines[at]
    km = next((w for line in lines[at:at + 3] for w in line if w['text'] == 'Km' and w['top'] - head[0]['top'] <= HEADER_GAP), None)
    if km is None:
        raise ValueError(f'page {page}: no "Km" heading by "BUS STOPS"')
    numbers = next((line for line in lines[at:at + 3] if line[0]['top'] - head[0]['top'] <= HEADER_GAP
                    and [w for w in line if w['x0'] > km['x1']] and all(NUMBER.match(w['text']) for w in line if w['x0'] > km['x1'])), None)
    if numbers is None:
        raise ValueError(f'page {page}: no run numbers under "BUS STOPS"')
    cols = [_centre(w) for w in numbers if w['x0'] > km['x1']]
    top = numbers[0]['top']
    codes: list = [None] * len(cols)
    for line in lines[max(0, at - 1):at + 3]:
        for w in line:
            if w['x0'] > km['x1'] and CODE.match(w['text']) and 0 < top - w['top'] <= CODES_GAP:
                i = min(range(len(cols)), key=lambda c: abs(cols[c] - _centre(w)))
                codes[i] = w['text']
    if None in codes:
        raise ValueError(f'page {page}: run {codes.index(None) + 1} has no day code')
    unknown = sorted({c for c in codes if c not in SERVICES})
    if unknown:
        raise ValueError(f'page {page}: day codes {", ".join(unknown)} (only working days are read)')
    stops, cells, marks = [], [], [[] for _ in cols]
    i = lines.index(numbers) + 1
    while i < len(lines) and not any(w['text'] == 'BUS' for w in lines[i]):
        line = lines[i]
        name = _text([w for w in line if w['x1'] <= km['x1'] and not KM.match(w['text'])])
        times = [w for w in line if w['x0'] > km['x1'] and CLOCK.match(w['text'])]
        if times and not name:
            raise ValueError(f'page {page}: times at height {line[0]["top"]:.0f} on no stop\'s row ({_text(times)})')
        if name and times:
            row: list = [None] * len(cols)
            for w in line:
                if w['x0'] <= km['x1'] or KM.match(w['text']):
                    continue
                c = min(range(len(cols)), key=lambda c: abs(cols[c] - _centre(w)))
                if abs(cols[c] - _centre(w)) > COLUMN:
                    raise ValueError(f'page {page}, {name}: "{w["text"]}" in no run\'s column')
                if CLOCK.match(w['text']):
                    row[c] = w['text'].zfill(5)
                else:
                    marks[c].append(w['text'])
            stops.append(name)
            cells.append(row)
        i += 1
    if len(stops) < 2:
        raise ValueError(f'page {page}: a table with {len(stops)} stops')
    runs = [[cells[r][c] for r in range(len(stops))] for c in range(len(cols))]
    return {'stops': stops, 'runs': runs, 'codes': codes, 'marks': [' '.join(m) for m in marks]}, i


def read(pages: list[list[dict]]) -> list[dict]:
    line, title = None, None
    grids: list[dict] = []   # per distinct stop list, in reading order: direction = its index
    for n, words in enumerate(pages, 1):
        lines = _lines(words)
        if not lines:
            continue
        number, name = _title(lines)
        if line is not None and number != line:
            raise ValueError(f'page {n}: line {number}, page 1 is line {line}')
        line, title = number, title or name
        at = 0
        while at < len(lines):
            if lines[at][0]['text'] == 'BUS':
                table, at = _table(lines, at, n)
                grid = next((g for g in grids if g['stops'] == table['stops']), None)
                if grid is None:
                    grid = {'stops': table['stops'], 'runs': []}
                    grids.append(grid)
                grid['runs'] += list(zip(table['runs'], table['codes'], table['marks']))
            else:
                at += 1
    if not grids:
        raise ValueError('no "BUS STOPS" table')
    if len(grids) > 2:
        raise ValueError(f'{len(grids)} different stop lists: a table was misread')
    tables: dict[tuple, dict] = {}
    for direction, grid in enumerate(grids):
        for run, code, mark in grid['runs']:
            # Line 2's file prints line 2A's runs between its own, marked "2" and "A" down the column.
            own = f'{line}A' if mark.split()[:2] == ['2', 'A'] and line == '2' else line
            key = (own, direction, SERVICES[code])
            t = tables.setdefault(key, {'line': own, 'title': title, 'stops': grid['stops'], 'runs': [],
                                        'direction': direction, 'service': SERVICES[code]})
            t['runs'].append(run)   # in print order, which is time order (compose reads a start that jumps back as after midnight)
    return list(tables.values())
