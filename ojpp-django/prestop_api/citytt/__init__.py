"""City bus timetables nobody publishes as GTFS, read from the operator's own pages into hand-kept feeds.

`manage.py city_timetables` reads each town's timetables (one reader per kind of source), puts every stop on the
pole the national feed or OpenStreetMap has for it (poles.py), routes the shapes on the roads and writes GTFS text
files into `data/gtfs/<feed>/`, which supplement.py reads like Sevnica's: boards, lines, trips and the map. A build
that fails its checks leaves the last good folder in place and says why in its `status.json` (/health).

Sources (docs/research/2026-10-23-city-bus-sources.md):
- Jesenice: Arriva's city lines 1A, 1B, 2A, 2B, one Word-table PDF each (arriva.py). arriva.si answers only from
  Slovenia (403 from the Oracle server in Milan, Globalping 2026-10-23), so the command runs on a PC in Slovenia
  (`yarn city-timetables`) and the folder is committed; the server never fetches it.

Only the command and the tests import the readers (pdfplumber is heavy); the API reads `health()` alone.
"""
import json
from dataclasses import dataclass
from datetime import date

from .. import supplement


@dataclass(frozen=True)
class City:
    feed: str              # feed id: data/gtfs/<feed>/, stop ids '<feed>:…'
    name: str
    page: str              # the operator's page listing the timetables
    links: str             # regex of the timetable files' links on it
    reader: str            # module in this package that reads one file
    days: str              # the page's sentence on running days: checked on every build, the calendar follows it
    weekdays: tuple        # Monday … Sunday: runs that day
    holidays_too: tuple    # (month, day) of public holidays it runs on anyway
    start: date
    end: date
    agency: tuple          # (id, name, url): the name matches the operator's in IJPP (operators.py merges them)
    bbox: tuple            # (south, west, north, east): every stop lies inside


CITIES = {
    'Jesenice': City(
        feed='Jesenice', name='Jesenice',
        page='https://arriva.si/avtobusni-prevozi/mestni-avtobusni-prevozi/mestni-avtobusni-prevozi-jesenice/vozni-redi-in-cenik-jesenice/',
        links=r'https://arriva\.si/wp-content/uploads/[^"\'\s]+/Linija-[^"\'\s]+\.pdf',
        reader='arriva',
        days='Krožni liniji obratujeta od ponedeljka do vključno sobote, brez nedelj in praznikov, razen 31. 10. in 1. 11.',
        weekdays=(1, 1, 1, 1, 1, 1, 0), holidays_too=((10, 31), (11, 1)),
        # The PDFs print no validity. The municipality's contract for the lines runs 1. 10. 2025 – 24. 6. 2027
        # (EU tender notice): check the page again before the end.
        start=date(2025, 10, 1), end=date(2027, 6, 24),
        agency=('arriva', 'Arriva d.o.o.', 'https://arriva.si/'),
        bbox=(46.40, 13.96, 46.49, 14.13),
    ),
}

STATUS = 'status.json'
EXPIRING = 14  # days before a feed's end date that /health calls it stale


def health(today: date) -> list[dict]:
    """A /health source per city: live while the last build passed and its calendar covers the next EXPIRING days,
    stale after a failed build or near its end, unavailable without a folder. updatedAt: when the files last changed."""
    out = []
    for city in CITIES.values():
        try:
            status = json.loads((supplement.LOCAL_GTFS / city.feed / STATUS).read_text(encoding='utf-8'))
            end = date.fromisoformat(status['end'])
        except (OSError, ValueError, KeyError, TypeError):
            status, end = None, None
        if not status:
            state, updated = 'unavailable', None
        else:
            ok = status.get('status') == 'ok' and (end - today).days >= EXPIRING
            state, updated = 'live' if ok else 'stale', f'{status["built"]}T00:00:00Z' if status.get('built') else None
        out.append({'id': f'city-timetables:{city.feed}', 'name': f'{city.name} city buses ({city.agency[1]} timetables)',
                    'status': state, 'updatedAt': updated, 'capabilities': ['boards', 'vehicles']})
    return out
