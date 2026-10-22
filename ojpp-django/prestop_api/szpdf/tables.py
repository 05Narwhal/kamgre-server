"""A timetable grid → one table per direction, with one column per bus and its calls in travel order.

Grid layout (SŽ's Excel template): the first column holds the row labels ("Nadomestni prevoz", "Številka vlaka",
"POSTAJA/OPOMBE", then one row per station, two for a station with arrival P and departure O). A column of P/O marks
starts each direction; a table with two of them holds the return direction on the right, read bottom to top when
its topmost mark is P (the arrow points up).
"""
import re

from .texts import fold

VEHICLE = re.compile(r'(BUS|8\+1)\s*(\*?)\s*(\d*)')
TRAIN = re.compile(r'(\d+)(?:/(\d{1,2}))?')
# A connecting bus between trains: "318/4211", "*2424/**2494 / 4219" (stars mark which footnote goes with which train).
CONNECTION = re.compile(r'\**\d{3,}(?:\s*/\s*\**\d{3,})+')
TIME = re.compile(r'(\d{1,2})\s*:+\s*(\d{2})')  # 10088 prints "17::00"
PASSES = {'I', '|', 'l', '1'}
MAX_STEP = 180


def row_kind(label: str) -> str:
    f = fold(label)
    if f.startswith('nadomestni prevoz'):
        return 'vehicle'
    if f.startswith('stevilka vlaka'):
        return 'train'
    if f.startswith('st. bus'):
        return 'bus'
    if 'opomb' in f or 'notice' in f:
        return 'footnotes'
    if f.startswith('postaja'):
        return 'postaja'
    return 'station' if f else 'blank'


def cell_value(text: str) -> tuple[str, str | None]:
    """('time', 'HH:MM') | ('pass', None) | ('empty', None) | ('bad', text)."""
    t = text.strip()
    if not t:
        return 'empty', None
    if t in PASSES:
        return 'pass', None
    m = TIME.fullmatch(t)
    if m and int(m[1]) < 24 and int(m[2]) < 60:
        return 'time', f'{int(m[1]):02d}:{m[2]}'
    return 'bad', t


def hhmm(minutes: int) -> str:
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def directions(grid, heading: str, additional_legend: bool, connecting: bool) -> list[dict]:
    """The grid's direction tables (left first). `heading` is the "Smer / Direction" text above it."""
    labels = [c.text for c in grid.columns[0].cells]
    kinds = [row_kind(t) for t in labels]
    first_station = next((i for i, k in enumerate(kinds) if k == 'station'), len(kinds))
    header = {}
    for i in range(first_station):
        header.setdefault(kinds[i], i)
    fn_row = header.get('footnotes', header.get('postaja', header.get('blank')))
    station_rows = list(range(first_station, len(kinds)))
    header_rows = [header[k] for k in ('vehicle', 'train') if k in header] + ([fn_row] if fn_row is not None else [])

    segments: list[dict] = []
    for k, col in enumerate(grid.columns[1:], start=1):
        st = [col.cells[r].text.strip() for r in station_rows]
        hd = [col.cells[r].text.strip() for r in header_rows]
        if not any(hd) and any(st) and all(v in ('', 'P', 'O') for v in st):
            segments.append({'mark': k, 'columns': []})
        elif any(hd) or any(st):
            if not segments:
                segments.append({'mark': None, 'columns': []})
            segments[-1]['columns'].append(k)

    out = []
    for n, seg in enumerate(segments):
        marks = {r: grid.columns[seg['mark']].cells[r].text.strip() if seg['mark'] else '' for r in station_rows}
        up = next((marks[r] for r in station_rows if marks[r]), 'O') == 'P'
        order = list(reversed(station_rows)) if up else station_rows
        stations = _stations(labels, order, marks)
        direction = heading if n == 0 else ' - '.join(reversed(heading.split(' - ')))
        columns = [_column(grid, k, header, fn_row, stations, additional_legend, connecting) for k in seg['columns']]
        source = 'mixed' if any(grid.columns[k].source == 'ocr' for k in seg['columns']) else 'text'
        out.append({'direction': direction, 'source': source, 'stations': [s['name'] for s in stations],
                    'columns': columns})
    return out


def _stations(labels, order, marks) -> list[dict]:
    """Consecutive rows with the same station name are one station: its P row is the arrival, its O row the
    departure (unmarked: the first row in travel order is the arrival)."""
    stations: list[dict] = []
    for r in order:
        name = labels[r].strip()
        if stations and fold(stations[-1]['name']) == fold(name):
            stations[-1]['rows'].append(r)
        else:
            stations.append({'name': name, 'rows': [r]})
    for s in stations:
        if len(s['rows']) == 1:
            s['arr'] = s['dep'] = s['rows'][0]
        else:
            by_mark = {marks[r]: r for r in s['rows'] if marks[r] in ('P', 'O')}
            s['arr'] = by_mark.get('P', s['rows'][0])
            s['dep'] = by_mark.get('O', s['rows'][-1])
    return stations


def _column(grid, k, header, fn_row, stations, additional_legend, connecting) -> dict:
    cells = grid.columns[k].cells
    problems = list(grid.columns[k].problems)
    vehicle_text = cells[header['vehicle']].text if 'vehicle' in header else ''
    label_cell = cells[header['train']] if 'train' in header else None
    label = ' '.join(label_cell.text.split()) if label_cell else ''

    vehicle, mark = None, None
    m = VEHICLE.fullmatch(vehicle_text.strip())
    if m:
        vehicle, mark = m[1], m[2] or None
    else:
        problems.append(f'vehicle "{vehicle_text}" unreadable')

    train, part, link = None, None, False
    if (m := TRAIN.fullmatch(label)):
        train, part = m[1], int(m[2]) if m[2] else None
    elif CONNECTION.fullmatch(label):
        train, link = re.search(r'\d+', label)[0], True
    else:
        problems.append(f'train label "{label}" missing or malformed' if label else 'no train label')

    footnotes = []
    fn_text = cells[fn_row].text if fn_row is not None else ''
    for tok in re.split(r'[\s/,]+', fn_text.strip()):
        if re.fullmatch(r'\d+|\*+', tok):
            footnotes.append(tok)
        elif tok and not re.fullmatch(r'\*+\d+', tok):  # "*2,**3": footnotes of the trains a connecting bus links
            problems.append(f'footnote cell "{fn_text}" unreadable')
    if mark and mark not in footnotes:
        footnotes.append(mark)

    calls = []
    for s in stations:
        values = {}
        for role in ('arr', 'dep'):
            kind, value = cell_value(cells[s[role]].text)
            if kind == 'bad':
                problems.append(f'row {s["name"]}: cell "{value}" unreadable')
            elif kind == 'time':
                values[role] = value
        if values:
            calls.append({'station': s['name'], 'arr': values.get('arr', values.get('dep')),
                          'dep': values.get('dep', values.get('arr'))})
    if calls:
        del calls[0]['arr']
    if len(calls) > 1:
        del calls[-1]['dep']
    problems += _clock(calls)
    if len(calls) < 2:
        problems.append(f'{len(calls)} call(s)')
    additional = connecting or link or (additional_legend and bool(label_cell and label_cell.red))
    return {'label': label, 'train': train, 'part': part, 'vehicle': vehicle, 'mark': mark, 'additional': additional,
            'footnotes': footnotes, 'calls': calls, 'problems': problems}


def _clock(calls: list[dict]) -> list[str]:
    """Times in travel order continue past 24:00 after midnight; a step back, a step over three hours or an
    arrival after the departure is a problem."""
    problems, prev, offset = [], None, 0
    for call in calls:
        for role in ('arr', 'dep'):
            if role not in call:
                continue
            h, m = map(int, call[role].split(':'))
            v = h * 60 + m + offset
            if prev is not None and v < prev - 12 * 60:
                offset += 24 * 60
                v += 24 * 60
            if prev is not None and v < prev:
                problems.append(f'row {call["station"]}: {call[role]} is before {hhmm(prev)}')
            elif prev is not None and v - prev > MAX_STEP:
                problems.append(f'row {call["station"]}: {v - prev} min after the previous time')
            call[role] = hhmm(v)
            prev = v
    return problems
