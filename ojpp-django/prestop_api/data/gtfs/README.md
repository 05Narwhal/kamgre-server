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
