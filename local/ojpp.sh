#!/usr/bin/env bash
# Run OJPP Django locally inside WSL (kali-linux) against the "prestop" PostGIS cluster.
#
#   wsl -d kali-linux -- bash backend/local/ojpp.sh up            # start PostGIS + Redis
#   wsl -d kali-linux -- bash backend/local/ojpp.sh manage <args>  # any manage.py command
#   wsl -d kali-linux -- bash backend/local/ojpp.sh serve          # API on http://localhost:8066 (Prestop facade at /api/v1)
#   wsl -d kali-linux -- bash backend/local/ojpp.sh collect        # record observed delays for /api/v1/statistics (every 60 s)
#   wsl -d kali-linux -- bash backend/local/ojpp.sh ingest         # OJPP's own LPP vehicle history + nightly GTFS refresh
#   wsl -d kali-linux -- bash backend/local/ojpp.sh push           # send reminders and live trip changes as Web Push (every 20 s)
#   wsl -d kali-linux -- bash backend/local/ojpp.sh stop           # stop a running API server, collector and push sender
#   wsl -d kali-linux -- bash backend/local/ojpp.sh valhalla       # local Valhalla router on :8002 (road shapes; see below)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HERE/../ojpp-django"
VENV="${PRESTOP_VENV:-$HOME/.venvs/prestop-ojpp}"
PY="$VENV/bin/python"
export DJANGO_SETTINGS_MODULE=ojpp_core.settings_prestop
export PYTHONUNBUFFERED=1
# A local Valhalla (pyvalhalla in ~/.venvs/valhalla, Slovenia tiles in ~/valhalla, started by
# `ojpp.sh valhalla`) routes and map-matches bus shapes without asking the public FOSSGIS server,
# so it needs no pause between requests. Without it the public server is used, politely.
VALHALLA_DIR="${PRESTOP_VALHALLA_DIR:-$HOME/valhalla}"
if [ -z "${PRESTOP_VALHALLA_URL:-}" ] && curl -s -m 2 -o /dev/null http://127.0.0.1:8002/status; then
  export PRESTOP_VALHALLA_URL=http://127.0.0.1:8002/route PRESTOP_VALHALLA_GAP=0
fi

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

up() {
  if ! pg_lsclusters -h | awk '$1==18 && $2=="prestop" && $4=="online"' | grep -q .; then
    as_root pg_ctlcluster 18 prestop start
  fi
  redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes --bind 127.0.0.1 >/dev/null
  pg_lsclusters | awk 'NR==1 || $2=="prestop"'
  echo "redis: $(redis-cli ping)"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  up) up ;;
  # Stop a previous API server or collector (e.g. from another window) so ports and polls don't clash.
  stop) pkill -f "manage.py (runserver|collect_delays|run_push)" && echo "stopped previous backend processes" || true ;;
  manage) cd "$APP" && exec "$PY" manage.py "$@" ;;
  serve) up >/dev/null; cd "$APP" && exec "$PY" manage.py runserver "0.0.0.0:${PORT:-8066}" "$@" ;;
  ingest) up >/dev/null; cd "$APP" && exec "$PY" manage.py run_ingestion "$@" ;;
  collect) up >/dev/null; cd "$APP" && exec "$PY" manage.py collect_delays "$@" ;;
  push) up >/dev/null; cd "$APP" && exec "$PY" manage.py run_push "$@" ;;
  valhalla)
    # One-time setup: python3.12 -m venv ~/.venvs/valhalla && ~/.venvs/valhalla/bin/pip install pyvalhalla,
    # then in ~/valhalla: download slovenia-latest.osm.pbf (Geofabrik), valhalla_build_config > valhalla.json
    # (tile dir ~/valhalla/tiles, listen tcp://127.0.0.1:8002), valhalla_build_admins and valhalla_build_tiles.
    [ -f "$VALHALLA_DIR/valhalla.json" ] || { echo "no local valhalla (see ojpp.sh valhalla); using ${PRESTOP_VALHALLA_URL:-the public server}"; exit 0; }
    pgrep -f "valhalla_service" >/dev/null && { echo "valhalla already running"; exit 0; }
    # pyvalhalla's wrapper finds its binary through PATH (3.9: "Can't find executable at valhalla_service").
    cd "$VALHALLA_DIR" && PATH="$HOME/.venvs/valhalla/bin:$PATH" nohup "$HOME/.venvs/valhalla/bin/valhalla_service" valhalla.json 2 > service.log 2>&1 &
    sleep 2; curl -s -m 5 http://127.0.0.1:8002/status && echo ;;
  *) sed -n '2,12p' "${BASH_SOURCE[0]}" ;;
esac
