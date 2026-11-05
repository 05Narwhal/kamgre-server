"""Celje's city buses (Nomago, network CELEBUS): one Word file per line, `Linija_<n>_2026-09.docx`, read with zipfile and
ElementTree only.

    Smer: Hudinja-Škofja vas-(Linija 3) Odhod            (a paragraph, or split over the cells of the first table)
    | 10    | 11 | 12 |    | POSTAJE,        |      run numbers, one cell per run
    | D*    | SO | DŠ | KM | POSTAJALIŠČA    |      the run's service code
    | 08:25 | 08:55 | I | 0 | Celje | ŽP      |      a call per run, then the km, then the stop name (in one to four cells)

A file holds several tables (page breaks): a table with run numbers starts a block of runs, the tables without go on
with the stops of the block before, in order. Every block lists the same stops, so a run is a column of all of them; the
tables of a line are the columns of one service each. What the reader makes of the oddities:

* `I` (passes without stopping), `---` and `-` (does not go there) and an empty cell are no call (None).
* A cell holding several times (`12:29 12:29`, a merged cell) is that many runs; a cell wider than its run is one.
* A stop with a wait prints three rows: the time it arrives on a row without a name, the named row (`---` in every
  run), the time it leaves on a row without a name. The file has no vMerge, so the rows are tied by position: a row
  without a name before a named row with `---` is its arrival, one after it its departure. One call per stop, the
  departure (the later time).
* Rows that fell out of a table are paragraphs: the times separated by spaces, then the km glued to the stop name
  (`21:15` `4` `Celje ŽP`). They are rows of the block before them; a paragraph with another number of times than the
  block has runs is an error, not a guess.
* The legend ("Režimi obratovanja linije: D*- Vozi ob delavnikih razen sobote") must explain every code the headers use,
  and each code must be in SERVICES (`D*` -> `D`, `SO` -> `SO`, `DŠ` -> `DS`).
* "Čas veljavnosti voznega reda:01.09.2026 - 30.06.2029" is in every table's `notes` and as `valid_from` / `valid_to`
  (ISO dates), so a build can check them.

`parse` returns one table per (line, service): `{'line', 'title', 'stops', 'runs', 'direction', 'service', 'notes',
'valid_from', 'valid_to'}`, runs sorted by first departure, runs with fewer than two calls dropped. Every direction is
`Odhod` (a loop or there-and-back in one column): `direction` 0. A layout the reader does not know, or a time that goes
back inside a run, is a ValueError naming the file, the line and the stop.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SERVICES = {'D*': 'D', 'SO': 'SO', 'DŠ': 'DS'}
CLOCK = re.compile(r'^(\d{1,2}):(\d{2})$')
TOKEN = re.compile(r'\d{1,2}:\d{2}|I(?=[\s\d]|$)|-{1,3}(?=[\s\d]|$)')
LEAK = re.compile(r'^(?:\d{1,2}:\d{2}|I|-{1,3})(?=[\s\d]|$)')
SMER = re.compile(r'Smer:\s*(.*?)\s*-?\s*\(Linija\s+([^)\s]+)\)\s*(\S*)')
VALID = re.compile(r'Čas veljavnosti voznega reda:\s*(\d\d)\.(\d\d)\.(\d{4})\s*-\s*(\d\d)\.(\d\d)\.(\d{4})')
LEGEND = re.compile(r'^([A-ZŠČŽ]{1,3}\*?)\s*-\s*\S')
NO_CALL = {'', 'I', '-', '--', '---'}


def parse(source) -> list[dict]:
    """`source`: a path, bytes or a binary file object of a .docx."""
    name = str(getattr(source, 'name', source)) if not isinstance(source, bytes) else '<bytes>'
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    elif hasattr(source, 'read'):
        source = io.BytesIO(source.read())
    try:
        with zipfile.ZipFile(source) as z:
            xml = z.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError(f'{name}: not a Word file ({e})') from e
    return read(xml, name)


def _text(el) -> str:
    return re.sub(r'\s+', ' ', ''.join(t.text or '' for t in el.iter(W + 't')).replace(' ', ' ')).strip()


def _events(xml: bytes, name: str) -> list[tuple]:
    """('p', text) per paragraph and ('row', [(paragraphs, span), …]) per table row, in document order."""
    try:
        body = ET.fromstring(xml).find(W + 'body')
    except ET.ParseError as e:
        raise ValueError(f'{name}: document.xml is not XML ({e})') from e
    if body is None:
        raise ValueError(f'{name}: no body: the layout changed')
    out: list[tuple] = []
    for el in body:
        if el.tag == W + 'p':
            if _text(el):
                out.append(('p', _text(el)))
        elif el.tag == W + 'tbl':
            for tr in el.findall(W + 'tr'):
                cells = []
                for tc in tr.findall(W + 'tc'):
                    span = tc.find(f'{W}tcPr/{W}gridSpan')
                    cells.append(([_text(p) for p in tc.findall(W + 'p')], int(span.get(W + 'val')) if span is not None else 1))
                out.append(('row', cells))
    return out


def _hhmm(text: str, where: str) -> str | None:
    if text in NO_CALL:
        return None
    m = CLOCK.match(text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f'{where}: "{text}" is not a time')
    return f'{int(m.group(1)):02d}:{m.group(2)}'


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


class _Block:
    """The runs of one header (run numbers, service codes) and the stops printed under it."""

    def __init__(self, numbers: list[str]):
        self.numbers = numbers
        self.codes: list[str] = []
        self.entries: list[dict] = []   # name, main (a call per run), arr, dep
        self.pending: list | None = None


def read(xml: bytes, name: str = '<docx>') -> list[dict]:
    """The tables of a line's document.xml (`parse` reads it from the .docx)."""
    events = _events(xml, name)
    smer: list[str] = []          # "Smer: …(Linija 3) Odhod" texts
    legend: dict[str, str] = {}
    validity = None
    blocks: list[_Block] = []
    in_legend = False

    def fail(msg: str, block: _Block | None = None, stop: str = '') -> ValueError:
        line = (smer and SMER.search(smer[0]) and SMER.search(smer[0]).group(2)) or '?'
        return ValueError(f'{name}: line {line}{", stop " + stop if stop else ""}: {msg}')

    def add_row(block: _Block, times: list[str], label: str, where: str) -> None:
        """One row of the block: a call per run (already text), then the stop's name ('' on an arrival or departure row)."""
        calls = [_hhmm(t, where) for t in times]
        dwell = any(t == '---' for t in times)
        if not label:
            last = block.entries[-1] if block.entries else None
            if last is not None and last['dwell'] and last['arr'] is not None and last['dep'] is None:
                last['dep'] = calls
            elif block.pending is not None:
                raise fail('two rows without a stop name in a row', block)
            else:
                block.pending = calls
            return
        entry = {'name': label, 'main': calls, 'dwell': dwell, 'arr': block.pending, 'dep': None}
        if block.pending is not None and not dwell:
            raise fail('a time on a row with no stop name, before a stop that does not wait', block, label)
        block.pending = None
        block.entries.append(entry)

    for kind, item in events:
        if kind == 'p':
            text = item
            if text.startswith('Smer:'):
                smer.append(text)
            elif text.startswith('Čas veljavnosti'):
                m = VALID.search(text)
                if not m:
                    raise fail(f'cannot read the validity "{text}"')
                validity = (text, m)
            elif text.startswith('Režimi obratovanja'):
                in_legend = True
                text = text.split(':', 1)[1].strip()
            elif text.startswith('Odgovorna'):
                in_legend = False
            if in_legend:
                m = LEGEND.match(text)
                if m:
                    legend[m.group(1)] = text
            elif blocks and re.search(r'\d{1,2}:\d{2}', text):   # times outside a table: a row that fell out of it
                block = blocks[-1]
                if not LEAK.match(text):
                    raise fail(f'"{text[:60]}" looks like a row but starts with something else than a time', block)
                n = len(block.numbers)
                pos, times = 0, []
                while len(times) < n:
                    m = TOKEN.match(text, pos)
                    if not m:
                        raise fail(f'"{text}" has {len(times)} times, the table has {n} runs', block)
                    times.append(m.group(0))
                    pos = m.end()
                    while pos < len(text) and text[pos] == ' ':
                        pos += 1
                rest = text[pos:]
                if TOKEN.match(rest) and (CLOCK.match(rest.split()[0]) or rest.split()[0] in ('I', '-', '--', '---')):
                    raise fail(f'"{text}" has more times than the table has runs ({n})', block)
                m = re.match(r'(\d*)\s*(.*)$', rest)
                add_row(block, times, m.group(2).strip(), text)
            continue
        cells = item
        texts = [' '.join(p for p in c[0] if p) for c in cells]
        nonempty = [t for t in texts if t]
        if nonempty and nonempty[0].startswith('Smer:'):
            smer.append(' '.join(nonempty))
            continue
        if nonempty == ['Odhod']:
            if smer and 'Odhod' not in smer[-1]:
                smer[-1] += ' Odhod'
            continue
        last = texts[-1] if texts else ''
        if last.startswith('POSTAJE'):
            parts = [c[0] for c in cells[:-2]]
            if len(cells) < 3 or texts[-2] not in ('', 'KM'):
                raise fail('a header row of an unknown shape')
            if 'POSTAJALI' in last:   # numbers and codes in one row, one above the other
                if any(len(p) != 2 for p in parts):
                    raise fail('a header row without a code under a run number')
                block = _Block([p[0] for p in parts])
                block.codes = [p[1] for p in parts]
            else:
                block = _Block([' '.join(p) for p in parts])
            if not block.numbers or not all(re.fullmatch(r'\d+', n) for n in block.numbers):
                raise fail(f'run numbers {block.numbers}')
            blocks.append(block)
            continue
        if last.startswith('POSTAJALI'):
            if not blocks or blocks[-1].codes or len(cells) - 2 != len(blocks[-1].numbers):
                raise fail('service codes that do not match the run numbers above')
            blocks[-1].codes = texts[:-2]
            continue
        if not blocks:
            continue   # the registration data above the first header
        block = blocks[-1]
        if not block.codes:
            raise fail(f'run {block.numbers[0]}… has no service codes')
        n = len(block.numbers)
        times: list[str] = []
        i = 0
        while len(times) < n and i < len(cells):
            tokens = texts[i].split() or ['']
            times += tokens
            i += 1
        if len(times) != n or i >= len(cells):
            raise fail(f'a row of {len(times)} times, the table has {n} runs: {" | ".join(texts)[:80]}', block)
        km = texts[i]
        if not re.fullmatch(r'\d*', km):
            raise fail(f'"{km}" is not a km', block)
        add_row(block, times, ' '.join(t for t in texts[i + 1:] if t), ' | '.join(texts)[:80])

    if not smer:
        raise ValueError(f'{name}: no "Smer: …(Linija n) Odhod" in the file: the layout changed')
    found = {(m.group(1), m.group(2), m.group(3)) for m in (SMER.search(s) for s in smer) if m}
    if len(found) != 1 or len(smer) != sum(1 for s in smer if SMER.search(s)):
        raise ValueError(f'{name}: "Smer" lines that do not agree: {sorted(smer)[:3]}')
    title, line, direction = next(iter(found))
    if direction != 'Odhod':
        raise ValueError(f'{name}: line {line}: direction "{direction}", only "Odhod" is known')
    if validity is None:
        raise ValueError(f'{name}: line {line}: no "Čas veljavnosti voznega reda"')
    if not blocks:
        raise ValueError(f'{name}: line {line}: no timetable header')
    sentence, v = validity
    for b in blocks:
        if b.pending is not None:
            raise ValueError(f'{name}: line {line}: a time on a row with no stop name at the end of the runs {b.numbers[0]}…')
        if not b.entries:
            raise ValueError(f'{name}: line {line}: runs {b.numbers[0]}… have no stops')
        for code in b.codes:
            if code not in SERVICES:
                raise ValueError(f'{name}: line {line}: service code "{code}" is not known')
            if code not in legend:
                raise ValueError(f'{name}: line {line}: service code "{code}" is not explained in the legend')
    norm = lambda b: [re.sub(r'\W', '', e['name']).lower() for e in b.entries]  # noqa: E731
    stops = [e['name'] for e in blocks[0].entries]
    for b in blocks[1:]:
        if norm(b) != norm(blocks[0]):
            raise ValueError(f'{name}: line {line}: runs {b.numbers[0]}… list other stops than runs {blocks[0].numbers[0]}…')
    seen: set[str] = set()
    for b in blocks:
        for num in b.numbers:
            if num in seen:
                raise ValueError(f'{name}: line {line}: run {num} twice')
            seen.add(num)

    columns: dict[str, list[tuple[int, list]]] = {}   # service -> (run number, call per stop)
    for b in blocks:
        for c, (num, code) in enumerate(zip(b.numbers, b.codes)):
            run: list = []
            before = None
            for e in b.entries:
                arr = e['arr'][c] if e['arr'] else None
                dep = e['dep'][c] if e['dep'] else None
                main = e['main'][c]
                if main is not None and (arr is not None or dep is not None):
                    raise ValueError(f'{name}: line {line}, stop {e["name"]}: run {num} has a time on the stop row and on its arrival/departure rows')
                for t in (arr, main, dep):
                    if t is None:
                        continue
                    if before is not None and _minutes(t) < _minutes(before):
                        raise ValueError(f'{name}: line {line}, stop {e["name"]}: run {num} goes back from {before} to {t}')
                    before = t
                run.append(dep or main or arr)
            columns.setdefault(SERVICES[code], []).append((int(num), run))
    tables = []
    for service, cols in columns.items():
        runs = [(n, r) for n, r in cols if sum(1 for v in r if v) >= 2]
        runs.sort(key=lambda nr: (_minutes(next(v for v in nr[1] if v)), nr[0]))
        if runs:
            tables.append({'line': line, 'title': title, 'stops': stops, 'runs': [r for _, r in runs], 'direction': 0,
                           'service': service, 'notes': [sentence],
                           'valid_from': f'{v.group(3)}-{v.group(2)}-{v.group(1)}', 'valid_to': f'{v.group(6)}-{v.group(5)}-{v.group(4)}'})
    if not tables:
        raise ValueError(f'{name}: line {line}: no runs')
    return tables
