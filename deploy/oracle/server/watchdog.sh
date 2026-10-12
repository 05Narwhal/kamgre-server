#!/usr/bin/env bash
# prestop-watchdog.timer: restart the API after 3 failed health checks in a row (about 6 minutes).
set -uo pipefail
count_file=/run/prestop-watchdog/failures
if curl -fsS --max-time 10 -o /dev/null http://127.0.0.1:8066/api/v1/health; then
  echo 0 > "$count_file"
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
