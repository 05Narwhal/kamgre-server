# Owned transit backend

`ojpp-django/` is the exact upstream source pinned by the approved backend plan. See [provenance](UPSTREAM.md) and [implementation progress](../docs/implementation-progress.md).

## Run locally with real data (WSL, no Docker)

The upstream Django app runs unmodified inside the `kali-linux` WSL distro, against a dedicated PostgreSQL 18 + PostGIS 3.6 cluster (`18/prestop`, port 5433) and Redis. Prestop additions live beside upstream code:

- `ojpp_core/settings_prestop.py`: settings overlay (database port, CORS for Vite, no credentials needed at startup).
- `prestop_api/`: the `/api/v1` facade the React app's live mode uses (see [Live data](#live-data-apiv1)).
- `prestop_statistics/`: `collect_delays` records observed delays per trip for the Reliability screen.
- `prestop_data/`: `import_gtfs` loads the public GTFS mirror at <http://gtfs.derp.si/> (the OJPP authors' feed mirror) into OJPP's own tables; `run_ingestion` runs only configured, credential-free upstream jobs.
- `ojpp_core/urls_prestop.py`: upstream URLs plus `/api/v1/`; upstream `urls.py` is unchanged.
- `local/ojpp.sh`: wrapper for the commands below. Local config is in `ojpp-django/.env` (git-ignored).

From the repository root in Windows, the quick way:

```powershell
yarn backend    # starts PostGIS + Redis, stops any running server/collector, then opens two windows: API server and delay collector
yarn dev:live   # in the same terminal: the app with live data
```

The individual commands (`up` is needed once per WSL boot, e.g. after a reboot or `wsl --shutdown`; repeating it is harmless):

```sh
wsl -d kali-linux -u root -- bash backend/local/ojpp.sh up        # start PostGIS + Redis (after a WSL restart)
wsl -d kali-linux -- bash backend/local/ojpp.sh serve             # http://localhost:8066, Prestop API at /api/v1
wsl -d kali-linux -- bash backend/local/ojpp.sh stop              # stop a running API server and collector
wsl -d kali-linux -- bash backend/local/ojpp.sh collect           # delay statistics: polls trip updates every 60 s
wsl -d kali-linux -- bash backend/local/ojpp.sh ingest            # OJPP's own LPP vehicle history + GTFS refresh at 04:30
wsl -d kali-linux -- bash backend/local/ojpp.sh manage import_gtfs           # refresh ijpp + lpp now (skips unchanged files)
wsl -d kali-linux -- bash backend/local/ojpp.sh manage test prestop_api prestop_statistics prestop_data
```

Then run the app against it with `yarn dev:live` (any shell; it loads `.env.live`). Vite proxies `/api/v1` to `http://localhost:8066` (override with `PRESTOP_API_TARGET`).

Useful upstream pages and endpoints: `/operators`, `/routes`, `/stops`, `/map`, `/api/stop_locations`, `/api/stop_locations/<id>/arrivals?date=YYYY-MM-DD`, `/api/vehicle_locations`, `/api/` (DRF), `/admin/` (create a user with `manage createsuperuser`).

### What data is real

| Source | Content | Credentials |
| --- | --- | --- |
| `ijpp_gtfs.zip` (NAP national GTFS, mirrored daily) | 9 operators incl. Arriva, Nomago, SŽ trains, LPP regional; stops, routes, trips with shapes, stop times, service days | none |
| `lpp_gtfs.zip` (LPP official GTFS) | Ljubljana city buses: stops, routes with colours, trips, stop times | none |
| `lpp.ojpp.derp.si` | LPP live bus positions (upstream `lpp_update_locations`) | none |
| NAP SIRI / IJPP SOAP | national live positions, upstream timetable import | NAP B2B account (`IJPP_LOGIN`) and generated NeTEx/SIRI bindings; not enabled |
| Marprom | Maribor | upstream API host not reachable; not enabled |

Import semantics: GTFS ids are kept feed-qualified in `prestop_data.GtfsRef`; IJPP ids also fill upstream `ijpp_id` fields and LPP station codes fill `lpp_id`, so rows created by upstream adapters are adopted, not duplicated. Re-imports update in place, deactivate trips that left the feed, and rewrite stop times only for changed trips, so vehicle history is kept. Each GTFS service becomes a schedule with explicit running dates. OJPP stores stop times as wall-clock `TimeField`, so GTFS times after 24:00 wrap (e.g. `24:40` → `00:40`) and belong to the previous service day.

## Live data (/api/v1)

The facade reads the same public services brezavta.si uses, both run by the OJPP authors ([derp-si](https://gitlab.com/derp-si)):

| Source | What it gives Prestop | Cache |
| --- | --- | --- |
| OpenTripPlanner GTFS GraphQL, `otp.ojpp-gateway.derp.si` (fails over to `otp1`/`otp2`) | 15 feeds: IJPP national (Arriva, Nomago, SŽ trains, LPP regional, AP Murska Sobota), LPP, Marprom, Kranj, Celje, Koper, Nova Gorica, Novo mesto, Velenje, Ptuj, Postojna, Murska Sobota, Krško, Brežice, Sevnica. Stops, departure boards and journeys with realtime already applied, service alerts (incl. SŽ disruptions and replacement buses), bike and scooter sharing | stops/routes 1 h, alerts and rentals 60 s, boards and journeys per request |
| Combined GTFS-Realtime, `rt.gtfs.ijpp.prometko.si/combined/rt/{vl,tu}` (built by [gtfs-rt-aggregator](https://gitlab.com/derp-si/gtfs-rt-aggregator)) | vehicle positions and trip updates; trip ids match OTP (635/636 live trips resolved when checked) | 5 s / 10 s |
| Pelias `pelias.ojpp.derp.si`, Photon as fallback | addresses and places for the planner | per request |

Caches serve the last good value while refreshing in the background. If a source keeps failing, responses are marked `stale` and then become `503 UPSTREAM_UNAVAILABLE` (retryable). `GET /api/v1/health` reports database readiness and each source's freshness.

Endpoints follow `src/contracts/transit.ts` and `contracts/prestop.openapi.yaml`: `capabilities`, `locale`, `places`, `stops` (paged, 4,000 per page), `stops/{id}/board`, `vehicles` (also `?routeId=` for every vehicle on a line; vehicles carry `tripId`, `speed`, `nextStopId`, `stopped` as motion hints), `rentals`, `journeys` (POST; OTP `planConnection` with native via points and the minimum transfer as slack), `trips?ids=` and `trips/{id}` (shape simplified to ≤ 400 points, each stop's distance along it, live times from `stoptimesForDate`, learned running time to the next stop; static parts cached 6 h, times 15 s; `geometry=0` omits shapes), `lines/{id}` (every pattern with shape, stops and today's trip count), `alerts`, `statistics/routes`, `statistics/routes/{id}/daily`, `statistics/reliability?routeIds=`. Settings live in `ojpp_core/settings_prestop.py`: `PRESTOP_OTP_URLS`, `PRESTOP_RT_*`, `PRESTOP_PELIAS_URL`, `PRESTOP_TRUSTED_COUNTRY_HEADER`, `PRESTOP_INSANE_MODE` (default on).

Statistics: `collect_delays` keeps one row per trip and service day with the provider's last reported delay at each stop whose time has passed (quality `observed`). Trips weigh equally; days without measurements are `no_data` with null metrics; days before the planner's timetable window have unknown scheduled counts. Each row also stores the observed running time between consecutive recorded stops (`segments`, arrival to arrival: scheduled difference plus the change in delay). Per route, the median over the last 21 days (segments with ≥ 3 trips) is the *typical running time* the app uses to predict vehicle positions and arrival times. `statistics/reliability` summarises the last 30 days per route: trip-weighted mean signed and late delay, the share of trips averaging under 3 minutes late, and the signed mean by hour of day (from when the trip was first seen). The collector must be running for any of this to fill (`yarn backend` starts it).

### Known gaps

- **SŽ train delays**: the combined feed carries SŽ trip updates only while its SŽ adapter's upstream (`api.modra.ninja/sz/lokacije`, used by derp-si's [ijpp-rt](https://gitlab.com/derp-si/ijpp-rt)) answers. It timed out on 2026-10-09, so trains show scheduled times; brezavta.si has the same gap. SŽ's own site is behind a bot challenge and is not scraped. Train notices and replacement buses do come through, and train delays appear automatically once that upstream is back.
- Trains have no GPS positions in any public feed; buses from IJPP, LPP, Marprom, Kranj and Celje do.
- Insane mode is on by default (`PRESTOP_INSANE_MODE=false` turns it off): slack 0, transfer cost 0, walking at 1.75 m/s. `journeys` also takes `operators` (agency ids) as an OTP include filter; `places` resolves pasted coordinates and Google Maps links (short links only via Google hosts).
- Terms: the mirrors are free to use without guarantee, and reusing the data needs agreement with each provider (gtfs.derp.si README). Settle this before a public launch.
