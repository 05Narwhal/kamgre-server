"""Which provider notices concern one leg of a planned journey."""
import re
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .mapping import fold

LOCAL = ZoneInfo('Europe/Ljubljana')

# Notices arrive in the rider's language, so titles are read in Slovenian and English.
# "Prefix: A - B / C (A) in obratno (dates)." → the "A - B / C" part (after the last colon); English "and vice versa".
_SEGMENT = re.compile(r'([^:]+?)\s+(?:in obratno|and vice versa)', re.IGNORECASE)
_COUNTRY = re.compile(r'\((?:a|i|hr)\)', re.IGNORECASE)
_RELATION = re.compile(r'^.*\bna relaciji\s+', re.IGNORECASE)  # "Avtobusni IC prevoz na relaciji Ljubljana - Celje in obratno"
# "(10., 11., 17., 24., 25. oktober)", "(5. - 6. in 19. - 20. oktober)", "(5 - 6 and 19 - 20 October)" — days in one month.
_DAYS = re.compile(r'\(((?:\d{1,2}\.?\s*(?:,|-|in\b|and\b)?\s*)+)([a-z]+)\s*\)')
_MONTHS = (('jan',), ('feb',), ('mar',), ('apr',), ('maj', 'may'), ('jun',), ('jul',), ('avg', 'aug'), ('sep',),
           ('okt', 'oct'), ('nov',), ('dec',))


def title_sections(title: str) -> list[set[str]]:
    """The sides of the section an SŽ notice names, e.g. "Ljubljana / Lesce Bled - Jesenice / Beljak (A)" →
    [{ljubljana, lesce bled}, {jesenice, beljak}] (folded)."""
    m = _SEGMENT.search(title or '')
    if not m or ' - ' not in m.group(1):
        return []
    sides = re.split(r'\s+-\s+', _COUNTRY.sub('', _RELATION.sub('', m.group(1))))
    out = [{fold(n).strip(' .') for n in side.split('/') if n.strip(' .')} for side in sides]
    return [side for side in out if side]


def title_stations(title: str) -> list[str]:
    """Folded station names of an SŽ notice title such as "…: Ljubljana - Ljubljana Šiška in obratno (…)"."""
    m = _SEGMENT.search(title or '')
    if not m or ' - ' not in m.group(1):
        return []
    names = re.split(r'\s+-\s+|\s*/\s*', _COUNTRY.sub('', _RELATION.sub('', m.group(1))))
    return [fold(n).strip(' .') for n in names if n.strip(' .')]


def title_days(title: str, year: int) -> Optional[set[date]]:
    """Days listed in a title ("(10., 11., 17. oktober)"), or None when it gives a range or nothing."""
    m = _DAYS.search(fold(title or ''))
    month = m and next((i for i, names in enumerate(_MONTHS, 1) if m.group(2).startswith(names)), None)
    if not month:
        return None
    days = set()
    for part in re.split(r',|\bin\b|\band\b', m.group(1)):
        numbers = [int(n) for n in re.findall(r'\d{1,2}', part)]
        if len(numbers) == 2 and '-' in part:
            numbers = list(range(numbers[0], numbers[1] + 1))
        days.update(numbers)
    try:
        return {date(year, month, d) for d in days}
    except ValueError:
        return None


def on_listed_day(alert: dict, start: float, end: float) -> bool:
    """False when the title lists days (or the notice its own dates, `_dates`, see closures) and the trip runs on none."""
    if alert.get('_dates') is not None:
        return bool({datetime.fromtimestamp(t, LOCAL).strftime('%Y%m%d') for t in (start, end)} & alert['_dates'])
    first = datetime.fromtimestamp(alert['_from'], LOCAL).date()
    days = title_days(alert['title'], first.year)
    if days is None:
        return True
    # A list in January published in December belongs to the next year.
    days |= {d.replace(year=d.year + 1) for d in days if d < first.replace(day=1)}
    leg_days = {datetime.fromtimestamp(t, LOCAL).date() for t in (start, end)}
    return bool(days & leg_days)


def on_section(alert: dict, stop_names: set[str]) -> bool:
    """False when the title names a section ("Divača - Koper") and the leg touches none of its stations."""
    sides = title_sections(alert['title'])
    return not sides or any(side & stop_names for side in sides)


def concerns(alert: dict, start: float, end: float, stop_names: set[str]) -> bool:
    """Whether a notice already tied to the leg's route or stops (by OTP or its entities) concerns this ride."""
    return on_listed_day(alert, start, end) and on_section(alert, stop_names)


def _overlaps(alert: dict, start: float, end: float) -> bool:
    return alert['_from'] <= end and (alert['_to'] is None or alert['_to'] >= start)


def match(leg: dict, stop_ids: set[str], stop_names: set[str], alerts: list[dict]) -> list[str]:
    """Ids of the alerts in effect during the leg (on a listed day, when the title lists days) that name its route or a
    stop it uses, or (for notices without route/stop entities, and replacement notices for replacement buses) name a
    section it travels. `stop_names` are folded."""
    out = []
    for a in alerts:
        if not _overlaps(a, leg['_start'], leg['_end']) or not on_listed_day(a, leg['_start'], leg['_end']):
            continue
        if leg.get('routeId') in a['routeIds'] or stop_ids & set(a['stopIds']):
            if on_section(a, stop_names):
                out.append(a['id'])
        elif (not a['routeIds'] and not a['stopIds'] and (
                a['operatorId'] == leg.get('operatorId') or leg.get('mode') == 'rail' or leg.get('replacement'))) or (
                # SŽ attaches replacement timetables to the trains; the bus that runs instead travels the same section.
                leg.get('replacement') and a.get('kind') == 'replacement'):
            # On the named section: the leg uses stations on at least two of its sides.
            sides = title_sections(a['title'])
            if sum(1 for side in sides if side & stop_names) >= 2:
                out.append(a['id'])
    return out


# ---------------------------------------------------------------- leg notices (contract legNoticeSchema)

NOTICE_KINDS = ('replacement', 'closure', 'detour', 'stop-moved', 'disruption')
MAX_NOTICES = 3       # per leg
NOTICE_TEXT = 160     # characters of a notice's title kept
_WORDS = {
    'sl': {'bus': 'Avtobus namesto vlaka {train}', 'part': 'Avtobus namesto vlaka {train} na odseku {a} – {b}'},
    'en': {'bus': 'Bus instead of train {train}', 'part': 'Bus instead of train {train} between {a} and {b}'},
}


def _short(text: str) -> str:
    text = ' '.join((text or '').split())
    return text if len(text) <= NOTICE_TEXT else text[:NOTICE_TEXT - 1].rstrip(' ,.;:-') + '…'


def add_notices(journeys: list[dict], alerts: list[dict], lang: str) -> list[dict]:
    """Each leg's short disruption lines (`notices`, besides alertIds): a replacement bus names the train it runs
    instead of, and the stretch when the train runs the rest of the way; a detour, a moved stop or a closure on
    the leg's line says so in the notice's own title, and so does a notice about the train itself (`_leg_notice`:
    zamudil.si's train notices, works on the line) whatever its kind. A train that runs anyway has none (its notice was dropped,
    journey_legs.unreplaced_notices)."""
    words = _WORDS.get(lang, _WORDS['en'])
    by_id = {a['id']: a for a in alerts}
    for journey in journeys:
        trains = {l.get('routeName') for l in journey['legs'] if l['mode'] == 'rail'}
        for leg in journey['legs']:
            out: list[dict] = []
            train = leg.get('replacesTrain')
            if leg['mode'] == 'bus' and leg.get('replacement') and train:
                text = words['part' if train in trains else 'bus'].format(train=train, a=leg['origin']['name'], b=leg['destination']['name'])
                out.append({'kind': 'replacement', 'text': text})
            for alert_id in leg.get('alertIds') or []:
                alert = by_id.get(alert_id) or {}
                kind = alert.get('kind')
                if (kind not in NOTICE_KINDS and not alert.get('_leg_notice')) or (out and kind in ('replacement', 'closure') and leg.get('replacement')):
                    continue  # the bus already says what it replaces
                out.append({'kind': kind, 'text': _short(alert.get('title') or alert.get('message') or '')})
            seen, notices = set(), []
            for n in out:
                if n['text'] and n['text'] not in seen:
                    seen.add(n['text'])
                    notices.append(n)
            if notices:
                leg['notices'] = notices[:MAX_NOTICES]
            else:
                leg.pop('notices', None)
    return journeys
