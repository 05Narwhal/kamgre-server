# Hand-kept city bus timetables

Each folder is one OTP feed (`Sevnica` → ids `Sevnica:…`), as plain GTFS text files. `supplement.py`
reads them instead of OTP's copy of that feed for lines, trips and stop boards; `city_journeys.py`
adds their runs to OTP's journeys. Keep the stop, route and trip ids of OTP's feed where they exist, so stops and saved lines
keep working; new stops get new ids.

## Sevnica

- Source: Občina Sevnica, "Vozni red mestnega busa Sevnica–Boštanj–Sevnica",
  <https://www.obcina-sevnica.si/sl/za-obcane/vozni-redi/mestni-bus-sevnica%E2%80%93bostanj-sevnica/>
  (read 2026-10-12: "Vozni red velja od 1. 9. 2026", Monday to Friday except public holidays, free).
- OTP's copy (AddTransit, `gtfs.derp.si/sevnica_manual.zip`) ended 2026-06-24, and its runs at 10:00
  and 11:00 still went round Boštanj by INPOS first; since September they go by the Tuš roundabout.
- The page gives no end date. The previous timetable ran with the school year, so this one ends
  2027-06-24: check the page again in June (and on each school year) and extend `calendar.txt`.
- Route 2 is the cemetery run, on the first Friday of each month (dates in `calendar_dates.txt`).
- Stops and shape 1–17 come from the AddTransit file. Approximate points (no public coordinates):
  18 Vila Planinska (on Planinska cesta), 20 Pokopališče (the cemetery). 19 Tuš rondo is the OSM bus
  stop by the roundabout (node 11181960230). Trips without a shape are routed on the roads (roads.py).

## Jesenice

Written by `manage.py city_timetables` (prestop_api/citytt), not by hand: run `yarn city-timetables` on a PC in
Slovenia (arriva.si refuses other countries, the server included), check the summary and commit the folder.
`--check` builds and compares without writing. `status.json` records the source files and the last result;
/health shows `city-timetables:Jesenice` as stale after a failed build or 14 days before the end date.

- Source: Arriva, "Mestni avtobusni prevozi Jesenice", one PDF per line (1A, 1B, 2A, 2B) on
  <https://arriva.si/avtobusni-prevozi/mestni-avtobusni-prevozi/mestni-avtobusni-prevozi-jesenice/vozni-redi-in-cenik-jesenice/>
  (read 2026-10-23; the PDFs print no validity, uploaded 2025-06).
- Days, from the page's sentence (the build fails when it changes): Monday to Saturday, no Sundays or public
  holidays except 31 October and 1 November. Valid until 2027-06-24, the end of the municipality's contract for
  the lines (EU tender notice): check the page again before then and extend `CITIES` in citytt/__init__.py.
- Stops: the IJPP pole of the same name and direction (stop id = the IJPP stop's number, same position, so the two
  are one marker), else the OpenStreetMap pole (`osm<node>`): Straža, Tomšičeva trgovina, Tomšičeva I and II,
  OŠ Prežihov Voranc, Blejska Dobrava pokopališče. Which pole a direction uses follows OTP's patterns and OSM's
  bus route relations (citytt/poles.py). Shapes are routed with Valhalla.

## MARPROM (Maribor)

Written by `manage.py city_timetables --city MARPROM` (prestop_api/citytt/marprom.py), not by hand; `yarn city-timetables`
rebuilds it (about 60 requests, one a second, and some minutes to read the PDFs). `--check` compares without writing;
/health shows `city-timetables:MARPROM`.

- Why: Marprom's published feed (<https://vozniredi.marprom.si/GTFS/gtfs.zip>) ends its weekday service 8726 on
  2026-08-31 and nothing replaces it, so every stop was empty Monday to Friday from 1 September. Each line's page
  (`marprom.si/koda-linije_nova/<line>_nova/`) links next timetables as `PVR<line>-20260901_plus.pdf` / `_minus.pdf`, one
  page per stop (the site's own `_plus_007.pdf` per stop are skipped). Ids stay the published feed's (stop `192`, route, shapes).
- Weekday trips are rebuilt from the pages (`pdf-weekday`, Monday to Friday; `pdf-holiday` on the ŠP school-holiday ranges
  the PDFs print). A page lists one stop's departures, so a trip is chained from the stops it passes: each departure is
  matched to the one at the next stop that the published run time expects (within 2 min, in order); a departure nothing
  continues ends its trip, one nothing led up to starts a new one. No departure is made up, and a stop whose weekday table
  is empty is passed by. Nothing departs from a trip's last stop, so the PDFs have no page for it: it comes from the published
  trips (the stop they end at after this one, `timepoint=0`, published run time). A direction whose last stop that cannot find
  is listed in `status.json` as `noLastStop`; a trip ending mid-way where no published trip ends stays at its last departure.
  Trip ids are `<line>-<plus|minus>-<wd|sp>-<first stop_code>-<HHMM>`, `-2` for a true duplicate (twin buses).
- Saturday and Sunday keep the published trips (8727, 8728); the summer tables 8726 and 8729 are dropped. They run on to
  the PDFs' end (2027-08-31) only when the PDFs' Saturday and Sunday departures equal the published ones (99.5 %, both
  ways); otherwise they end where the published feed does and /health says stale 14 days before. `status.json` lists
  how far each line agrees.
- Marks on the pages: `<>` is an empty template field (never drawn); `*` after a minute is a line variant, the legend at
  the foot of the page names it ("Vozi do Lesarske šole."): such trips pass a stop the others skip.
- Each file is checked as supplement.py reads it; an unreadable file, a stop code the published feed lacks, or a line
  without weekday trips fails the build and leaves this folder as it was.
