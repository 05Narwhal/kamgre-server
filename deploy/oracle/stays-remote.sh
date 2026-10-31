#!/usr/bin/env bash
# Stay-on and depot learning report from the Oracle server in your own terminal: runs `manage.py stays_report` there
# over SSH (prestop_statistics/management/commands/stays_report.py). Read-only. Sends the local copy of the command,
# so it works before the next deploy.
# With --trains: staying on the train instead (manage.py train_stay_backtest, read-only), sending the local
# train_stays.py with it, so it also works before the deploy (spec 2026-10-31 H6).
#
#   yarn server:stays [--lines] [--feed IJPP]
#   yarn server:stays --trains [--pairs 40]
#   bash backend/deploy/oracle/stays-remote.sh [--lines] [--feed IJPP]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"
args=""
trains=""
for arg in "$@"; do
  [[ $arg =~ ^[A-Za-z0-9_-]{1,40}$ ]] || { echo "Arguments: --lines, --feed <feed>, --trains [--pairs N] [--days N]." >&2; exit 1; }
  if [ "$arg" = "--trains" ]; then trains=1; continue; fi
  args+="'$arg', "
done

ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
STATS="$HERE/../../ojpp-django/prestop_statistics"
if [ -n "$trains" ]; then
  # The local train_stays.py as the module the command imports (the server's copy may be older or missing).
  { printf 'import sys, types\n_m = types.ModuleType("prestop_statistics.train_stays")\n'
    printf 'sys.modules["prestop_statistics.train_stays"] = _m\nexec(compile(%s, "train_stays.py", "exec"), _m.__dict__)\n' \
      "$(tr -d '\r' < "$STATS/train_stays.py" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()))')"
    tr -d '\r' < "$STATS/management/commands/train_stay_backtest.py"
    printf '\nfrom django.core.management import call_command\ncall_command(Command(), %s)\n' "$args"
  } | ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage shell"
  exit
fi
{ tr -d '\r' < "$STATS/management/commands/stays_report.py"
  printf '\nfrom django.core.management import call_command\ncall_command(Command(), %s)\n' "$args"
} | ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage shell"
