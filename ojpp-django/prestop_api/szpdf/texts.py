"""The words printed around SŽ's timetable tables: validity, footnote wordings, direction headings, stop lists.

Pure string functions, so the wordings SŽ uses can be tested without a PDF.
"""
import re
import unicodedata
from datetime import date


def fold(text: str) -> str:
    """Lower case, no diacritics, single spaces: for comparing wordings."""
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text.replace('–', '-')).strip().lower()


def _days(text: str, year: int | None = None) -> tuple[list[date] | None, bool]:
    """The dates written in `text` ("10., 11., 17. 10. ter 24. in 25. 10. 2026") and whether it is a range
    ("Od … do …"). A month or year applies to every day before it that has none, `year` to days without one;
    None if unreadable."""
    items: list[list] = []
    after_number = False
    ranged = False
    for tok in re.findall(r'\d+|\bdo\b|[,;]|\bin\b|\bter\b|[a-zčšž]+', fold(text)):
        if not tok.isdigit():
            ranged |= tok == 'do'
            if tok not in (',', ';', 'in', 'ter', 'do', 'od'):
                return None, False
            after_number = False
            continue
        n = int(tok)
        if len(tok) == 4:
            for it in items:
                it[2] = it[2] or n
        elif after_number and items and items[-1][1] is None:
            for it in items:
                it[1] = it[1] or n
        else:
            items.append([n, None, None])
        after_number = True
    try:
        days = [date(y or year, m, d) for d, m, y in items]
    except (TypeError, ValueError):
        return None, False
    return days or None, ranged


def validity(text: str) -> dict | None:
    """"Velja v dneh" → {'from', 'to', 'dates'}: a range has dates None, a list of days names each day."""
    days, ranged = _days(text)
    if not days or (ranged and len(days) != 2) or days != sorted(days):
        return None
    iso = [d.isoformat() for d in days]
    return {'from': iso[0], 'to': iso[-1], 'dates': None if ranged else iso}


_RULES = [
    (r'ne vozi ob sobotah, nedeljah in praznikih( - dela prostih dneh v rs)?', 'workdays'),
    (r'vozi le ob delovnikih', 'workdays'),
    (r'vozi ob sobotah, nedeljah in praznikih( - dela prostih dneh v rs)?', 'weekends_holidays'),
    (r'ne vozi ob sobotah', 'not_saturday'),
    (r'vozi ob nedeljah', 'sundays'),
    # Information only (the bus runs every day of the timetable):
    (r'prevoz se opravi preko (preko )?mejnega prehoda [a-z]+', 'info'),
    (r'vlak st\. \d+ vozi do postajalisca [a-z ]+\. potniki v smeri [a-z ]+ prestopijo na postaji [a-z ]+!?', 'info'),
]
_TRAIN_RUNS = re.compile(r'dne (?P<days>[\d. ,]+(?:(?:in|ter) [\d. ,]+)*) se nadomestni prevoz ne opravlja; vozi vlak!?')


def footnote_rule(text: str, valid_from: date) -> tuple[str | None, list[str] | None]:
    """A footnote's wording → (rule, dates). Only wordings seen in SŽ's PDFs are known; others give (None, None)."""
    folded = fold(text).rstrip('.').strip()
    for pattern, rule in _RULES:
        if re.fullmatch(pattern, folded):
            return rule, None
    m = _TRAIN_RUNS.fullmatch(folded)
    if m:
        # "dne 19. 10." has no year: the one that puts it on or after the timetable's first day.
        days, _ = _days(m['days'].strip(), valid_from.year)
        if days:
            days = [d if d >= valid_from else d.replace(year=d.year + 1) for d in days]
            return 'train_runs_on', [d.isoformat() for d in days]
    return None, None


# ---------------------------------------------------------------- the blocks around the tables

BOILERPLATE = [
    r'LOKACIJE POSTANKOV NADOMESTNIH PREVOZOV NA ZEMLJEVIDU:?',
    r'LOCATIONS OF RAIL REPLACEMENT BUS STOPS ON THE MAP:?',
    r'potniski\.sz\.si/vozni-redi/lokacije-postankov-nadomestnih-prevozov',
]
TITLES = ('vozni red nadomestnih prevozov', 'timetable of replacement bus services',
          'vozni red povezovalnih avtobusnih prevozov', 'timetable of connecting bus services')
HEADINGS = {
    'velja v dneh': 'valid',
    'smer / direction': 'direction',
    'opomba / notice': 'footnotes',
    'postanki nadomestnih prevozov': 'stops',
    'legenda / legend': 'legend',
    'dodatne informacije': 'notes',
}
FOOTNOTE = re.compile(r'(\d+)\s*[-–]\s*(.+)')
STARRED = re.compile(r'(\*+)\s*(.+)')
STOP = re.compile(r'([A-ZČŠŽĆĐ][A-ZČŠŽĆĐ .,]*?)\s*[-–:]\s*(.+)')
EARLIER = re.compile(r'(\d+)\s*minut\w*\s+pred')


def slovene(text: str) -> str:
    """The Slovene half of "slovensko / English"."""
    return text.split(' / ')[0].strip()


def heading_of(text: str) -> str | None:
    f = fold(text)
    return next((kind for start, kind in HEADINGS.items() if f.startswith(start)), None)


def clean(text: str) -> str:
    for pattern in BOILERPLATE:
        text = re.sub(pattern, '', text)
    return ' '.join(text.split())


def blocks(lines: list) -> dict:
    """Walk the text lines in reading order. `lines` have .page .top .x0 .text .red .blue (layout.Line)."""
    out = {'valid': [], 'directions': [], 'footnotes': [], 'starred': [], 'unnumbered': [], 'stops': [],
           'stationNotes': [], 'notes': [], 'additional_legend': False, 'connecting': False}
    state = None
    pending_direction = []
    for line in sorted(lines, key=lambda l: (l.page, round(l.top), l.x0)):
        text = clean(line.text)
        if not text:
            continue
        f = fold(text)
        if f.startswith(TITLES):
            out['connecting'] |= 'povezovalnih' in f
            continue
        kind = heading_of(text)
        if kind == 'valid':
            out['valid'].append(text.split(':', 1)[1].strip() if ':' in text else '')
            continue
        if kind == 'direction':
            pending_direction.append(line)
            continue
        if kind:
            state = kind
            continue
        heading = next((h for h in pending_direction if h.page == line.page and abs(h.x0 - line.x0) < 20
                        and 0 < line.top - h.top < 30), None)
        if heading is not None:
            pending_direction.remove(heading)
            out['directions'].append(line)
            continue
        if state == 'footnotes':
            if f.startswith('dodatne linije'):
                out['additional_legend'] = True
                out['notes'].append(text)
            elif (m := FOOTNOTE.fullmatch(text)):
                out['footnotes'].append((m[1], m[2].strip()))
            elif (m := STARRED.fullmatch(text)):
                out['starred'].append((m[1], m[2].strip()))
            else:
                out['unnumbered'].append((text, line.red))
        elif state == 'stops':
            _stop_line(out, text)
        elif state == 'legend':
            continue
        else:
            out['notes'].append(text)
    return out


def _stop_line(out: dict, text: str):
    """A POSTANKI line: "KRANJ – postanek pred postajo", "DIVAČA, HRPELJE KOZINA - …", a station note
    ("*Za postajo PODNART …", tied to the stop line ending in the same stars, else the one before), or the
    continuation of the line before."""
    if (m := STARRED.fullmatch(text)):
        stars = m[1]
        tagged = [s for s in out['stops'] if s.get('_stars') == stars]
        station = (tagged[-1] if tagged else out['stops'][-1])['station'] if out['stops'] else None
        out['stationNotes'].append({'station': station, 'text': m[2].strip()})
        out['_last'] = 'note'
        return
    m = STOP.fullmatch(text)
    if m and not re.search(r'[a-zčšžćđ]', m[1]):
        body = m[2].strip()
        stars = re.search(r'\*+$', body)
        body = body[:stars.start()].strip() if stars else body
        for name in (n.strip() for n in m[1].split(',')):
            if name:
                out['stops'].append({'station': name, 'text': body, **({'_stars': stars[0]} if stars else {})})
        out['_last'] = 'stop'
        return
    wrapped = re.match(r'[-–]\s*(.+)', text)
    tail = re.fullmatch(r'(.*?\S)\s+((?:[A-ZČŠŽĆĐ]{2,}\s?)+)', out['stops'][-1]['text']) if out['stops'] else None
    if out.get('_last') == 'note':
        out['stationNotes'][-1]['text'] += ' ' + text
    elif wrapped and tail:
        # The next stop's name printed at the end of the line before, its description on this line (11188).
        out['stops'][-1]['text'] = tail[1]
        out['stops'].append({'station': tail[2].strip(), 'text': wrapped[1].strip()})
    elif out['stops']:
        out['stops'][-1]['text'] += ' ' + text
    else:
        out['notes'].append(text)


def finish_stops(out: dict) -> tuple[list[dict], list[dict]]:
    stops = [{'station': s['station'], 'text': s['text']} for s in out['stops']]
    notes = []
    for n in out['stationNotes']:
        m = EARLIER.search(fold(n['text']))
        notes.append({'station': n['station'], 'text': n['text'], 'minutesEarlier': int(m[1]) if m else None})
    return stops, notes


def direction_text(text: str) -> str:
    text = re.sub(r'\s*in obratno\s*/\s*and vice versa\s*$', '', text, flags=re.I)
    return text.strip().rstrip('-–').strip()
