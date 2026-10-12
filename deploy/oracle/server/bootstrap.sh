#!/usr/bin/env bash
# One-time server setup for Prestop on an OCI Always Free Ubuntu 24.04 (Ampere A1) instance.
# Run by update.sh on the first deploy; safe to re-run. Needs root.
#
#   PRESTOP_DOMAIN       your domain, e.g. kamgre.si (required on the first run)
#   CLOUDFLARE_TUNNEL_TOKEN  optional: installs the Cloudflare Tunnel connector
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "bootstrap.sh needs root (sudo)" >&2; exit 1; }

DEPLOY=/opt/prestop/deploy
ENV_FILE=/etc/prestop/prestop.env
export DEBIAN_FRONTEND=noninteractive
step() { printf '\n==> %s\n' "$*"; }

[ "$(dpkg --print-architecture)" = arm64 ] || echo "warning: expected an arm64 (A1) instance, got $(dpkg --print-architecture)"

step "Packages: PostgreSQL 18 + PostGIS (PGDG), Redis, Caddy, Python, GDAL"
apt-get update -q
apt-get install -yq ca-certificates curl gnupg rsync jq
install -d /usr/share/postgresql-common/pgdg
curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release; echo "$VERSION_CODENAME")-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  > /etc/apt/sources.list.d/cloudflared.list
apt-get update -q
apt-get install -yq postgresql-18 postgresql-18-postgis-3 redis-server caddy cloudflared rclone \
  python3 python3-venv python3-dev build-essential libpq-dev gdal-bin unattended-upgrades vnstat fail2ban

step "Swap (2 GB safety margin)"
if ! swapon --show | grep -q /swapfile; then
  [ -f /swapfile ] || { fallocate -l 2G /swapfile; chmod 600 /swapfile; mkswap /swapfile; }
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/90-prestop.conf
sysctl -q --system

step "Automatic security updates (reboot at 03:30 when needed)"
cat > /etc/apt/apt.conf.d/52prestop-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
EOF

step "SSH: keys only, no root login; fail2ban bans repeated failures"
# SSH is the only port open to the internet (the API arrives through the Cloudflare tunnel).
cat > /etc/ssh/sshd_config.d/10-prestop.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
LoginGraceTime 30
EOF
sshd -t
# Ubuntu 24.04 starts sshd per connection (ssh.socket), which reads the new config anyway.
systemctl reload ssh 2>/dev/null || true
cat > /etc/fail2ban/jail.d/prestop.conf <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
bantime.increment = true
EOF
systemctl enable -q fail2ban && systemctl restart fail2ban

step "User and directories"
id prestop >/dev/null 2>&1 || useradd --system --home-dir /var/lib/prestop --shell /usr/sbin/nologin prestop
install -d -o prestop -g prestop -m 0750 /var/lib/prestop /var/lib/prestop/static /var/lib/prestop/media /var/lib/prestop/gtfs /var/lib/prestop/tmp /var/backups/prestop
chmod 0755 /var/lib/prestop /var/lib/prestop/static   # Caddy serves /static
install -d -m 0755 /opt/prestop
install -d -o root -g prestop -m 0750 /etc/prestop

step "Configuration: $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  : "${PRESTOP_DOMAIN:?set PRESTOP_DOMAIN (DOMAIN in config.local) for the first deploy}"
  secret="$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 50)"
  sed -e "s/__SECRET_KEY__/$secret/" -e "s/__DOMAIN__/$PRESTOP_DOMAIN/" "$DEPLOY/server/prestop.env.template" > "$ENV_FILE"
  chown root:prestop "$ENV_FILE"; chmod 0640 "$ENV_FILE"
  echo "created with a new SECRET_KEY"
else
  echo "kept existing file"
fi

step "PostgreSQL: tuning, role and database"
install -m 0644 "$DEPLOY/postgres/prestop.conf" /etc/postgresql/18/main/conf.d/prestop.conf
systemctl restart postgresql
pg() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtA "$@"; }
[ "$(pg -c "SELECT 1 FROM pg_roles WHERE rolname='prestop'")" = 1 ] || runuser -u postgres -- createuser prestop
[ "$(pg -c "SELECT 1 FROM pg_database WHERE datname='prestop'")" = 1 ] || runuser -u postgres -- createdb -O prestop prestop
pg -d prestop -c 'CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS hstore; CREATE EXTENSION IF NOT EXISTS pg_prewarm;'

step "Redis: local cache only"
conf=/etc/redis/redis.conf
grep -q '^# prestop' "$conf" || cat >> "$conf" <<'EOF'
# prestop: cache only, bounded, no snapshots
maxmemory 512mb
maxmemory-policy allkeys-lru
save ""
EOF
systemctl restart redis-server

step "Python environment"
[ -x /opt/prestop/venv/bin/python ] || python3 -m venv /opt/prestop/venv
/opt/prestop/venv/bin/pip install -q --upgrade pip wheel pipenv gunicorn

step "Cloudflare Tunnel"
if systemctl list-unit-files cloudflared.service >/dev/null 2>&1 && systemctl is-enabled -q cloudflared 2>/dev/null; then
  echo "cloudflared service already installed"
elif [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"
else
  echo "no CLOUDFLARE_TUNNEL_TOKEN yet: add it to config.local and deploy again (see README)"
fi

step "Oracle Cloud Agent (reports the CPU/memory metrics Oracle judges idleness by)"
if snap list oracle-cloud-agent >/dev/null 2>&1; then echo "installed"; else echo "warning: oracle-cloud-agent snap not found; check Instance > Oracle Cloud Agent in the console"; fi

touch /etc/prestop/.bootstrapped
step "Bootstrap complete"
