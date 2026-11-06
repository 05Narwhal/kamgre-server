#!/usr/bin/env bash
# SŽ website reader (N11-N13), called by update.sh. Off until /etc/prestop/prestop.env says PRESTOP_SZSITE=on:
#   PRESTOP_SZSITE=on        Docker (Ubuntu's docker.io), FlareSolverr container, our reader (prestop-szsite.service)
#   PRESTOP_SZSITE_WARP=on   also the anonymous WARP proxy container; the solver and the reader then go through it
# Nothing here creates an Oracle resource: containers on the existing VM, loopback only, $0 (README: SŽ reader).
set -euo pipefail
ENV=/etc/prestop/prestop.env
DEPLOY=/opt/prestop/deploy
STATE=/var/lib/prestop
get() { sed -n "s/^$1=//p" "$ENV" | tail -1; }
# set_env KEY VALUE: replace the line, or add it.
set_env() {
  if grep -q "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi
}
grep -q '^PRESTOP_SZSITE=' "$ENV" || printf '\n# SŽ website reader (README: SŽ reader). on/off; update.sh manages the PRESTOP_SZSITE_* lines below it.\nPRESTOP_SZSITE=off\n' >> "$ENV"
grep -q '^PRESTOP_SZSITE_WARP=' "$ENV" || echo 'PRESTOP_SZSITE_WARP=off' >> "$ENV"
UNITS=(prestop-szsite prestop-szsite-solver prestop-szsite-warp)

if [ "$(get PRESTOP_SZSITE)" != on ]; then
  # Off: nothing runs and the API reads derp-si / zamudil.si as before. Docker (if installed earlier) stops too.
  for u in "${UNITS[@]}" prestop-szsite-guard.timer; do
    systemctl disable -q --now "$u" 2>/dev/null || true
  done
  if systemctl list-unit-files docker.service >/dev/null 2>&1; then systemctl disable -q --now docker.socket docker 2>/dev/null || true; fi
  set_env PRESTOP_SZSITE_SOLVER ''
  set_env PRESTOP_SZSITE_PROXY ''
  echo "SŽ reader: off (PRESTOP_SZSITE=on in $ENV turns it on)"
  exit 0
fi

avail=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
echo "SŽ reader: on ($avail MB available now; it pauses itself under 2048 MB)"
if ! command -v docker >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -yq docker.io
fi
# Published ports (none today: host network) would bind to loopback only; logs go to the journal, not to disk files.
install -d -m 0755 /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{ "ip": "127.0.0.1", "log-driver": "journald", "live-restore": true }
JSON
systemctl enable -q docker
systemctl restart docker
docker pull -q ghcr.io/flaresolverr/flaresolverr:v3.5.2 >/dev/null

install -d -o prestop -g prestop -m 0750 "$STATE/szsite"
set_env PRESTOP_SZSITE_DIR "$STATE/szsite"
set_env PRESTOP_SZSITE_SOLVER http://127.0.0.1:8191
if [ "$(get PRESTOP_SZSITE_WARP)" = on ]; then
  install -d -m 0700 "$STATE/warp"
  docker build -q -t prestop-warp:local -f "$DEPLOY/server/szsite/warp.Dockerfile" "$DEPLOY/server/szsite" >/dev/null
  set_env PRESTOP_SZSITE_PROXY http://127.0.0.1:40000
  systemctl enable -q prestop-szsite-warp
  systemctl restart prestop-szsite-warp
else
  systemctl disable -q --now prestop-szsite-warp 2>/dev/null || true
  set_env PRESTOP_SZSITE_PROXY ''
fi
rm -f /run/prestop-szsite-paused
systemctl enable -q prestop-szsite-solver prestop-szsite
systemctl enable -q --now prestop-szsite-guard.timer
systemctl restart prestop-szsite-solver prestop-szsite || echo "SŽ reader did not start: journalctl -u prestop-szsite -n 30"
