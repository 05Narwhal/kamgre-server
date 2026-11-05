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
  next September's timetables as PDFs, one per direction and stop (marprom.py). The PDFs give each direction's stops
  and the school-holiday dates; the times come from Marprom's interactive timetable (vozniredi.marprom.si, one page
  per stop and sample day). Weekday trips are rebuilt from it; the published Saturday and Sunday trips stay, except a
  line whose weekend there differs, which is rebuilt too. marprom.py fetches and builds on its own (`run`), since it
  needs no pole matching or routing: no OTP, Overpass or Valhalla.

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
    # holidays[, months it runs in]). Each service gets its own calendar rows; `weekdays`/`holidays_too` are then unused.
    services: tuple = ()
    line_services: tuple = ()  # (line, the reader's service, the city's service): one line's day code means another service
    # The folder replaces OTP's feed of the same id (supplement.owns): its stops are the poles, keeping their ids (saved
    # stops and merges keep working), and the national feed's stops are not candidates.
    own_stops: bool = False
    pages: tuple = ()      # more pages whose timetable links count too (a news post linking a file the page lacks)
    files: tuple = ()      # the exact file names to read: the build reports one that vanished or a new one it does not know
    stale: tuple = ()      # names of old files the pages still link: ignored
    names: tuple = ()      # (the timetable's spelling, its pole's name) where the timetable spells a stop its own way
    unplaced: tuple = ()   # stops no source has a pole for: left out of the runs (status notes list them)
    # A correction of OTP's feed of the same id (supplement.py, replaces.txt): (line, 'replace' | 'add' | 'all'). Only these
    # lines are read and OTP keeps the rest; its stops are the poles (set own_stops too).
    replaces: tuple = ()
    only: tuple = ()       # (line, direction, first departures): of that line only these runs are read (an 'add')
    only_services: tuple = ()  # (line, services): of that line only the tables of these services are read
    # (title as the reader gives it, OTP's route id, the number riders know): a reader whose lines are titles (Postojna)
    line_ids: tuple = ()
    unread: tuple = ()     # the reader's lines left out on purpose (they match OTP's)
    breaks: tuple = ()     # (service, ((first, last day), …)): days that service does not run (school holidays)


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
    'Ptuj': City(
        # Replaces OTP's Ptuj feed, a pre-September table for lines 2, 3 and 5 (docs/research/2026-11-04-city-timetables.md).
        feed='Ptuj', name='Ptuj', own_stops=True,
        page='https://arriva.si/avtobusni-prevozi/mestni-avtobusni-prevozi/mestni-avtobusni-prevozi-ptuj/vozni-redi-in-cenik-ptuj/',
        links=r'https://arriva\.si/wp-content/uploads/[^"\'\s]+/Linija-[1-5][^"\'\s]*\.pdf',
        files=('Linija-1_PTUJ_2_01092026.pdf', 'Linija-2_Panorama_1_01092026.pdf', 'Linija-3_Jezero_Spuhlja_1_01092026-ANG.pdf',
               'Linija-4-_Breg_Turnisce_1_01092026.pdf', 'Linija-5_Ljudski-vrt_Rogoznica_2_01092026.pdf'),
        reader='arriva_ocr',
        # The page still says so (2026-11-04), though the files are the 1 Sep 2026 timetables.
        days='Vozni redi veljajo od 10. 2. 2025 naprej.',
        weekdays=(1, 1, 1, 1, 1, 0, 0), holidays_too=(),
        # The files print "01092026" and no end: check the page again before the next school year.
        start=date(2026, 9, 1), end=date(2027, 8, 31),
        agency=('arriva', 'Arriva d.o.o.', 'https://arriva.si/'),
        bbox=(46.38, 15.78, 46.48, 15.95),
        # D = workdays, SO/NEP = Saturdays, Sundays and public holidays (line 1 only), all year; lines 2-5 run on
        # workdays from 1 Sep to 30 Jun only (DS).
        services=(('D', (1, 1, 1, 1, 1, 0, 0), False), ('DS', (1, 1, 1, 1, 1, 0, 0), False, (9, 10, 11, 12, 1, 2, 3, 4, 5, 6)),
                  ('SONP', (0, 0, 0, 0, 0, 1, 1), True)),
        line_services=(('2', 'D', 'DS'), ('3', 'D', 'DS'), ('4', 'D', 'DS'), ('5', 'D', 'DS')),
        # Line 4's row 45 prints "Ptuj Turnišče 02*,04" (no legend for the star): the Turnišče poles, which OTP names alike.
        # OCR'd names too garbled for poles.misread; "Jurčičeva 2" is the other side's pole of "Jurčičeva 1" (OTP names both so).
        names=(('Ptuj Turnisée 02*,04', 'Ptuj Turnišče'), ('Juréigéeva 1', 'Jurčičeva 1'), ('Jurcigéeva 2', 'Jurčičeva 1'),
               ('Villa Monde parkirisce', 'Parking Vila Monde')),
        # Line 2's 07:00 from Krčevina passes "Knjižnica": neither OTP, IJPP nor OSM has a pole by that name (2026-11-04).
        unplaced=('Knjiznica',),
    ),
    'MOKoper': City(
        # A correction of OTP's Koper feed, not a replacement (docs/research/2026-11-04-city-timetables.md): OTP runs
        # line 9 on working days the weekend way (via Žusterna parkirišče), Arriva's table and its 2026/04 route map
        # by PH Sonce; and OTP lacks line 2's 10:55 and 11:55 from Koper. Every other line and day stays OTP's.
        feed='MOKoper', name='Koper', own_stops=True,
        page='https://arriva.si/en/passenger-transport/city-bus-transport/city-transport-koper/timetable-price-list-koper/',
        links=r'https://arriva\.si/wp-content/uploads/[^"\'\s]+/Line-[29]-Koper[^"\'\s]*-annual\.pdf',
        files=('Line-2-Koper-Semedela-Markovec-Hospital-Koper-annual.pdf', 'Line-9-Koper-AP-Passenger-terminal-Koper-AP-annual.pdf'),
        reader='arriva_koper',
        # Line 2's working-day file is the school year's: July and August have their own (2026-11-04).
        days='Timetable (MON – FRI) (July, August)',
        weekdays=(1, 1, 1, 1, 1, 0, 0), holidays_too=(),
        # The files print "Valid from 18.11.2022" and no end: check the page again before the next school year.
        start=date(2026, 9, 1), end=date(2027, 8, 31),
        # OTP's own Koper operator: corrected runs keep the company of the runs they stand in for (one operator filter).
        agency=('MPK', 'Mestni potniški promet Koper', 'https://arriva.si/'),
        bbox=(45.50, 13.68, 45.57, 13.78),
        replaces=(('9', 'replace'), ('2', 'add')),
        only=(('2', 0, ('10:55', '11:55')),),
        # D = working days all year (line 9), DS = working days but July and August (line 2's file says so).
        services=(('D', (1, 1, 1, 1, 1, 0, 0), False), ('DS', (1, 1, 1, 1, 1, 0, 0), False, (9, 10, 11, 12, 1, 2, 3, 4, 5, 6))),
        line_services=(('2', 'D', 'DS'),),
        names=(('Bolnišnica', 'Bol.Izola'), ('Barka II', 'Barka')),
    ),
    'Postojna': City(
        # A correction of OTP's Postojna feed (docs/research/2026-11-04-city-timetables.md): OTP has no Saturday runs of
        # lines 1 and 2 (the poster: Saturday mornings), runs its school lines through the school holidays and 1-5 min
        # off the poster, and lacks Šolska Popoldanska 3. Weekday runs of 1 and 2 and Delavska match: OTP's stay.
        feed='Postojna', name='Postojna', own_stops=True,
        page='https://www.nomago.si/avtobusni-prevozi/mestni-promet/postojna/vozni-red',
        links=r'https://www\.nomago\.si/storage/app/media/mesta/postojna/[^"\'\s]+\.pdf',
        files=('2026_Furman_VozniRed_A_01.pdf',),
        reader='nomago_postojna',
        days='S 1. oktobrom 2026 velja nov vozni red mestnega avtobusa Furman.',
        weekdays=(1, 1, 1, 1, 1, 1, 0), holidays_too=(),
        # The poster prints no end: check the page again before the next school year.
        start=date(2026, 10, 1), end=date(2027, 8, 31),
        agency=('Postojna', 'NOMAGO d.o.o.', 'https://nomago.si'),
        bbox=(45.72, 14.16, 45.81, 14.27),
        line_ids=(('Proga 1', '1', '1'), ('Proga 2', '2', '2'), ('Šolska 1', 'ducu', '4'), ('Šolska 2', '5l2y', '5'),
                  ('Šolska 3', 'mamr', '6'), ('Šolska 4', 'l6ti', '7'), ('Šolska Popoldanska 1,2', 'enzk', '8'),
                  ('Šolska Popoldanska 3', 'pop3', '9')),
        unread=('Delavska',),
        # Šolska 4's 7:32 starts at Raubarkomanda (a request stop) and calls at Javorniška pot 4: no pole in OSM, and OTP's
        # Javorniška pot 4 (Postojna:hj0f) is on no run, so not among the served stops (2026-11-04). The run starts at
        # Javorniška pot 7:40, as OTP's does.
        unplaced=('Raubarkomanda', 'Javorniška pot 4'),
        replaces=(('1', 'add'), ('2', 'add'), ('ducu', 'all'), ('5l2y', 'all'), ('mamr', 'all'), ('l6ti', 'all'),
                  ('enzk', 'all'), ('pop3', 'add')),
        only_services=(('1', ('SO',)), ('2', ('SO',))),
        # SO = Saturdays (lines 1 and 2, the legend's morning window), SOL = school days: working days but the 2026/27
        # school holidays of Notranjsko-kraška (gov.si, "Podrobnejša navodila o šolskem koledarju za OŠ 2026/2027", 5 Feb
        # 2026): autumn, New Year, winter (2nd group), 26 Apr (no lessons), May Day, summer from 25 Jun.
        services=(('SO', (0, 0, 0, 0, 0, 1, 0), False), ('SOL', (1, 1, 1, 1, 1, 0, 0), False)),
        breaks=(('SOL', ((date(2026, 10, 26), date(2026, 10, 30)), (date(2026, 12, 25), date(2027, 1, 2)),
                         (date(2027, 2, 22), date(2027, 2, 26)), (date(2027, 4, 26), date(2027, 5, 2)),
                         (date(2027, 6, 25), date(2027, 8, 31)))),),
        names=(('Kazarje - prihod', 'Kazarje'), ('Pretnarjeva', 'Pretnerjeva'), ('Kolodvorska cesta', 'Kolodvorska'),
               ('Žel. postaja', 'Železniška postaja'), ('Pod jelovico', 'Pod Jelovico'), ('Pod Kolodvorom', 'Pod kolodvorom')),
    ),
    'MARPROM': City(
        feed='MARPROM', name='Maribor',
        page='https://www.marprom.si/koda-linije_nova/{line}_nova/',   # one page per line: {line} is its code in lower case
        links=r'(https?://www\.marprom\.si/dokumentacija/[^"\'\s<>]*/PVR{line}-(\d{8})_(plus|minus)\.pdf)',
        reader='marprom',
        days='',               # unused: the PDFs name their own days and the ŠP (school holiday) dates
        weekdays=(1, 1, 1, 1, 1, 0, 0), holidays_too=(),
        # The PDFs start on 2026-09-01 and have no end; their ŠP list reaches 2027-08-31. The feed's real end is the
        # calendar's (Saturday and Sunday run on when they agree with the site's, or are rebuilt from it): see marprom.compose.
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
