#!/usr/bin/env bash
# Live server view in your own terminal: runs server/top.py on the Oracle server over SSH
# (q quits, ? lists the keys; hover graphs, click tabs). Sends the local copy of the script, so it works before the next deploy.
#
#   yarn server:top [seconds between updates, default 2] [tab]
#   yarn server:top logs            open on a tab: overview system services traffic data learning logs usage
#   yarn server:top usage week      the usage tab, for today, week, month or all
#   bash backend/deploy/oracle/top-remote.sh [seconds] [tab]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config.local"
[ -f "$CONFIG" ] || { echo "Copy config.local.example to config.local and fill it in." >&2; exit 1; }
# shellcheck source=/dev/null
. <(tr -d '\r' < "$CONFIG")
: "${SSH_TARGET:?set SSH_TARGET in config.local}"
args=()
for a in "$@"; do
  [[ $a =~ ^([0-9]+|overview|system|services|traffic|data|learning|logs|usage|today|week|month|all|--once)$ ]] \
    || { echo "Usage: yarn server:top [seconds] [overview|system|services|traffic|data|learning|logs|usage] [today|week|month|all]" >&2; exit 1; }
  args+=("$a")
done

ssh_opts=(-t -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [ -n "${SSH_KEY:-}" ]; then
  [ -f "$SSH_KEY" ] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  ssh_opts+=(-i "$SSH_KEY")
fi
# The script travels gzipped and base64-encoded inside the command line: no quoting trouble, well under ARG_MAX.
payload=$(tr -d '\r' < "$HERE/server/top.py" | gzip -9n | base64 -w0)
launch="import base64,sys,zlib; exec(compile(zlib.decompress(base64.b64decode('$payload'), 31), 'prestop-top', 'exec'))"
rc=0
ssh "${ssh_opts[@]}" "$SSH_TARGET" "sudo python3 -c $(printf %q "$launch") ${args[*]:-}" || rc=$?
# If the connection dropped, the far end never turned mouse reporting off, and every mouse move would type junk here.
printf '\033[?1003l\033[?1006l\033[?1000l'
exit "$rc"
