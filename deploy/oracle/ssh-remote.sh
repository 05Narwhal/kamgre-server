#!/usr/bin/env bash
# A shell on the Oracle server in your own terminal (exit or Ctrl+D leaves). Run admin commands
# there, e.g. `sudo prestop-manage leg_detours --legs --delete` or `sudo prestop-status`. Lasting
# server changes still go through the deploy bundle (server/, systemd/, push.ps1), not by hand.
#
#   yarn server:ssh
#   bash backend/deploy/oracle/ssh-remote.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"

ssh_opts=(-t -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
exec ssh "${ssh_opts[@]}" "$SSH_TARGET"
