#!/usr/bin/env bash
# prestop-egress.timer (every 5 minutes): Oracle bills outbound data above 10 TB a month, the only
# usage-based charge a fixed Always Free server can run into. Two stages, from this month's outbound data:
#
#   busy     above EGRESS_BUSY_GB (default 6000), or ahead of the month's pace (more than the pro-rata
#            share of EGRESS_LIMIT_GB plus one day's worth): writes $TRAFFIC/busy, so the API and Caddy
#            turn away new visitors while people already using the app keep working.
#   stopped  at EGRESS_LIMIT_GB (default 8000): stops cloudflared and Caddy and writes $STATE/egress-tripped,
#            which also keeps them from starting (systemd drop-in egress-hold.conf), even after a reboot.
#
# Everything starts again on its own when the next month (UTC) begins.
# Outbound data is the larger of vnstat's count and this script's own count of the kernel's interface
# counter, so a broken or reset vnstat database cannot hide traffic.
set -uo pipefail
STATE=/var/lib/prestop
TRAFFIC=$STATE/traffic
setting() { sed -n "s/^$1=\([0-9]*\).*/\1/p" /etc/prestop/prestop.env 2>/dev/null; }
limit="$(setting EGRESS_LIMIT_GB)"; limit="${limit:-8000}"
busy_at="$(setting EGRESS_BUSY_GB)"; busy_at="${busy_at:-6000}"
[ "$limit" -le 9000 ] || limit=9000   # never closer than 1 TB to the billed 10 TB
[ "$busy_at" -le "$limit" ] || busy_at="$limit"
mkdir -p "$TRAFFIC" && chmod 0755 "$TRAFFIC"

month="$(date -u +%Y-%m)"
iface="$(ip route show default | awk '{print $5; exit}')"

# 1. vnstat's monthly count (0 if it has none for this month).
vn_tx=0
if stats="$(vnstat --json m 1 -i "$iface" 2>/dev/null)"; then
  read -r vmonth tx < <(jq -r '.interfaces[0].traffic.month[0] // {} |
    "\(.date.year // 0)-\(.date.month // 0 | tostring | if length < 2 then "0" + . else . end) \(.tx // 0)"' <<<"$stats")
  [ "$vmonth" = "$month" ] && vn_tx="${tx:-0}"
fi

# 2. Own count: the kernel's transmit counter since the last run, summed per month. The counter
#    restarts at boot (boot_id changes), then everything it shows is new traffic.
counter=$STATE/egress-counter
cur="$(cat "/sys/class/net/$iface/statistics/tx_bytes" 2>/dev/null || echo 0)"
boot="$(cat /proc/sys/kernel/random/boot_id)"
read -r c_month c_boot c_last c_sum 2>/dev/null < "$counter" || true
if [ "${c_boot:-}" = "$boot" ] && [ "${c_last:-0}" -le "$cur" ]; then delta=$((cur - c_last)); else delta="$cur"; fi
[ "${c_month:-}" = "$month" ] && sum=$((c_sum + delta)) || sum="$delta"
echo "$month $boot $cur $sum" > "$counter.new" && mv "$counter.new" "$counter"

tx=$(( vn_tx > sum ? vn_tx : sum ))
used_gb=$((tx / 1000000000))

# Pace: the share of the limit for the time gone so far this month, plus one day.
start="$(date -u -d "$(date -u +%Y-%m-01)" +%s)"
next="$(date -u -d "$(date -u +%Y-%m-01) +1 month" +%s)"
now="$(date -u +%s)"
pace_gb=$(( limit * (now - start + 86400) / (next - start) ))

# Once tripped, stay stopped for the rest of the month, even if a counter later reads lower.
if [ "$used_gb" -ge "$limit" ] || [ "$(cat "$STATE/egress-tripped" 2>/dev/null)" = "$month" ]; then
  [ -f "$STATE/egress-tripped" ] || echo "egress limit reached: $used_gb GB >= $limit GB; stopping public traffic"
  echo "$month" > "$STATE/egress-tripped"
  touch "$TRAFFIC/stopped" "$TRAFFIC/busy"
  systemctl stop cloudflared caddy
  stage=stopped
else
  if [ -f "$STATE/egress-tripped" ]; then   # tripped in an earlier month
    rm -f "$STATE/egress-tripped" "$TRAFFIC/stopped"
    systemctl start caddy cloudflared
    echo "new month: public traffic back on"
  fi
  if [ "$used_gb" -ge "$busy_at" ] || [ "$used_gb" -gt "$pace_gb" ]; then
    [ -f "$TRAFFIC/busy" ] || echo "busy: $used_gb GB used (pace $pace_gb GB, busy at $busy_at GB); refusing new visitors"
    touch "$TRAFFIC/busy"
    stage=busy
  else
    [ -f "$TRAFFIC/busy" ] && echo "back on pace: new visitors welcome again"
    rm -f "$TRAFFIC/busy"
    stage=normal
  fi
fi
echo "outbound this month: $used_gb GB ($stage; pace $pace_gb GB, busy at $busy_at GB, stop at $limit GB; Oracle bills above 10000 GB)"
