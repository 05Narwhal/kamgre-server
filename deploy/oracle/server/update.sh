#!/usr/bin/env bash
# Applies a deploy on the server after push.sh has copied the code. Needs root.
# First run bootstraps the machine; later runs install only what changed.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "update.sh needs root (sudo)" >&2; exit 1; }

DEPLOY=/opt/prestop/deploy
APP=/opt/prestop/app
VENV=/opt/prestop/venv
STATE=/var/lib/prestop
step() { printf '\n==> %s\n' "$*"; }

# Values sent by push.sh (domain, tunnel token) for the first deploy; never echoed.
if [ -f /etc/prestop/deploy.vars ]; then
  set -a; . /etc/prestop/deploy.vars; set +a
  rm -f /etc/prestop/deploy.vars
fi

chmod 0755 "$DEPLOY"/server/*.sh "$DEPLOY"/floor/prestop_floor.py
if [ ! -f /etc/prestop/.bootstrapped ]; then
  bash "$DEPLOY/server/bootstrap.sh"
fi

# Tunnel token for systemd/cloudflared.service: root-only file, refreshed on every deploy.
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  install -d -m 0700 /etc/cloudflared
  (umask 077; printf '%s
' "$CLOUDFLARE_TUNNEL_TOKEN" > /etc/cloudflared/token)
fi
unset CLOUDFLARE_TUNNEL_TOKEN

# Servers bootstrapped before the egress guard existed.
command -v vnstat >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -yq vnstat

step "Config files"
install -m 0644 "$DEPLOY"/systemd/*.service "$DEPLOY"/systemd/*.timer /etc/systemd/system/
install -m 0644 "$DEPLOY/caddy/Caddyfile" /etc/caddy/Caddyfile
# Caddy and the tunnel stay off while the egress guard has tripped this month, even after a reboot.
for unit in caddy cloudflared; do
  install -D -m 0644 "$DEPLOY/systemd/egress-hold.conf" "/etc/systemd/system/$unit.service.d/prestop-egress-hold.conf"
done
if ! cmp -s "$DEPLOY/postgres/prestop.conf" /etc/postgresql/18/main/conf.d/prestop.conf; then
  install -m 0644 "$DEPLOY/postgres/prestop.conf" /etc/postgresql/18/main/conf.d/prestop.conf
  systemctl restart postgresql
fi
ln -sf "$DEPLOY/server/manage.sh" /usr/local/bin/prestop-manage
ln -sf "$DEPLOY/server/status.sh" /usr/local/bin/prestop-status
ln -sf "$DEPLOY/server/restore.sh" /usr/local/bin/prestop-restore
systemctl daemon-reload

step "Python dependencies"
lock_hash="$(sha256sum "$APP/Pipfile.lock" | cut -d' ' -f1)"
if [ "$(cat "$STATE/.pipfile-lock" 2>/dev/null)" != "$lock_hash" ]; then
  (cd "$APP" && PIPENV_VERBOSITY=-1 "$VENV/bin/pipenv" requirements > "$STATE/requirements.txt")
  "$VENV/bin/pip" install -q -r "$STATE/requirements.txt"
  echo "$lock_hash" > "$STATE/.pipfile-lock"
else
  echo "Pipfile.lock unchanged"
fi
# Prestop's own additions (Web Push), with the upstream lock as constraints so nothing upstream moves.
extra_hash="$(cat "$APP/requirements-prestop.txt" "$STATE/requirements.txt" | sha256sum | cut -d' ' -f1)"
if [ "$(cat "$STATE/.requirements-prestop" 2>/dev/null)" != "$extra_hash" ]; then
  # pip rejects options (-i ...) and extras (zeep[async]) in constraint files: keep only name==version.
  sed -E '/^-/d; s/^([A-Za-z0-9._-]+)\[[^]]*\]/\1/' "$STATE/requirements.txt" > "$STATE/constraints.txt"
  "$VENV/bin/pip" install -q -r "$APP/requirements-prestop.txt" -c "$STATE/constraints.txt"
  echo "$extra_hash" > "$STATE/.requirements-prestop"
fi

step "Push notification keys"
# Generated on the server the first time; the private key never leaves /etc/prestop/prestop.env.
if ! grep -q '^PRESTOP_VAPID_PRIVATE_KEY=.' /etc/prestop/prestop.env; then
  sed -i '/^PRESTOP_VAPID_\(PUBLIC\|PRIVATE\)_KEY=/d' /etc/prestop/prestop.env
  prestop-manage vapid_keys >> /etc/prestop/prestop.env
  echo "Generated a VAPID key pair in /etc/prestop/prestop.env"
else
  echo "VAPID keys present"
fi

step "Database migrations and static files"
prestop-manage migrate --noinput
prestop-manage collectstatic --noinput -v 0

if [ ! -f "$STATE/.gtfs-imported" ]; then
  step "First GTFS import (a few minutes)"
  prestop-manage import_gtfs
  touch "$STATE/.gtfs-imported"
fi

step "Services"
systemctl enable -q prestop-web prestop-collector prestop-push prestop-ingest prestop-floor caddy redis-server postgresql
systemctl enable -q --now vnstat prestop-backup.timer prestop-watchdog.timer prestop-egress.timer
systemctl restart prestop-web prestop-collector prestop-push prestop-ingest
systemctl restart prestop-floor
# Keep public traffic off while the egress guard has tripped this month.
[ -f "$STATE/egress-tripped" ] || systemctl restart caddy
if [ -s /etc/cloudflared/token ]; then
  systemctl enable -q cloudflared
  [ -f "$STATE/egress-tripped" ] || systemctl restart cloudflared
else
  echo "No tunnel token yet: set CLOUDFLARE_TUNNEL_TOKEN in config.local and deploy again."
fi
# Refresh the traffic stage (busy/stopped) for the API and Caddy right away.
systemctl start prestop-egress.service || true

step "Health check"
for i in $(seq 30); do
  if body="$(curl -fsS --max-time 5 http://127.0.0.1:8066/api/v1/health 2>/dev/null)"; then
    echo "API: $body" | cut -c1-300
    curl -fsS --max-time 5 -o /dev/null http://127.0.0.1/api/v1/health && echo "Caddy: serving the API" || echo "Caddy: NOT serving the API (journalctl -u caddy)"
    systemctl is-active -q cloudflared && echo "Tunnel: running" || echo "Tunnel: not running yet (see README: Cloudflare Tunnel)"
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy; recent log:" >&2
journalctl -u prestop-web -n 40 --no-pager >&2
exit 1
