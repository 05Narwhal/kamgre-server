#!/usr/bin/env bash
# Stay-on and depot learning report from the Oracle server in your own terminal: runs `manage.py stays_report` there
# over SSH (prestop_statistics/management/commands/stays_report.py). Read-only. Sends the local copy of the command,
# so it works before the next deploy.
#
#   yarn server:stays [--lines] [--feed IJPP]
#   bash backend/deploy/oracle/stays-remote.sh [--lines] [--feed IJPP]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"
args=""
for arg in "$@"; do
  [[ $arg =~ ^[A-Za-z0-9_-]{1,40}$ ]] || { echo "Arguments: --lines, --feed <feed>." >&2; exit 1; }
  args+="'$arg', "
done

ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
{ tr -d '\r' < "$HERE/../../ojpp-django/prestop_statistics/management/commands/stays_report.py"
  printf '\nfrom django.core.management import call_command\ncall_command(Command(), %s)\n' "$args"
} | ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage shell"
