"""Postojna's city buses (Furman, run by Nomago): one poster PDF with a text layer, page 1 the map, page 2 the tables.

    [Proga 1]  Industrijska cona  10:38  14:37          [Šolska 1]  Zalog     7:02   [Šolska 4]  Raubarkomanda  7:32
               Kazarje            8:40 9:10 …                       Mercator  7:05               Javorniška pot 7:40
               Primorka      8:13 8:48 9:18 …                       …                            …
    [Proga 2]  Inkubator          8:15 8:55 …           [Šolska 2]  …                [Šolska Popoldanska 1,2] 13:27 13:49

Boxes stand in four bands across the page, each titled by a word turned on its side ("agorP" read upwards is "Proga")
with its number on top; "Delavska" is printed upright on a row of its own, after a gap. In a box every row is a stop
and every column a run; a run's columns come from the row printing the most times and each time goes to the nearest
one. Two calls more than GAP apart are two runs (Šolska Popoldanska 3 drops everyone at Zagon at 13.20 and runs
again from Primorka at 14.12). A row with no time inside a box is a stop served on request ("Raubarkomanda 1 Če je
potnik"): left out, with a note.

The legend under Proga 1 and 2 says when they run on Saturdays ("Ob sobotah vozi od 8¹³ do 12¹⁰", the minutes raised):
the runs lying wholly in that window are the Saturday service. `parse` returns one table per box and service: Proga
`D` (working days) and `SO` (Saturdays), Šolska `SOL` (school days), Delavska `D`. The lines keep the poster's titles;
the city's `line_ids` give them OTP's route ids.
"""
import re

import pdfplumber

CLOCK = re.compile(r'^([01]?\d|2[0-3])[:.]([0-5]\d)$')
NUMBER = re.compile(r'^\d(?:,\d)*$')
SATURDAY = re.compile(r'progi (\d+)\b.*?Ob sobotah vozi od (\d{1,2})(\d{2}) do (\d{1,2})(\d{2})')
PAGE = 1          # the tables' page
ROW = 4           # pt: words this close in `top` are one row
TITLE_ABOVE = 6   # pt: a box's first row may stand this far above its title's number
BAND = 3          # pt: sideways titles this close in x head one band
ROW_GAP = 16     # pt: an untimed row this far below the one before starts a box (a title printed upright)
GAP = 30          # min: calls further apart are two runs
SERVICES = {'Proga': 'D', 'Šolska': 'SOL', 'Delavska': 'D'}


def parse(path) -> list[dict]:
    with pdfplumber.open(path) as pdf:
        return read(pdf.pages[PAGE].extract_words())


def _rows(words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if rows and abs(rows[-1][0]['top'] - w['top']) <= ROW:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w['x0']) for r in rows]


def _titles(words: list[dict]) -> list[tuple[float, float, str]]:
    """(x, top, title) of each sideways title: its number on top, then its words, each read upwards."""
    side = sorted((w for w in words if not w.get('upright', True)), key=lambda w: (round(w['x0']), w['top']))
    groups: list[list[dict]] = []
    for w in side:
        if NUMBER.match(w['text'][::-1]) or not groups or abs(groups[-1][0]['x0'] - w['x0']) > 2:
            groups.append([w])
        else:
            groups[-1].append(w)
    out = []
    for g in groups:
        number, rest = g[0]['text'][::-1], [w['text'][::-1] for w in reversed(g[1:])]
        out.append((g[0]['x0'], g[0]['top'], ' '.join(rest + [number])))
    return out


def _hhmm(text: str) -> str:
    m = CLOCK.match(text)
    return f'{int(m.group(1)):02d}:{m.group(2)}'


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _box(title: str, rows: list[list[dict]], notes: list[str]) -> dict:
    """One box's rows (stop name, then times) as a table, a column per run, split where calls lie GAP apart."""
    named = []
    for r in rows:
        times = [w for w in r if CLOCK.match(w['text'])]
        name = ' '.join(w['text'] for w in r if not times or w['x1'] <= times[0]['x0'])
        if times:
            named.append((name, times))
        elif named:
            notes.append(f'{name}: no time, left out')
    widest = max((t for _, t in named), key=len, default=[])
    cols = [(w['x0'] + w['x1']) / 2 for w in widest]
    stops = [n for n, _ in named]
    grid = [[None] * len(cols) for _ in named]
    for i, (_, times) in enumerate(named):
        for w in times:
            c = min(range(len(cols)), key=lambda c: abs(cols[c] - (w['x0'] + w['x1']) / 2))
            grid[i][c] = _hhmm(w['text'])
    runs = []
    for c in range(len(cols)):
        run: list = [None] * len(stops)
        last = None
        for i in range(len(stops)):
            v = grid[i][c]
            if v is None:
                continue
            if last is not None and not 0 <= _minutes(v) - _minutes(last) <= GAP:
                runs.append(run)
                run = [None] * len(stops)
            run[i], last = v, v
        runs.append(run)
    runs = [r for r in runs if sum(1 for v in r if v) >= 2]
    runs.sort(key=lambda r: _minutes(next(v for v in r if v)))
    return {'line': title, 'title': title, 'stops': stops, 'runs': runs, 'direction': 0,
            'service': SERVICES.get(title.split()[0], 'D'), 'notes': notes}


def _saturdays(words: list[dict]) -> dict[str, tuple[str, str]]:
    """Line -> (from, to) of its Saturday service, from the legend's paragraphs ("Na redni krožni progi 1 … Ob sobotah
    vozi od 8¹³ do 12¹⁰"), each read within its own column."""
    starts = sorted(w['x0'] for w in words if w['text'] == 'redni')
    out = {}
    for n, x in enumerate(starts):
        right = starts[n + 1] if n + 1 < len(starts) else float('inf')
        top = min(w['top'] for w in words if w['text'] == 'redni' and w['x0'] == x)
        text = ' '.join(w['text'] for r in _rows([w for w in words if x - 20 <= w['x0'] < right - 20 and w['top'] >= top - ROW])
                        for w in r)
        m = SATURDAY.search(text)
        if m:
            out[m.group(1)] = (f'{int(m.group(2)):02d}:{m.group(3)}', f'{int(m.group(4)):02d}:{m.group(5)}')
    return out


def read(words: list[dict]) -> list[dict]:
    titles = _titles(words)
    if not titles:
        raise ValueError('no box titles on the page: the layout changed')
    xs: list[float] = []   # a band's left edge: its titles' x, which differ by a point or so
    for x in sorted(x for x, _, _ in titles):
        if not xs or x - xs[-1] > BAND:
            xs.append(x)
    upright = [w for w in words if w.get('upright', True)]
    tables = []
    for b, x in enumerate(xs):
        right = xs[b + 1] if b + 1 < len(xs) else float('inf')
        band = _rows([w for w in upright if x <= w['x0'] < right])
        heads = sorted((top - TITLE_ABOVE, t) for tx, top, t in titles if x <= tx < right)
        boxes: list[tuple[str, list]] = []
        prev = None
        for r in band:
            top = r[0]['top']
            while heads and top >= heads[0][0]:
                boxes.append((heads.pop(0)[1], []))
            timed = any(CLOCK.match(w['text']) for w in r)
            if boxes and not timed and prev is not None and top - prev > ROW_GAP:
                boxes.append((' '.join(w['text'] for w in r), []))   # an upright title: Delavska
            elif boxes:
                boxes[-1][1].append(r)
            prev = top
        for title, rows in boxes:
            t = _box(title, rows, [])
            if t['runs']:
                tables.append(t)
    if not tables:
        raise ValueError('no runs on the page')
    for line, (start, end) in _saturdays(words).items():
        t = next((t for t in tables if t['line'] == f'Proga {line}' and t['service'] == 'D'), None)
        if t is None:
            raise ValueError(f'the legend gives Saturdays for Proga {line}, which has no table')
        within = [r for r in t['runs'] if start <= next(v for v in r if v) and max(v for v in r if v) <= end]
        if not within or next(v for v in within[0] if v) != start or max(v for v in within[-1] if v) != end:
            raise ValueError(f'Proga {line}: no runs fit Saturdays {start}–{end} exactly')
        tables.append({**t, 'service': 'SO', 'runs': within, 'notes': []})
    return tables
