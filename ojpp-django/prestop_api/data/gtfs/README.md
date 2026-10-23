# Hand-kept city bus timetables

Each folder is one OTP feed (`Sevnica` → ids `Sevnica:…`), as plain GTFS text files. `supplement.py`
reads them instead of OTP's copy of that feed for lines, trips and stop boards (journeys still come
from OTP). Keep the stop, route and trip ids of OTP's feed where they exist, so stops and saved lines
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
