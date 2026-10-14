#!/usr/bin/env bash
# The maintenance flag /api/v1/health reports while a deploy restarts the API (PRESTOP_MAINTENANCE_FILE).
#   sudo bash maintenance.sh on [seconds]   # announce an update lasting about that long (default 180)
#   sudo bash maintenance.sh off
set -euo pipefail
FLAG="${PRESTOP_MAINTENANCE_FILE:-/var/lib/prestop/maintenance.json}"
case "${1:-}" in
  on)
    until="$(date -u -d "+${2:-180} seconds" +%Y-%m-%dT%H:%M:%S+00:00)"
    tmp="$(mktemp "$(dirname "$FLAG")/.maintenance.XXXXXX")"
    printf '{"message": {"sl": "%s", "en": "%s"}, "until": "%s"}\n' \
      'KamGre se posodablja. ÄŒez nekaj minut bo spet vse kot prej.' \
      'KamGre is updating. Everything will be back in a few minutes.' "$until" > "$tmp"
    chmod 0644 "$tmp"; mv -f "$tmp" "$FLAG"
    echo "Maintenance flag on until $until" ;;
  off) rm -f "$FLAG"; echo "Maintenance flag off" ;;
  *) sed -n '2,4p' "$0"; exit 2 ;;
esac
