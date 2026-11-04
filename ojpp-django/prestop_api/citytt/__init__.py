"""City bus timetables nobody publishes as GTFS, read from the operator's own pages into hand-kept feeds.

`manage.py city_timetables` reads each town's timetables (one reader per kind of source), puts every stop on the
pole the national feed or OpenStreetMap has for it (poles.py), routes the shapes on the roads and writes GTFS text
files into `data/gtfs/<feed>/`, which supplement.py reads like Sevnica's: boards, lines, trips and the map. A build
that fails its checks leaves the last good folder in place and says why in its `status.json` (/health).

Sources (docs/research/2026-10-23-city-bus-sources.md):
- Jesenice: Arriva's city lines 1A, 1B, 2A, 2B, one Word-table PDF each (arriva.py). arriva.si answers only from
  Slovenia (403 from the Oracle server in Milan, Globalping 2026-10-23), so the command runs on a PC in Slovenia
  (`yarn city-timetables`) and the folder is committed; the server never fetches it.
- Maribor: Marprom's published feed ends its weekday service 2026-08-31 and nothing follows it, but each line's page links
  next September's timetables as PDFs, one per direction and stop (marprom.py). The weekday trips are rebuilt from those
  pages; the published Saturday and Sunday trips stay. marprom.py fetches and builds on its own (`run`), since it needs
  no pole matching or routing: no OTP, Overpass or Valhalla.

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
    # Cities whose timetables are several services (Piran): (service id, weekdays Monday … Sunday, runs on public
    # holidays). Each service gets its own calendar rows; `weekdays`/`holidays_too` are then unused.
    services: tuple = ()
    pages: tuple = ()      # more pages whose timetable links count too (a news post linking a file the page lacks)
    files: tuple = ()      # the exact file names to read: the build reports one that vanished or a new one it does not know
    stale: tuple = ()      # names of old files the pages still link: ignored
    names: tuple = ()      # (the timetable's spelling, its pole's name) where the timetable spells a stop its own way
    unplaced: tuple = ()   # stops no source has a pole for: left out of the runs (status notes list them)


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
    'Piran': City(
        feed='Piran', name='Piran',
        page='https://arriva.si/avtobusni-prevozi/mestni-avtobusni-prevozi/mestni-avtobusni-prevozi-piran/vozni-red-in-cenik-piran/',
        # The Saturday file is linked from the news post only (2026-11-04); the page lists the other three.
        pages=('https://arriva.si/en/changes-to-piran-urban-transport-timetables-effective-november-1-2026/',),
        links=r'https://arriva\.si/wp-content/uploads/[^"\'\s]+/(?:Linija|Line)-1\.1\.[12][^"\'\s]*\.pdf',
        files=('Linija-1.1.1_POPE.pdf', 'Line-1.1.1._Sat_1.11.2026.pdf', 'Linija-1.1.1._NP_1.11.2026.pdf', 'Linija-1.1.2-.pdf'),
        stale=('Line-1.1.1_SAT-1.pdf', 'Line-1.1.1_SH-1.pdf', 'Line-1.1.1_MON-FRI.pdf', 'Linija-1.1.1_SOB-1.pdf',
               'Line-1.1.1._SH_1.11.2026.pdf'),
        reader='arriva_grid',
        days='Vozni redi veljajo od 1. 11. 2026 do 31. 3. 2027.',
        weekdays=(1, 1, 1, 1, 1, 1, 1), holidays_too=(),
        # The files print "1.XI.–31.III." and the page says valid until 31 March 2027: check the page again then.
        start=date(2026, 11, 1), end=date(2027, 3, 31),
        agency=('arriva', 'Arriva d.o.o.', 'https://arriva.si/'),
        bbox=(45.48, 13.55, 45.55, 13.64),
        names=(('Bernardin kr.', 'Bernardin K'),),
        # Neither IJPP nor OSM has a pole for these two (Liminjanska cesta, Lucija, on runs from TC Tuš), 2026-11-04.
        unplaced=('Liminjanska I', 'Liminjanska II'),
        # D = workdays Mon-Fri, PESO = Fridays (the Saturday file prints the Saturday runs itself), SO = Saturdays,
        # NP = Sundays and public holidays, SONP = Saturdays, Sundays and public holidays, V = every day. Public
        # holidays run only the services flagged True.
        services=(('D', (1, 1, 1, 1, 1, 0, 0), False), ('FRI', (0, 0, 0, 0, 1, 0, 0), False), ('SO', (0, 0, 0, 0, 0, 1, 0), False),
                  ('NP', (0, 0, 0, 0, 0, 0, 1), True), ('SONP', (0, 0, 0, 0, 0, 1, 1), True), ('V', (1, 1, 1, 1, 1, 1, 1), True)),
    ),
    'MARPROM': City(
        feed='MARPROM', name='Maribor',
        page='https://www.marprom.si/koda-linije_nova/{line}_nova/',   # one page per line: {line} is its code in lower case
        links=r'(https?://www\.marprom\.si/dokumentacija/[^"\'\s<>]*/PVR{line}-(\d{8})_(plus|minus)\.pdf)',
        reader='marprom',
        days='',               # unused: the PDFs name their own days and the ŠP (school holiday) dates
        weekdays=(1, 1, 1, 1, 1, 0, 0), holidays_too=(),
        # The PDFs start on 2026-09-01 and have no end; their ŠP list reaches 2027-08-31. The feed's real end is the
        # calendar's (Saturday and Sunday only run on when the PDFs agree with the published ones): see marprom.compose.
        start=date(2026, 9, 1), end=date(2027, 8, 31),
        agency=('3', 'Marprom', 'https://marprom.si'),
        bbox=(46.45, 15.45, 46.70, 15.85),
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
