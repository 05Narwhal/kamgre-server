#!/usr/bin/env bash
# prestop-watchdog.timer: restart the API after 3 failed health checks in a row (about 6 minutes).
set -uo pipefail
count_file=/run/prestop-watchdog/failures
health=/run/prestop-watchdog/health.json
if curl -fsS --max-time 10 -o "$health" http://127.0.0.1:8066/api/v1/health; then
  echo 0 > "$count_file"
  # An SŽ source down for more than 30 min (prestop_api/views.outages): one journal line per check while it lasts.
  jq -r '.outages[]? | "SŽ source \(.id) \(.status) for \(.minutes) min (last answer \(.since // "none since start"))"' "$health" 2>/dev/null
  exit 0
fi
failures=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 ))
echo "$failures" > "$count_file"
echo "health check failed ($failures in a row)"
if [ "$failures" -ge 3 ]; then
  echo "restarting prestop-web"
  systemctl restart prestop-web
  echo 0 > "$count_file"
fi
