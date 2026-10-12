#!/usr/bin/env bash
# Deploy the Prestop backend to the Oracle server from WSL: copies the backend and this deploy
# folder, then runs server/update.sh there (the first run also sets up the machine). The web app
# is not deployed here: Vercel builds it from GitHub.
#
#   bash backend/deploy/oracle/push.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"

ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
remote() { ssh "${ssh_opts[@]}" "$SSH_TARGET" "$@"; }
# Files land owned by root, world-readable, never world-writable (Windows drives show 777 in WSL).
copy() { rsync -az --delete --chown=root:root --chmod=D755,F644 --rsync-path='sudo rsync' -e "ssh ${ssh_opts[*]}" "$@"; }

echo "==> Cost audit (Oracle account must have nothing billable)"
if ! bash "$HERE/oci/audit.sh"; then
  echo "Deploy stopped: fix the FAIL lines above first (README: Cost safety)." >&2
  exit 1
fi

echo "==> Connecting to $SSH_TARGET"
remote 'sudo mkdir -p /opt/prestop/app /opt/prestop/deploy /etc/prestop && command -v rsync >/dev/null || sudo apt-get install -yq rsync'

echo "==> Copying backend"
copy --exclude='/.env' --exclude='/data/' --exclude='/dump.rdb' --exclude='/.idea/' --exclude='.git/' \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.venv/' --exclude='venv/' --exclude='*.zip' --exclude='ojpp.sql*' \
  "$ROOT/backend/ojpp-django/" "$SSH_TARGET:/opt/prestop/app/"

echo "==> Copying deploy files"
copy --exclude='/config.local' --exclude='__pycache__/' "$HERE/" "$SSH_TARGET:/opt/prestop/deploy/"

# Domain and tunnel token travel over SSH stdin into a root-only file that update.sh deletes.
printf 'PRESTOP_DOMAIN=%q\nCLOUDFLARE_TUNNEL_TOKEN=%q\n' "${DOMAIN:-}" "${CLOUDFLARE_TUNNEL_TOKEN:-}" |
  remote 'sudo sh -c "umask 077; cat > /etc/prestop/deploy.vars"'

echo "==> Applying on the server"
remote 'sudo bash /opt/prestop/deploy/server/update.sh'
echo
echo "Deployed. Check anytime with: ssh $SSH_TARGET sudo prestop-status"
