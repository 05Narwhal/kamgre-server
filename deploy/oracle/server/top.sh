#!/usr/bin/env bash
# prestop-top: a live view of the server, redrawn in place every few seconds (q or Ctrl+C quits).
# Usage: sudo prestop-top [seconds between updates, default 2]
set -uo pipefail
INTERVAL=${1:-2}
SERVICES=(prestop-web prestop-collector prestop-push prestop-ingest prestop-floor caddy cloudflared postgresql redis-server)
IFACE=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
declare -A CPU_PREV
NET_PREV=""
T_PREV=0

cpu_ns() { systemctl show -p CPUUsageNSec --value "$1" 2>/dev/null | sed 's/[^0-9]//g'; }
mem_mb() { local m; m=$(systemctl show -p MemoryCurrent --value "$1" 2>/dev/null); [[ $m =~ ^[0-9]+$ ]] && echo $((m / 1048576)) || echo -; }
net_bytes() { awk -v i="$IFACE:" '$1 == i {print $2, $10}' /proc/net/dev; }
human() { awk -v b="$1" 'BEGIN { s="B/s KB/s MB/s GB/s"; split(s, u, " "); n=1; while (b >= 1024 && n < 4) { b /= 1024; n++ } printf "%.1f %s", b, u[n] }'; }

B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
envval() { sed -n "s/^$1=//p" /etc/prestop/prestop.env 2>/dev/null | tail -1 | tr -d '\r"'"'"; }
REDIS_URL=$(envval REDIS_URL); REDIS_URL=${REDIS_URL:-redis://127.0.0.1:6379/1}
MAX_ACTIVE=$(envval PRESTOP_TRAFFIC_MAX_ACTIVE); [[ $MAX_ACTIVE =~ ^[0-9]+$ ]] || MAX_ACTIVE=3000
PG=$(systemctl list-units 'postgresql@*' --plain --no-legend 2>/dev/null | awk '{print $1; exit}')
# bar <percent>: a 20-wide meter, yellow above 70%, red above 90%
bar() { local p=${1%.*} c=$G; ((p > 90)) && c=$R || { ((p > 70)) && c=$Y; }; local f=$((p * 20 / 100)); ((f > 20)) && f=20
  printf '%s%s%s%s%s' "$c" "$(printf '%*s' $f '' | tr ' ' '#')" "$D" "$(printf '%*s' $((20 - f)) '' | tr ' ' '.')" "$N"; }
dot() { case $1 in active) printf '%s●%s' "$G" "$N" ;; activating|reloading) printf '%s●%s' "$Y" "$N" ;; *) printf '%s●%s' "$R" "$N" ;; esac; }

tput civis; trap 'tput cnorm; echo; exit' INT TERM EXIT
clear
while true; do
  now=$(date +%s%N)
  out=$(
    printf '%sKamGre server%s   %s   load %s   %sq quits · %ss%s\n\n' "$B" "$N" "$(date '+%H:%M:%S')" "$(cut -d' ' -f1-3 /proc/loadavg)" "$D" "$INTERVAL" "$N"
    printf '%s  %-12s %6s %8s%s\n' "$D" SERVICE CPU MEM "$N"
    for s in "${SERVICES[@]}"; do
      u=$s; [[ $s == postgresql && -n $PG ]] && u=$PG
      ns=$(cpu_ns "$u"); pct=-
      if [[ -n $ns && -n ${CPU_PREV[$s]:-} && $T_PREV -gt 0 ]]; then pct=$(awk -v a="$ns" -v b="${CPU_PREV[$s]}" -v t=$((now - T_PREV)) 'BEGIN { printf "%.1f%%", (a - b) * 100 / t }'); fi
      CPU_PREV[$s]=$ns
      m=$(mem_mb "$u"); [[ $m != - ]] && m="$m MB"
      printf '%s %-12s %6s %8s\n' "$(dot "$(systemctl is-active "$u" 2>/dev/null)")" "${s#prestop-}" "$pct" "$m"
    done
    echo
    read -r _ total _ _ _ _ avail _ < <(free -m | awk 'NR==2')
    used=$((total - avail))
    printf 'Memory   %s  %4.1f / %.1f GB\n' "$(bar $((used * 100 / total)))" "$(awk "BEGIN{print $used/1024}")" "$(awk "BEGIN{print $total/1024}")"
    read -r dpct dused dsize < <(df -h / | awk 'NR==2 {print $5+0, $3, $2}')
    printf 'Disk     %s  %s / %s\n' "$(bar "$dpct")" "$dused" "$dsize"
    cur=$(net_bytes)
    if [[ -n $NET_PREV && -n $cur && $T_PREV -gt 0 ]]; then
      read -r rx0 tx0 <<<"$NET_PREV"; read -r rx1 tx1 <<<"$cur"; dt=$(( (now - T_PREV) / 1000000 )); ((dt > 0)) || dt=1
      printf 'Network  ↓ %s   ↑ %s\n' "$(human $(( (rx1 - rx0) * 1000 / dt )))" "$(human $(( (tx1 - tx0) * 1000 / dt )))"
    else printf 'Network  %smeasuring…%s\n' "$D" "$N"; fi
    NET_PREV=$cur
    eg=$(/opt/prestop/deploy/server/egress-guard.sh 2>/dev/null | tail -1)
    if [[ $eg =~ month:\ ([0-9.]+)\ GB\ \(([a-z]+)\;\ pace\ ([0-9]+).*stop\ at\ ([0-9]+) ]]; then
      printf 'Egress   %s  %s / %s GB this month  %s%s, pace %s GB%s\n' "$(bar $(awk "BEGIN{print ${BASH_REMATCH[1]}*100/${BASH_REMATCH[4]}}"))" "${BASH_REMATCH[1]}" "${BASH_REMATCH[4]}" "$D" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "$N"
    else printf 'Egress   %s\n' "$eg"; fi
    printf 'API      %s open connections\n' "$(ss -Htn state established '( sport = :8066 )' 2>/dev/null | wc -l)"
    # Active users: the traffic guard's per-minute HyperLogLogs of hashed client IPs (prestop_api/traffic.py)
    min=$(( $(date +%s) / 60 )); k1=() k5=() k15=()
    for i in $(seq 0 14); do k=traffic:active:$((min - i)); k15+=("$k"); ((i < 5)) && k5+=("$k"); ((i < 1)) && k1+=("$k"); done
    if a15=$(redis-cli -u "$REDIS_URL" --no-auth-warning PFCOUNT "${k15[@]}" 2>/dev/null) && [[ $a15 =~ ^[0-9]+$ ]]; then
      printf 'Users    %s  %s in 15 min / %s  %snow %s · 5 min %s%s\n' "$(bar $((a15 * 100 / MAX_ACTIVE)))" "$a15" "$MAX_ACTIVE" "$D" \
        "$(redis-cli -u "$REDIS_URL" --no-auth-warning PFCOUNT "${k1[@]}")" "$(redis-cli -u "$REDIS_URL" --no-auth-warning PFCOUNT "${k5[@]}")" "$N"
    else printf 'Users    %sunavailable%s\n' "$R" "$N"; fi
    health=$(curl -fsS -o /tmp/prestop-top-health -w '%{time_total}' --max-time 5 http://127.0.0.1:8066/api/v1/health 2>/dev/null) \
      && printf 'Health   %s ms  %s\n' "$(awk -v t="$health" 'BEGIN { printf "%d", t * 1000 }')" "$(jq -r '"api \(.api) · db \(.database) · collector \(.collector.status // "?")" + (if .collector.updatedAt then " (\(now - (.collector.updatedAt | sub("\.[0-9]+"; "") | fromdateiso8601) | floor)s ago)" else "" end)' /tmp/prestop-top-health 2>/dev/null)" \
      || printf 'Health   %sunavailable%s\n' "$R" "$N"
    if [ -f /run/prestop-floor/status.json ]; then
      jq -r '"Floor    CPU \(.cpu_total)%  '"$D"'workload \(.cpu_workload)% · filler \(.cpu_filler_duty)% · mem \(.mem_used)%'"$N"'"' /run/prestop-floor/status.json
    fi
  )
  T_PREV=$now
  tput cup 0 0; printf '%s' "$out"; tput ed
  read -rsn1 -t "$INTERVAL" key && [[ $key == q ]] && break
done
