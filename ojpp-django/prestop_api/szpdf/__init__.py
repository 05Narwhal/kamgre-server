"""SŽ's replacement-bus timetables, read from the PDFs its disruption notices link ("Vozni red nadomestnega
prevoza"). `parse(path)` returns the contract in docs/specs/2026-10-14-sz-replacement-timetables.md without the
fetch fields; `sync` (manage.py szpdf_sync) fetches, caches and writes the files the API reads.

Never imported by the web workers: only the prestop-szpdf timer and the tests use it (pdfplumber is heavy).
"""
from datetime import date

import pdfplumber

from . import layout, ocr, tables, texts

SCHEMA = 1
PARSER = 2 # bump when parsing changes: every cached PDF is parsed again


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


def assemble(grids, lines, problems) -> dict:
    blocks = texts.blocks(lines)
    doc = {'schema': SCHEMA, 'parser': PARSER, 'status': 'ok', 'problems': problems, 'valid': None,
           'footnotes': {}, 'stationNotes': [], 'stops': [], 'notes': blocks['notes'], 'tables': []}
    readings = [texts.validity(v) for v in blocks['valid']]
    if not readings or readings[0] is None:
        problems.append(f'validity unreadable: {blocks["valid"]}')
    elif any(r != readings[0] for r in readings):
        problems.append(f'tables differ in validity: {blocks["valid"]}')
    doc['valid'] = readings[0] if readings else None
    start = date.fromisoformat(doc['valid']['from']) if doc['valid'] else date.today()

    for number, text in blocks['footnotes']:
        doc['footnotes'][number] = _footnote(text, start)
    for stars, text in blocks['starred']:
        doc['footnotes'][stars] = _footnote(text, start)

    for grid in sorted(grids, key=lambda g: (g.page, round(g.bbox[1]), g.bbox[0])):
        heading = _heading(grid, blocks['directions'])
        doc['tables'] += tables.directions(grid, heading, blocks['additional_legend'], blocks['connecting'])

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
