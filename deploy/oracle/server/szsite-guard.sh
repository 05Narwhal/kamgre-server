#!/usr/bin/env bash
# Memory guard for the SŽ website reader (prestop-szsite*). The API, database and collector come first:
#   szsite-guard.sh check   exit 1 while MemAvailable < 2 GB (ExecStartPre of the reader units)
#   szsite-guard.sh watch   (timer, root) under 2 GB: stop the reader units; back above 3 GB: start them again
set -euo pipefail
LOW_MB=2048
RESUME_MB=3072
UNITS=(prestop-szsite prestop-szsite-solver prestop-szsite-warp)
PAUSED=/run/prestop-szsite-paused
avail_mb() { awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo; }
mb="$(avail_mb)"
case "${1:-}" in
  check)
    if [ "$mb" -lt "$LOW_MB" ]; then echo "SŽ reader not started: $mb MB available, needs $LOW_MB MB" >&2; exit 1; fi ;;
  watch)
    on="$(sed -n 's/^PRESTOP_SZSITE=//p' /etc/prestop/prestop.env | tail -1)"
    [ "$on" = on ] || exit 0
    if [ "$mb" -lt "$LOW_MB" ]; then
      if systemctl is-active -q prestop-szsite prestop-szsite-solver; then
        systemctl stop "${UNITS[@]}" || true
        echo "$(date -Is) $mb MB" > "$PAUSED"
        logger -t prestop-szsite "stopped: $mb MB available (under $LOW_MB MB)"
      fi
    elif [ -f "$PAUSED" ] && [ "$mb" -ge "$RESUME_MB" ]; then
      rm -f "$PAUSED"
      warp="$(sed -n 's/^PRESTOP_SZSITE_WARP=//p' /etc/prestop/prestop.env | tail -1)"
      [ "$warp" = on ] && systemctl start prestop-szsite-warp || true
      systemctl start prestop-szsite-solver prestop-szsite || true
      logger -t prestop-szsite "started again: $mb MB available"
    fi ;;
  *) echo "usage: szsite-guard.sh check|watch" >&2; exit 2 ;;
esac
