"""Arriva's Ptuj city lines: one A3 page per line, a ruled grid printed as a picture (no text layer).

Layout (`Linija-<n>_…_01092026.pdf`, from 1 Sep 2026): a title "Vozni red 2. Linija Panorama" above the grid; the
grid's first row holds each run's day code ("D", "SO/NEP"), the second its number, then one row per stop: its number,
its name, an arrow column and one column per run, a time or "–". A column is one run from top to bottom (a loop
passes Ptuj AP twice, as rows 1 and 37).

`ocr` renders the page (`pdftoppm -r 300`), finds the grid's ruled lines and reads the words with `tesseract`
(WSL kali-linux, English model: names lose č/š/ž, "Krcevina", which the build matches to the poles' names).
`read` turns those words into tables and is what the tests run, on saved words. A time that goes backwards or jumps
more than MAX_STEP minutes is a misread and fails the build, which keeps the last good feed.
"""
import csv
import io
import re
import subprocess
import tempfile
from pathlib import Path

CLOCK = re.compile(r'(?<!\d)([01]?\d|2[0-3])[:.;]([0-5]\d)(?!\d)')
# Day codes over the runs (legend): D = workdays (lines 2-5: 1 Sep - 30 Jun only, the city's services say which),
# SO/NEP = Saturdays, Sundays and public holidays.
SERVICES = {'D': 'D', 'SO/NEP': 'SONP', 'SONEP': 'SONP'}
LINE = re.compile(r'Linija[-_ ]?(\d+)', re.I)
DPI = 300
DARK = 110          # grey level below which a pixel is ink
ROW_SHARE = 0.45    # a ruled row line spans at least this share of the page width
COL_SHARE = 0.6     # a ruled column line spans at least this share of the grid's height
MERGE = 6           # px: ink rows or columns this close are one line
INSET = 6           # px cut from each side of a header cell read on its own
MAX_STEP = 30       # minutes between two calls of a run; more is a misread


class ReadError(ValueError):  # build.py reports a file's ValueError as a problem
    pass


def _lines(profile: list[int], need: float) -> list[float]:
    found, start = [], None
    for i, v in enumerate([*profile, 0]):
        if v >= need and start is None:
            start = i
        elif v < need and start is not None:
            found.append((start + i - 1) / 2)
            start = None
    merged: list[float] = []
    for x in found:
        if merged and x - merged[-1] < MERGE:
            merged[-1] = (merged[-1] + x) / 2
        else:
            merged.append(x)
    return merged


def grid(img) -> tuple[list[float], list[float]]:
    """x of every ruled column line and y of every ruled row line."""
    from PIL import Image
    ink = img.convert('L').point(lambda v: 1 if v < DARK else 0)
    w, h = ink.size
    data = ink.tobytes()
    ys = _lines([sum(data[y * w:(y + 1) * w]) for y in range(h)], ROW_SHARE * w)
    if len(ys) < 4:
        raise ReadError(f'no grid: {len(ys)} ruled rows')
    band = ink.crop((0, int(ys[0]), w, int(ys[-1]))).transpose(Image.Transpose.TRANSPOSE)  # the grid's columns as rows
    bw, bh = band.size
    data = band.tobytes()
    cols = [sum(data[y * bw:(y + 1) * bw]) for y in range(bh)]
    xs = _lines(cols, COL_SHARE * (ys[-1] - ys[0]))
    if len(xs) < 4:
        raise ReadError(f'no grid: {len(xs)} ruled columns')
    return xs, ys


def _tesseract(image_path: str, psm: int) -> list[dict]:
    out = subprocess.run(['tesseract', image_path, '-', '--psm', str(psm), 'tsv'], capture_output=True, text=True,
                         check=True, timeout=300).stdout
    rows = csv.DictReader(io.StringIO(out), delimiter='\t', quoting=csv.QUOTE_NONE)
    return [{'text': r['text'].strip(), 'x': int(r['left']) + int(r['width']) / 2, 'y': int(r['top']) + int(r['height']) / 2}
            for r in rows if (r.get('text') or '').strip() and float(r['conf']) >= 0]


def _at(xs: list[float], ys: list[float], w: dict) -> tuple:
    c = next((i for i in range(len(xs) - 1) if xs[i] <= w['x'] < xs[i + 1]), None)
    r = next((i for i in range(len(ys) - 1) if ys[i] <= w['y'] < ys[i + 1]), None)
    return r, c


def ocr(path: str) -> dict:
    """The page's ruled lines and words ({'text', 'x', 'y'} in px at DPI). Header cells the page pass missed
    (a lone "D" in sparse mode) are read again on their own."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / 'page'
        subprocess.run(['pdftoppm', '-r', str(DPI), '-png', '-singlefile', '-f', '1', '-l', '1', path, str(png)],
                       check=True, timeout=120)
        png = png.with_suffix('.png')
        img = Image.open(png)
        xs, ys = grid(img)
        words = _tesseract(str(png), 11)
        seen = {_at(xs, ys, w) for w in words}
        timed = {c for w in words for r, c in [_at(xs, ys, w)] if r is not None and r >= 2 and CLOCK.search(w['text'])}
        for c in sorted(timed):
            for r in (0, 1):
                if (r, c) in seen:
                    continue
                cell = Path(tmp) / f'cell-{r}-{c}.png'
                img.crop((int(xs[c]) + INSET, int(ys[r]) + INSET, int(xs[c + 1]) - INSET, int(ys[r + 1]) - INSET)).save(cell)
                for w in _tesseract(str(cell), 7):
                    words.append({'text': w['text'], 'x': (xs[c] + xs[c + 1]) / 2, 'y': (ys[r] + ys[r + 1]) / 2})
    return {'xs': xs, 'ys': ys, 'words': words}


def _minutes(text: str):
    m = CLOCK.search(text)
    return (int(m.group(1)) * 60 + int(m.group(2))) if m else None


def read(page: dict, line=None) -> list[dict]:
    """One table per service: {'line', 'title', 'stops', 'runs', 'direction', 'service', 'notes'}. The line is the
    number before "Linija" in the title unless given (the build reads a temporary file without the PDF's name)."""
    xs, ys = page['xs'], page['ys']
    cells: dict[tuple, list[str]] = {}
    above = []
    for w in sorted(page['words'], key=lambda w: w['x']):   # a cell's words left to right ("Ptuj AP", not "AP Ptuj")
        r, c = _at(xs, ys, w)
        if w['y'] < ys[0]:
            above.append(w)
        elif r is not None and c is not None:
            cells.setdefault((r, c), []).append(w['text'])
    text = lambda r, c: ' '.join(cells.get((r, c), []))
    title = ''
    for w in above:   # "Vozni red 2. Linija Panorama": the words after "Linija" on its row
        if w['text'].casefold() == 'linija':
            same = [v for v in above if abs(v['y'] - w['y']) < 20]
            title = ' '.join(v['text'] for v in same if v['x'] > w['x'])
            number = [re.sub(r'\D', '', v['text']) for v in same if v['x'] < w['x'] and re.fullmatch(r'\d+\.?', v['text'])]
            line = line or (number[-1] if number else None)
            break
    if not line:
        raise ReadError('no line number in the title ("2. Linija …")')
    rows = [r for r in range(2, len(ys) - 1) if text(r, 1)]
    stops = [re.sub(r'\s+', ' ', text(r, 1)).strip() for r in rows]
    runs_at = sorted({c for (r, c), ws in cells.items() if r >= 2 and c > 1 and any(CLOCK.search(v) for v in ws)})
    if not rows or not runs_at:
        raise ReadError(f'line {line}: {len(rows)} stops, {len(runs_at)} runs read')
    tables: dict[str, dict] = {}
    for c in runs_at:
        code = re.sub(r'[\s|]', '', text(0, c)).upper()
        if code not in SERVICES:
            raise ReadError(f'line {line}: unknown day code {code!r} over run {text(1, c) or c}: look at the page, add it to SERVICES')
        run, last = [], None
        for r, name in zip(rows, stops):
            m = _minutes(text(r, c))
            if m is not None and last is not None and not 0 <= m - last[0] <= MAX_STEP:
                raise ReadError(f'line {line} run {text(1, c) or c}: {last[1]} {last[0] // 60:02d}:{last[0] % 60:02d} '
                                f'then {name} {m // 60:02d}:{m % 60:02d}: a misread? look at the page')
            if m is not None:
                last = (m, name)
            run.append(f'{m // 60:02d}:{m % 60:02d}' if m is not None else None)
        if sum(1 for v in run if v) < 2:
            raise ReadError(f'line {line} run {text(1, c) or c}: {sum(1 for v in run if v)} times read')
        service = SERVICES[code]
        tables.setdefault(service, {'line': line, 'title': title or f'Linija {line}', 'stops': stops, 'runs': [],
                                    'direction': 0, 'service': service, 'notes': []})['runs'].append(run)
    return list(tables.values())


def parse(path) -> list[dict]:
    m = LINE.search(Path(path).name)
    return read(ocr(str(path)), m.group(1) if m else None)
