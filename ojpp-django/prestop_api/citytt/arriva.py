"""Arriva's city-line timetables: one Word table per line and direction, saved as PDF with a text layer.

    LINIJA 1a: KOROŠKA BELA (trgovina) – BLEJSKA DOBRAVA (pokopališče) – HRUŠICA (Belo Polje)
    Št. Postaja                      Čas odhoda Čas odhoda …
    1   Koroška Bela trgovina        07:00      09:15      …
        / Začetna postaja
    8   Blejska Dobrava              07:10      09:25      …
        pokopališče

A row is a stop number, the stop's name (wrapping onto lines below it) and one departure per column; a column is
one run. Times go to the header's "Čas" column nearest them, so a run that skips a stop leaves its cell empty.
The table may continue on the next page without its header.
"""
import re
from dataclasses import dataclass, field

import pdfplumber

TITLE = re.compile(r'^LINIJA\s+(\w+)\s*:\s*(.+)$', re.I)
TIME = re.compile(r'^([01]?\d|2[0-4])[:.]([0-5]\d)$')
ENDS = re.compile(r'\s*/\s*(začetna|končna)(\s+postaja)?\s*$', re.I)  # "/ Začetna postaja" after a terminus
LINE_GAP = 3    # pt: words this close in height are on one line
WRAP_GAP = 16   # pt: a name's next line is at most this far below the line before it


class ReadError(ValueError):
    pass


@dataclass
class Row:
    number: int
    name: str
    times: list = field(default_factory=list)  # per column: 'HH:MM' or None
    bottom: float = 0.0


def _lines(words: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if out and abs(out[-1][0]['top'] - w['top']) <= LINE_GAP:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w['x0']) for line in out]


def _text(words: list[dict]) -> str:
    return ' '.join(w['text'] for w in words).strip()


def _columns(header: list[dict]) -> list[float]:
    """Centre of each "Čas odhoda" heading (the cell's centre: Word centres heading and times); "odhoda" may wrap
    onto the line below, leaving "Čas" centred alone."""
    out = []
    for i, w in enumerate(header):
        if w['text'] != 'Čas':
            continue
        nxt = header[i + 1] if i + 1 < len(header) else None
        right = nxt['x1'] if nxt and nxt['text'] == 'odhoda' and nxt['x0'] - w['x1'] < 6 else w['x1']
        out.append((w['x0'] + right) / 2)
    return out


def parse(path) -> dict:
    """{'line': '1A', 'title': '…', 'stops': [names], 'runs': [['07:00', '07:01', … or None] per column]}."""
    with pdfplumber.open(path) as pdf:
        pages = [_lines(p.extract_words(keep_blank_chars=False)) for p in pdf.pages]
    return read(pages)


def read(pages: list[list[list[dict]]]) -> dict:
    """The timetable from each page's lines of words ({'text', 'x0', 'x1', 'top'}), as `parse` returns it."""
    line = title = None
    columns: list[float] = []
    rows: list[Row] = []
    for lines in pages:
        last = None  # the row a wrapped name line belongs to, on this page
        for words in lines:
            text = _text(words)
            found = TITLE.match(text)
            if found and line is None:
                line, title = found.group(1).upper(), found.group(2).strip()
                continue
            if not columns and any(w['text'] == 'Postaja' for w in words):
                columns = _columns(words)
                continue
            if not columns:
                continue
            left = min(columns) - (columns[1] - columns[0]) / 2 if len(columns) > 1 else min(columns) - 30
            times = [w for w in words if TIME.match(w['text']) and w['x0'] >= left]
            name = [w for w in words if w['x1'] < left]
            if times and name and name[0]['text'].isdigit():
                row = Row(int(name[0]['text']), _text(name[1:]), [None] * len(columns), words[0]['bottom'])
                for w in times:
                    i = min(range(len(columns)), key=lambda c: abs(columns[c] - (w['x0'] + w['x1']) / 2))
                    if row.times[i] is not None:
                        raise ReadError(f'stop {row.number}: two times in column {i + 1}')
                    h, m = TIME.match(w['text']).groups()
                    row.times[i] = f'{int(h):02d}:{m}'
                rows.append(row)
                last = row
            elif last and not times and name and words[0]['top'] - last.bottom <= WRAP_GAP:
                last.name = f'{last.name} {_text(name)}'
                last.bottom = words[0]['bottom']
            elif times:
                raise ReadError(f'times without a stop: {text!r}')
    if line is None:
        raise ReadError('no "LINIJA …:" title')
    if not columns:
        raise ReadError('no header with "Postaja" and "Čas odhoda" columns')
    if [r.number for r in rows] != list(range(1, len(rows) + 1)):
        raise ReadError(f'stop numbers are not 1…{len(rows)}: {[r.number for r in rows]}')
    stops = [re.sub(r'\s+', ' ', ENDS.sub('', r.name)).strip() for r in rows]
    if not all(stops):
        raise ReadError('a stop without a name')
    runs = [[r.times[c] for r in rows] for c in range(len(columns))]
    return {'line': line, 'title': re.sub(r'\s+', ' ', title), 'stops': stops, 'runs': runs}
