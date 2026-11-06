"""Readers of potniski.sz.si's pages. Each raises SiteError('layout', why) when the structure it needs is missing, so a
changed site shows up as an error and the last good copy stays (store.py), never as an empty list.

Regular expressions over the markup, like sz_list.py (which reads the notices): the pages are server-rendered and the
parts we need have stable ids and class names.
"""
import html
import json
import re
from datetime import date
from typing import Any, Optional

from .. import mapping, sz_list
from .client import SiteError

CHECKED = 5  # items of the live list whose keys are checked
DAYS = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{4})')
ROADWORKS = re.compile(r'var\s+roadworks\s*=\s*')
TABLE = re.compile(r'<table\b([^>]*)>(.*?)</table>', re.S | re.I)
ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S | re.I)
CELL = re.compile(r'<t([hd])\b[^>]*>(.*?)</t[hd]>', re.S | re.I)
OPTION = re.compile(r'<option\b[^>]*value="(\d+)"[^>]*\bselected\b[^>]*>(.*?)</option>', re.S | re.I)
SET_BLOCK = re.compile(r'<div class="single-train-details.*?<h5>(.*?)</h5>.*?href="https://potniski\.sz\.si/train/([a-z0-9-]+)/"', re.S)
TRAIN_LABEL = re.compile(r'Vlak:\s*(?:<span[^>]*>)?\s*([^<]*?)\s*(?:</span>|<)')


def _plain(fragment: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragment))).strip()


def active_trains(data: Any) -> list[dict]:
    """SŽ's `aktivni_vlaki` answer: a list of running trains and buses ([] is valid, e.g. at night), returned unchanged
    for sz.parse_trains. The first items must have `St_vlaka` and `Koordinate`."""
    if not isinstance(data, list):
        raise SiteError('layout', 'aktivni_vlaki is not a list')
    if not all(isinstance(item, dict) for item in data):
        raise SiteError('layout', 'aktivni_vlaki holds something that is not a train')
    for item in data[:CHECKED]:
        if 'St_vlaka' not in item or 'Koordinate' not in item:
            raise SiteError('layout', 'aktivni_vlaki rows lack St_vlaka or Koordinate')
    return data


def _work_days(item: dict) -> tuple[Optional[str], Optional[str]]:
    cas = item.get('Cas')
    match = DAYS.search(' '.join(cas) if isinstance(cas, list) else str(cas or ''))
    if not match:
        return None, None
    d1, m1, y1, d2, m2, y2 = (int(x) for x in match.groups())
    try:
        return date(y1, m1, d1).isoformat(), date(y2, m2, d2).isoformat()
    except ValueError:
        return None, None


def works(page: str) -> list[dict]:
    """The works on the lines: `var roadworks = [...]` of the status page, each item as SŽ has it (Naslov, Cas, Lokacija,
    Koordinate, Relacija, Opis) plus `from` / `to` (ISO days of Cas, None when unreadable)."""
    found = ROADWORKS.search(page)
    if not found:
        raise SiteError('layout', 'var roadworks is missing')
    try:
        raw, _ = json.JSONDecoder().raw_decode(page, found.end())
    except ValueError as e:
        raise SiteError('layout', 'var roadworks is not JSON') from e
    if not isinstance(raw, list) or not all(isinstance(w, dict) for w in raw):
        raise SiteError('layout', 'var roadworks is not a list of works')
    return [{**w, **dict(zip(('from', 'to'), _work_days(w)))} for w in raw]


def delays(page: str) -> list[dict]:
    """The delays the status page highlights (#zamude, tables of class `delays`): {'station', 'relation', 'train'
    ('LPV 2418'), 'text' ('45 min V ODHODU'), 'minutes', 'event' ('departure' | 'arrival' | None), 'over30'}."""
    start = page.find('id="zamude"')
    out = []
    for attrs, body in TABLE.findall(page[start:] if start >= 0 else ''):
        if not re.search(r'\bdelays\b', attrs):
            continue
        for row in ROW.findall(body):
            cells = [_plain(c) for kind, c in CELL.findall(row) if kind == 'd']
            if len(cells) < 4:
                continue
            station, relation, train, text = cells[:4]
            minutes = re.search(r'(\d+)\s*min', text)
            event = 'departure' if 'ODHOD' in text.upper() else 'arrival' if 'PRIHOD' in text.upper() else None
            out.append({'station': station, 'relation': relation, 'train': train, 'text': text,
                        'minutes': int(minutes.group(1)) if minutes else None, 'event': event, 'over30': 'over-30' in attrs})
    return out


def status_page(page: str) -> dict:
    """{'notices', 'works', 'delays'} of the status page (WordPress page 438, the one that was saved by hand):
    notices exactly as `sz_list.parse` reads them, so `sz_list.save` takes them."""
    if 'nadomestni-prevozi' not in page:
        raise SiteError('layout', 'the notices section (nadomestni-prevozi) is missing')
    notices = sz_list.parse(page)
    if not notices:
        raise SiteError('layout', 'no notices could be read')
    return {'notices': notices, 'works': works(page), 'delays': delays(page)}


def _header(text: str) -> str:
    return mapping.fold(_plain(text)).rstrip('*').strip()


def departures(page: str) -> dict:
    """A station board: {'code', 'name', 'rows': [{'train', 'track', 'planned', 'kind', 'relation', 'expected'}]}. The
    two tables are told apart by their `Predvideno` column (arrivals only); rows are kept with an empty train number
    or track as SŽ shows them."""
    chosen = OPTION.search(page)
    if not chosen:
        raise SiteError('layout', 'no selected station')
    rows = []
    tables = 0
    for _, body in TABLE.findall(page):
        head = ROW.search(body)
        names = [_header(c) for kind, c in CELL.findall(head.group(1)) if kind == 'h'] if head else []
        if not any(n == 'tir' for n in names):
            continue
        tables += 1
        arrival = 'predvideno' in names
        index = {name: i for i, name in enumerate(names)}
        train_at = next((i for n, i in index.items() if n.startswith('st. vlaka')), None)
        for row in ROW.findall(body)[1:]:
            cells = [_plain(c) for kind, c in CELL.findall(row) if kind == 'd']
            if len(cells) < len(names) or train_at is None:
                continue
            relation_at = next((i for n, i in index.items() if n.startswith('relacija')), None)
            rows.append({'train': cells[train_at], 'track': cells[index['tir']], 'planned': cells[index.get('nacrtovano', 0)],
                         'kind': 'arrival' if arrival else 'departure', 'relation': cells[relation_at] if relation_at is not None else '',
                         'expected': cells[index['predvideno']] if arrival else ''})
    if not tables:
        raise SiteError('layout', 'no table with a Tir column')
    return {'code': chosen.group(1), 'name': _plain(chosen.group(2)), 'rows': rows}


def train_sets(page: str) -> dict[str, dict]:
    """The planned train set of each train in a timetable-finder answer: {train number: {'set': name, 'slug': slug}}
    (slug of its /train/<slug>/ page). A block belongs to the nearest "Vlak: IC 512" before it."""
    labels = [(m.start(), m.group(1)) for m in TRAIN_LABEL.finditer(page)]
    out = {}
    for block in SET_BLOCK.finditer(page):
        before = [name for at, name in labels if at < block.start()]
        number = re.search(r'\d+', before[-1]) if before else None
        if number:
            out[number.group(0)] = {'set': _plain(block.group(1)), 'slug': block.group(2)}
    if not out:
        raise SiteError('layout', 'no train sets found')
    return out
