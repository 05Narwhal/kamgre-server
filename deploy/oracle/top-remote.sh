#!/usr/bin/env bash
# Live server view in your own terminal: runs server/top.sh on the Oracle server over SSH
# (q or Ctrl+C quits). Sends the local copy of the script, so it works before the next deploy.
#
#   yarn server:top [seconds between updates, default 2]
#   bash backend/deploy/oracle/top-remote.sh [seconds]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"
INTERVAL=${1:-2}
[[ $INTERVAL =~ ^[0-9]+$ ]] || { echo "Interval must be whole seconds." >&2; exit 1; }

ssh_opts=(-t -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
script=$(tr -d '\r' < "$HERE/server/top.sh")
exec ssh "${ssh_opts[@]}" "$SSH_TARGET" "sudo bash -c $(printf %q "$script") prestop-top $INTERVAL"
