#!/usr/bin/env bash
# Updates operators' notices on the Oracle server from this PC, with no restart and no deploy; open apps see them
# within a minute. push.sh runs this after every deploy.
# - Arriva: arriva.si has blocked networks outside Slovenia, the server's among them, so the posts are read here and sent
#   over SSH to `manage.py arriva_notices --import`.
# - SŽ: its list of disruptions is in no open feed, so you save the page in your browser and pass the file with --sz; it
#   goes to `manage.py sz_notices --import`, and the replacement timetables it links are read at once.
#
#   yarn server:update                 # Arriva: read and send
#   yarn server:update --sz page.html  # ... and SŽ's list, saved from potniski.sz.si/ovire-in-izredne-spremembe
#   yarn server:update --check         # only read Arriva's here and say how many there are
#   bash backend/deploy/oracle/notices-remote.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check=""
sz_page=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check=1; shift ;;
    --sz)
      [ $# -ge 2 ] || { echo "--sz needs the saved page's file." >&2; exit 2; }
      sz_page="$2"; shift 2 ;;
    *) echo "Usage: yarn server:update [--check] [--sz <saved page>]" >&2; exit 2 ;;
  esac
done
if [ -n "$sz_page" ]; then
  [ -f "$sz_page" ] || sz_page="$(wslpath "$sz_page" 2>/dev/null || echo "$sz_page")"  # a Windows path, through yarn
  [ -f "$sz_page" ] || { echo "No such file: $sz_page" >&2; exit 1; }
  # Checked again on the server; this only saves a trip with the wrong file.
  listed="$(grep -c 'id="heading-' "$sz_page" || true)"
  [ "$listed" -gt 0 ] || { echo "$sz_page has no notices of SŽ's list. Save the whole page, or the list's outer HTML (not its text)." >&2; exit 1; }
  echo "==> SŽ's list: $listed notices in $sz_page"
fi

posts="$(mktemp)"
trap 'rm -f "$posts"' EXIT

# As operator_notices._load_arriva reads them: the 100 newest posts of the last 100 days.
echo "==> Reading Arriva's notices from this PC"
count=0
if curl --fail --silent --show-error --location --compressed --max-time 40 --max-filesize 4194304 \
    --user-agent 'KamGre/0.1 (+https://kamgre.si)' --get 'https://arriva.si/wp-json/wp/v2/posts' \
    --data-urlencode 'per_page=100' --data-urlencode "after=$(date -d '100 days ago' +%Y-%m-%dT00:00:00)" \
    --data-urlencode '_fields=id,date,link,title,content' --output "$posts"; then
  count="$(python3 -c 'import json, sys; posts = json.load(open(sys.argv[1], encoding="utf-8")); print(len(posts) if isinstance(posts, list) else 0)' "$posts" 2>/dev/null || echo 0)"
fi
failed=""
if [ "$count" -lt 1 ]; then
  echo "Could not read Arriva's posts from this PC. Its notices on the server stay as they were." >&2
  failed=1
else
  echo "    $count posts"
fi
if [ -n "$check" ]; then
  [ -z "$failed" ]
  exit
fi
[ -z "$failed" ] || [ -n "$sz_page" ] || exit 1

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

# The files land owned by the API's user; the commands are on the server from the first `yarn server:push` that has them.
if [ -z "$failed" ]; then
  echo "==> Sending Arriva's to $SSH_TARGET"
  if ! ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage arriva_notices --import" < "$posts"; then
    echo "Arriva's not updated. If the server says the command is unknown, it needs \`yarn server:push\` first." >&2
    failed=1
  fi
fi
if [ -n "$sz_page" ]; then
  echo "==> Sending SŽ's list to $SSH_TARGET"
  if ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage sz_notices --import" < "$sz_page"; then
    echo "==> Reading the timetables it links"
    ssh "${ssh_opts[@]}" "$SSH_TARGET" "cd /tmp && sudo prestop-manage szpdf_sync" \
      || echo "Not read now; the timer tries again within 30 minutes." >&2
  else
    echo "SŽ's list not updated. If the server says the command is unknown, it needs \`yarn server:push\` first." >&2
    failed=1
  fi
fi
[ -z "$failed" ]
