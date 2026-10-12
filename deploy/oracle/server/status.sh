#!/usr/bin/env bash
# prestop-status: services, utilization floor, health and backups at a glance.
set -uo pipefail
printf '%-20s %s\n' SERVICE STATE
for s in prestop-web prestop-collector prestop-push prestop-ingest prestop-floor caddy cloudflared postgresql redis-server prestop-backup.timer prestop-watchdog.timer prestop-egress.timer; do
  printf '%-20s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
echo
echo "Utilization floor (Oracle reclaims only if CPU, network and memory all stay < 20%):"
if [ -f /run/prestop-floor/status.json ]; then
  jq -r '"  CPU \(.cpu_total)%  (your workload \(.cpu_workload)%, filler \(.cpu_filler_duty)%)\n  memory \(.mem_used)%  (ballast \(.mem_ballast_mb) MB)"' /run/prestop-floor/status.json
else
  echo "  no status yet (systemctl status prestop-floor)"
fi
echo
echo "Health: $(curl -fsS --max-time 5 http://127.0.0.1:8066/api/v1/health 2>/dev/null | jq -c '{api, database, collector}' 2>/dev/null || echo unavailable)"
echo "Last backup: $(ls -1t /var/backups/prestop/*.dump 2>/dev/null | head -1 || true)"
echo "Egress: $(/opt/prestop/deploy/server/egress-guard.sh 2>/dev/null | tail -1)"
echo "Disk: $(df -h / | awk 'NR==2 {print $3 " used of " $2}')"
