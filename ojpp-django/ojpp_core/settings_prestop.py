"""Prestop overlay on the upstream OJPP settings.

Upstream `settings.py` is left untouched. This overlay lets the server start
without NAP/IJPP credentials (only the public GTFS mirror and the public LPP
proxy are used locally), reads a database port, and registers Prestop apps.
"""
import os
import sys

# Upstream splits IJPP_LOGIN on ':' and reads LPP_API_KEY at import time.
# Feeds that need them stay unconfigured until real credentials are provided.
os.environ.setdefault('IJPP_LOGIN', ':')
os.environ.setdefault('LPP_API_KEY', '')

from ojpp_core.settings import *  # noqa: E402,F401,F403
from ojpp_core.settings import env, root, INSTALLED_APPS, DATABASES, CORS_ALLOWED_ORIGINS, MIDDLEWARE  # noqa: E402

DATABASES['default']['PORT'] = env('POSTGRES_PORT', default='5432')

INSTALLED_APPS = ['prestop_data', 'prestop_api', 'prestop_statistics', 'prestop_push', *INSTALLED_APPS]

# Load shedding for /api/v1 so a public server stays inside its free outbound allowance
# (prestop_api/traffic.py). Off locally; the production settings turn it on.
MIDDLEWARE = [MIDDLEWARE[0], 'prestop_api.analytics.AnalyticsMiddleware', 'prestop_api.traffic.TrafficGuardMiddleware', *MIDDLEWARE[1:]]
# Usage counts in Redis, flushed to Postgres by the collector (prestop_api/analytics.py); off under manage.py test.
PRESTOP_ANALYTICS = 'test' not in sys.argv[1:2] and env.bool('PRESTOP_ANALYTICS', default=True)
PRESTOP_ANALYTICS_REDIS_URL = env('PRESTOP_ANALYTICS_REDIS_URL', default='')
# Hop's presence and messages (prestop_api/hop.py); empty uses the cache's Redis.
PRESTOP_HOP_REDIS_URL = env('PRESTOP_HOP_REDIS_URL', default='')
PRESTOP_TRAFFIC_GUARD = env.bool('PRESTOP_TRAFFIC_GUARD', default=False)
# Header with the visitor's IP set by the trusted proxy (CF-Connecting-IP); empty uses REMOTE_ADDR.
PRESTOP_CLIENT_IP_HEADER = env('PRESTOP_CLIENT_IP_HEADER', default='')
# Directory where the egress guard writes `busy` / `stopped`; empty disables those checks.
PRESTOP_TRAFFIC_STATE_DIR = env('PRESTOP_TRAFFIC_STATE_DIR', default='')
PRESTOP_TRAFFIC_PER_MINUTE = env.int('PRESTOP_TRAFFIC_PER_MINUTE', default=1200)
PRESTOP_TRAFFIC_MAX_ACTIVE = env.int('PRESTOP_TRAFFIC_MAX_ACTIVE', default=3000)
PRESTOP_TRAFFIC_HOURLY_MB = env.int('PRESTOP_TRAFFIC_HOURLY_MB', default=30000)
# JSON file `{message: {sl, en}, until}` that push.sh writes shortly before a deploy restarts the API;
# /health reports it as `maintenance` so the app can say the server is updating. Empty disables it.
PRESTOP_MAINTENANCE_FILE = env('PRESTOP_MAINTENANCE_FILE', default='')

ROOT_URLCONF = 'ojpp_core.urls_prestop'

# Upstream's admin uses django-ckeditor, which warns on every command about the bundled
# CKEditor 4. The editor only appears in OJPP's admin, not in the Prestop API.
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']

CORS_ALLOWED_ORIGINS = [
    *CORS_ALLOWED_ORIGINS,
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]

# Public, credential-free GTFS mirror maintained by the OJPP authors.
PRESTOP_GTFS_MIRROR = env('PRESTOP_GTFS_MIRROR', default='http://gtfs.derp.si/')
PRESTOP_GTFS_DIR = env('PRESTOP_GTFS_DIR', default=str(root / 'data/gtfs'))

# Upstream jobs run by `manage.py run_ingestion`. NAP/IJPP jobs need B2B credentials
# and the generated NeTEx/SIRI bindings, so they are not enabled by default.
PRESTOP_INGESTION_JOBS = env.list('PRESTOP_INGESTION_JOBS', default=[
    'lpp_update_locations',
    'prestop_refresh_gtfs',
])

# Live data for /api/v1 (prestop_api): the public OpenTripPlanner and combined
# GTFS-Realtime feeds run by the OJPP authors, the same sources brezavta.si uses.
PRESTOP_OTP_URLS = env.list('PRESTOP_OTP_URLS', default=[
    'https://otp.ojpp-gateway.derp.si/otp/gtfs/v1',
    'http://otp1.ojpp-gateway.derp.si/otp/gtfs/v1',
    'http://otp2.ojpp-gateway.derp.si/otp/gtfs/v1',
])
PRESTOP_RT_VEHICLES_URL = env('PRESTOP_RT_VEHICLES_URL', default='https://rt.gtfs.ijpp.prometko.si/combined/rt/vl')
PRESTOP_RT_TRIP_UPDATES_URL = env('PRESTOP_RT_TRIP_UPDATES_URL', default='https://rt.gtfs.ijpp.prometko.si/combined/rt/tu?type=json')
# The Kranj city buses' full timetable from the operator (Ridango), read instead of OTP's broken copy
# (prestop_api/supplement.py); '' turns it off.
PRESTOP_KRANJ_GTFS_URL = '' if 'test' in sys.argv[1:2] else env('PRESTOP_KRANJ_GTFS_URL', default='https://kranj-avl-prod.ridango.cloud/data/gtfs/v2/gtfs.zip')
# City bus timetables kept by hand in prestop_api/data/gtfs/<feedId>/ (read like the Kranj file).
PRESTOP_LOCAL_GTFS = False if 'test' in sys.argv[1:2] else env.bool('PRESTOP_LOCAL_GTFS', default=True)
PRESTOP_PELIAS_URL =env('PRESTOP_PELIAS_URL', default='http://pelias.ojpp.derp.si/v1')
PRESTOP_PHOTON_URL = env('PRESTOP_PHOTON_URL', default='https://photon.komoot.io/api/')
# SŽ sources are URL lists (comma-separated in the env, tried in order, the last one that answered first;
# upstream.Mirrors): derp-si's sz-platform-scraper under its two host names, then older services. '' turns one off.
# docs/research/2026-10-26-sz-source-chain.md lists who runs what.
SZ_SCRAPER = ('http://sz-platform-scraper.coolify.pve.si:12669', 'http://l10wspc3n0hqslvh6xuyd8la.141.255.217.12.sslip.io:12669')
# SŽ live trains: delay, next station, coordinates (prestop_api/sz.py).
PRESTOP_SZ_LIVE_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_LIVE_URL', default=[f'{h}/active_trains' for h in SZ_SCRAPER] + ['https://api.modra.ninja/sz/lokacije'])
# SŽ's delay table: actual and predicted delays, arrival or departure (prestop_api/sz.py).
PRESTOP_SZ_DELAYS_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_DELAYS_URL', default=[f'{h}/delays' for h in SZ_SCRAPER])
# ijpp-rt's own SŽ trip updates, a second path that skips the combined aggregator (gtfs-rt-aggregator providers/ijpp.js).
PRESTOP_SZ_RT_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_RT_URL', default=['http://jckcw4scco8wgo80c804gg0k.141.255.217.12.sslip.io/data/raw/sz/rt/trip-updates?type=json'])
# SŽ track numbers announced today (prestop_api/tracks.py); off: trains show their usual track from data/sz_tracks.json.
PRESTOP_SZ_TRACKS_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_TRACKS_URL', default=[f'{h}/train_data' for h in SZ_SCRAPER])
# Each train's usual track per station (prestop_api/tracks.py); empty: the copy checked in with the app.
PRESTOP_SZ_USUAL_TRACKS_FILE = '' if 'test' in sys.argv[1:2] else env('PRESTOP_SZ_USUAL_TRACKS_FILE', default='')
# zamudil.si (allowed by its author 2026-10-27, source named, our User-Agent): SŽ's notices per service date, the
# planned class of each train and the works on the lines (prestop_api/zamudil.py). Its notices go first, before
# PRESTOP_SZ_NOTICES_URL. The last good copy of each endpoint and date is kept in PRESTOP_ZAMUDIL_DIR, which the API's
# workers and szpdf_sync share; '' keeps copies in memory only.
PRESTOP_ZAMUDIL_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_ZAMUDIL_URL', default=['https://api.zamudil.si/api'])
PRESTOP_ZAMUDIL_DIR = '' if 'test' in sys.argv[1:2] else env('PRESTOP_ZAMUDIL_DIR', default=str(root / 'data/zamudil'))
# SŽ disruption notices with their HTML (map links of replacement stops; see prestop_api/closures.py), read when
# zamudil.si has no copy; the last good notices are kept on disk.
PRESTOP_SZ_NOTICES_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_NOTICES_URL', default=['https://api.modra.ninja/sz/ovire_raw?lang=sl'])
# The last good notices, so a restart while every notices URL fails keeps today's closures (closures.py).
PRESTOP_SZ_NOTICES_FILE = '' if 'test' in sys.argv[1:2] else env('PRESTOP_SZ_NOTICES_FILE', default=str(root / 'data/sz-notices.json'))
# SŽ's own RSS (news and "Obvestila za potnike"; no bot check): text alerts while no notices source works.
PRESTOP_SZ_NEWS_URL = [] if 'test' in sys.argv[1:2] else env.list('PRESTOP_SZ_NEWS_URL', default=['https://potniski.sz.si/feed/'])
# The notices' replacement-timetable PDFs, read by `manage.py szpdf_sync` (prestop_api/szpdf) into one JSON
# file per PDF plus index.json, which the API reads (prestop_api/sztimetables.py). Tests set their own directory.
PRESTOP_SZ_TIMETABLES_DIR = '' if 'test' in sys.argv[1:2] else env('PRESTOP_SZ_TIMETABLES_DIR', default=str(root / 'data/sz-timetables'))
# Road routing (bus costing) for bus patterns without a usable shape; empty disables it.
# Routed legs are stored in the database, so the public FOSSGIS server sees each once.
# Tests never route (they would reach the public server from a background thread).
PRESTOP_VALHALLA_URL = '' if 'test' in sys.argv[1:2] else env('PRESTOP_VALHALLA_URL', default='https://valhalla1.openstreetmap.de/route')
# Seconds between requests from the background workers (0 for a local router).
PRESTOP_VALHALLA_GAP = env.float('PRESTOP_VALHALLA_GAP', default=0.35)
# Map-match every bus shape onto the roads (roads.matched), so lines follow the streets exactly.
PRESTOP_SHAPE_MATCH = env.bool('PRESTOP_SHAPE_MATCH', default=True)
# Vehicles standing at a stop become "possible disruption" alerts (detected.py). Off: Slovenian buses are
# usually just late, and the alerts (and the notifications they set off) came too often.
PRESTOP_DETECTED_ALERTS = env.bool('PRESTOP_DETECTED_ALERTS', default=False)
# AP Ljubljana's departure board (bay per departure, platforms.py); empty disables it.
PRESTOP_AP_LJUBLJANA_URL = '' if 'test' in sys.argv[1:2] else env('PRESTOP_AP_LJUBLJANA_URL', default='https://www.ap-ljubljana.si/api/upcoming')
# Header set by a trusted reverse proxy (e.g. CF-IPCountry); empty disables IP-based language hints.
PRESTOP_TRUSTED_COUNTRY_HEADER = env('PRESTOP_TRUSTED_COUNTRY_HEADER', default='')
# Keep the timetable and stop indexes fresh while the app is in use (prestop_api/warm.py); never in tests.
PRESTOP_WARM = False if 'test' in sys.argv[1:2] else env.bool('PRESTOP_WARM', default=True)
# Boards and the built alert list are reused for a few seconds (sources.board, sources.alerts); off under
# manage.py test, where tests turn it on themselves.
PRESTOP_SHORT_CACHE = 'test' not in sys.argv[1:2] and env.bool('PRESTOP_SHORT_CACHE', default=True)
# Insane mode: same-minute transfers, no transfer penalty and a brisk walking pace.
PRESTOP_INSANE_MODE = env.bool('PRESTOP_INSANE_MODE', default=True)
# Predicted delays on journey legs from history and the vehicle's previous trip (predictions.py); off under
# manage.py test, where tests turn it on themselves.
PRESTOP_PREDICTIONS = 'test' not in sys.argv[1:2] and env.bool('PRESTOP_PREDICTIONS', default=True)
# Web Push (prestop_push): VAPID key pair from `vapid --gen` (see deploy/oracle/README.md).
# Empty keys turn push off; only the public key is ever sent to clients.
PRESTOP_VAPID_PUBLIC_KEY = env('PRESTOP_VAPID_PUBLIC_KEY', default='')
PRESTOP_VAPID_PRIVATE_KEY = env('PRESTOP_VAPID_PRIVATE_KEY', default='')
PRESTOP_VAPID_SUBJECT = env('PRESTOP_VAPID_SUBJECT', default='mailto:push@kamgre.si')
