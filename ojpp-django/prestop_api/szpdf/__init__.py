"""SŽ's replacement-bus timetables, read from the PDFs its disruption notices link ("Vozni red nadomestnega
prevoza"). `parse(path)` returns the contract in docs/specs/2026-10-14-sz-replacement-timetables.md without the
fetch fields; `sync` (manage.py szpdf_sync) fetches, caches and writes the files the API reads.

Never imported by the web workers: only the prestop-szpdf timer and the tests use it (pdfplumber is heavy).
"""
from datetime import date, timedelta

import pdfplumber

from . import layout, ocr, tables, texts

SCHEMA = 1
PARSER = 4 # bump when parsing changes: every cached PDF is parsed again


def parse(path) -> dict:
    with pdfplumber.open(path) as pdf:
        grids, lines, images = [], [], []
        for n, page in enumerate(pdf.pages):
            found = layout.grids(page, n)
            grids += found
            lines += layout.lines(page, n, [g.bbox for g in found])
            images += [(n, im) for im in page.images]
        problems = []
        for grid in grids:
            problems += ocr.apply(path, pdf.pages[grid.page], grid, [im for n, im in images if n == grid.page])
    return assemble(grids, lines, problems)


def validity_above(readings: list, places: list, page: int, box: tuple) -> dict | None:
    """The last validity printed above a table, in its column where tables stand side by side (`places`: the (page,
    top, x0) of each of `readings`; `box`: the table's), or None."""
    above = [(r, p) for r, p in zip(readings, places) if p[:2] <= (page, box[1])]
    beside = [r for r, p in above if box[0] - 20 <= p[2] <= box[2]]
    return (beside or [r for r, _ in above] or [None])[-1]


def _days(reading: dict) -> set[str]:
    if reading.get('dates'):
        return set(reading['dates'])
    first, last = date.fromisoformat(reading['from']), date.fromisoformat(reading['to'])
    return {(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)}


def whole_validity(readings: list) -> dict:
    """All the days of a file whose tables have validities of their own: from - to, or the dates where there is a gap."""
    days = sorted(set().union(*(_days(r) for r in readings)))
    first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    return {'from': days[0], 'to': days[-1], 'dates': None if (last - first).days + 1 == len(days) else days}


def assemble(grids, lines, problems) -> dict:
    blocks = texts.blocks(lines)
    doc = {'schema': SCHEMA, 'parser': PARSER, 'status': 'ok', 'problems': problems, 'valid': None,
           'footnotes': {}, 'stationNotes': [], 'stops': [], 'notes': blocks['notes'], 'tables': []}
    readings = [texts.validity(v) for v in blocks['valid']]
    if not readings or readings[0] is None:
        problems.append(f'validity unreadable: {blocks["valid"]}')
    several = bool(readings) and None not in readings and any(r != readings[0] for r in readings)
    doc['valid'] = whole_validity(readings) if several else readings[0] if readings else None
    start = date.fromisoformat(doc['valid']['from']) if doc['valid'] else date.today()

    for number, text in blocks['footnotes']:
        doc['footnotes'][number] = _footnote(text, start)
    for stars, text in blocks['starred']:
        doc['footnotes'][stars] = _footnote(text, start)

    for grid in sorted(grids, key=lambda g: (g.page, round(g.bbox[1]), g.bbox[0])):
        heading = _heading(grid, blocks['directions'])
        found = tables.directions(grid, heading, blocks['additional_legend'], blocks['connecting'])
        if several:  # "Od 31. 10. do 8. 11." and "Od 9. do 11. 11." in one file: a table runs in the validity above it
            own = validity_above(readings, blocks['valid_at'], grid.page, grid.bbox)
            if own is None:
                problems.append(f'no validity above the table on page {grid.page + 1}: {blocks["valid"]}')
            for t in found:
                for col in t['columns']:
                    col['valid'] = own or doc['valid']
        doc['tables'] += found

    # A footnote "*" with no "*…" line: SŽ's red unnumbered note under OPOMBA (11159).
    used = {f for t in doc['tables'] for c in t['columns'] for f in c['footnotes']}
    unnumbered = list(blocks['unnumbered'])
    for stars in sorted(u for u in used if u.startswith('*') and u not in doc['footnotes']):
        red = next((u for u in unnumbered if u[1]), None)
        if red:
            unnumbered.remove(red)
            doc['footnotes'][stars] = _footnote(red[0], start)
    doc['notes'] += [text for text, _ in unnumbered]
    doc['stops'], doc['stationNotes'] = texts.finish_stops(blocks)

    for n, t in enumerate(doc['tables'], start=1):
        for col in t['columns']:
            for f in col['footnotes']:
                if f not in doc['footnotes']:
                    col['problems'].append(f'footnote {f} is not defined')
                elif doc['footnotes'][f]['rule'] is None:
                    col['problems'].append(f'footnote {f} has an unknown wording')
            problems += [f'table {n} "{t["direction"]}", column {col["label"] or "?"}: {p}' for p in col['problems']]
    if not doc['tables']:
        problems.append('no timetable table found')
    doc['status'] = 'failed' if not doc['tables'] or doc['valid'] is None else 'unsure' if problems else 'ok'
    return doc


def _footnote(text: str, start: date) -> dict:
    rule, dates = texts.footnote_rule(texts.slovene(text), start)
    section = texts.footnote_section(texts.slovene(text)) if rule == 'train_runs_on' else None
    return {'text': texts.slovene(text), 'rule': rule, **({'dates': dates} if dates else {}),
            **({'section': section} if section else {})}


def _heading(grid, directions) -> str:
    """The "Smer / Direction" text nearest above the table and over it."""
    x0, top, x1, _ = grid.bbox
    above = [d for d in directions if d.page == grid.page and d.top < top and x0 - 10 <= d.x0 <= x1]
    return texts.direction_text(max(above, key=lambda d: d.top).text) if above else ''
