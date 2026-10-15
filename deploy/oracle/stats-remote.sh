#!/usr/bin/env bash
# Usage report from the Oracle server in your own terminal: runs `manage.py stats` there over SSH
# (prestop_api/analytics_report.py). Read-only: it only reads the usage counts.
#
#   yarn server:stats [today|week|month|all]      ("this week" and "this month" work too; default today)
#   bash backend/deploy/oracle/stats-remote.sh [period]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"
PERIOD=$(echo "${*:-today}" | tr '[:upper:]' '[:lower:]')
[[ $PERIOD =~ ^(this\ )?(today|day|week|month|all)$ ]] || { echo "Period: today, week, month or all (\"this week\" works too)." >&2; exit 1; }

ssh_opts=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
exec ssh "${ssh_opts[@]}" "$SSH_TARGET" "sudo prestop-manage stats --period $(printf %q "$PERIOD")"
