#!/usr/bin/env bash
# Locks the Oracle account to the Always Free allowance so nothing billable can be created,
# by a wrong click in the console or by a script. Safe to re-run; re-run after Oracle adds services.
#
#   bash backend/deploy/oracle/oci/guardrails.sh            # apply
#   bash backend/deploy/oracle/oci/guardrails.sh --dry-run  # only print what it would set
#
# What it sets (quota policies and budgets are free):
#   1. Quota policy "free-tier-allowance": compute zeroed except A1 at 2 OCPU / 12 GB, block storage
#      200 GB / 5 backups / no replicas, object storage 20 GB, no reserved public IPs.
#   2. Quota policies "free-tier-zero-N": every other quota-capable service zeroed (databases, load
#      balancers, GPUs, firewalls, ...), except the free plumbing listed in KEEP below.
#   3. A monthly budget of 1 USD on the whole tenancy with e-mail alerts at 0.01 actual and 1.00 forecast.
# Quotas block creating new resources; they never stop or delete running ones.
# To lift one deliberately: edit this file (never the console), re-run, and say why in the commit.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
dry=0; [ "${1:-}" = --dry-run ] && dry=1

# Free services this setup needs or that cannot cost anything; everything else quota-capable is zeroed.
KEEP="compute block-storage object-storage vcn vcnip identity compartments limits tagging
  security-attributes cloud-shell logging notifications events monitoring oci-bastion dns
  resource-manager dashboard subscription-pricing"
KEEP=" $(echo $KEEP) "

# Compute quotas live in three families: cores in compute-core, memory in compute-memory, the rest
# (shape counts, images, clusters) in compute. All three are zeroed; only A1 gets an allowance.
# https://docs.oracle.com/en-us/iaas/Content/Quotas/Concepts/resourcequotas_topic-Compute_Quotas.htm
allowance=(
  "zero compute quotas in tenancy"
  "zero compute-core quotas in tenancy"
  "zero compute-memory quotas in tenancy"
  "set compute-core quota standard-a1-core-count to $FREE_A1_OCPUS in tenancy"
  "set compute-memory quota standard-a1-memory-count to $FREE_A1_MEMORY_GB in tenancy"
  "set compute-core quota standard-a1-core-regional-count to $FREE_A1_OCPUS in tenancy"
  "set compute-memory quota standard-a1-memory-regional-count to $FREE_A1_MEMORY_GB in tenancy"
  "zero block-storage quotas in tenancy"
  "set block-storage quota total-storage-gb to $FREE_STORAGE_GB in tenancy"
  "set block-storage quota volume-count to 4 in tenancy"
  "set block-storage quota backup-count to $FREE_VOLUME_BACKUPS in tenancy"
  "set object-storage quota storage-bytes to $FREE_OBJECT_BYTES in tenancy"
  "zero vcn quota reserved-public-ip-count in tenancy"
)

echo "==> Reading the services Oracle offers this account"
mapfile -t services < <(oci limits service list -c "$TENANCY" --all | jq -r '.data[].name' | sort)
zero=()
for s in "${services[@]}"; do
  case "$KEEP" in *" $s "*) continue ;; esac
  n="$(oci limits definition list -c "$TENANCY" --service-name "$s" --all 2>/dev/null |
    jq '[.data[] | select(.["are-quotas-supported"])] | length')"
  [ "${n:-0}" -gt 0 ] && zero+=("zero $s quotas in tenancy")
done
echo "    ${#services[@]} services; zeroing ${#zero[@]}, keeping:$KEEP"

# One policy per 40 statements. Zero and set for a family must share a policy: across policies the
# most restrictive wins, so a separate "zero compute-core" would cancel the A1 allowance.
put_policy() {  # name, description, statements...
  local name="$1" desc="$2"; shift 2
  local json; json="$(printf '%s\n' "$@" | jq -R . | jq -sc .)"
  if [ "$dry" = 1 ]; then printf '\n[%s]\n' "$name"; printf '  %s\n' "$@"; return; fi
  local id; id="$(oci limits quota list -c "$TENANCY" --all --name "$name" | jq -r '.data[0].id // empty')"
  if [ -n "$id" ]; then
    oci limits quota update --quota-id "$id" --statements "$json" --description "$desc" --force >/dev/null
    echo "    updated $name"
  else
    oci limits quota create -c "$TENANCY" --name "$name" --description "$desc" --statements "$json" >/dev/null
    echo "    created $name"
  fi
}

echo "==> Quota policies"
put_policy free-tier-allowance "Always Free only: A1 2 OCPU/12 GB, 200 GB disk, 5 backups, 20 GB object storage. Managed by backend/deploy/oracle/oci/guardrails.sh" "${allowance[@]}"
i=0
for ((start = 0; start < ${#zero[@]}; start += 40)); do
  i=$((i + 1))
  put_policy "free-tier-zero-$i" "Services with no Always Free use here, zeroed. Managed by guardrails.sh" "${zero[@]:start:40}"
done
# Drop leftovers when the list shrinks.
if [ "$dry" = 0 ]; then
  oci limits quota list -c "$TENANCY" --all | jq -r '.data[] | "\(.id) \(.name)"' | while read -r id name; do
    case "$name" in free-tier-zero-*)
      if [ "${name#free-tier-zero-}" -gt "$i" ]; then oci limits quota delete --quota-id "$id" --force; echo "    removed $name"; fi ;;
    esac
  done
fi

echo "==> Budget alert"
budgets="$(oci budgets budget budget list -c "$TENANCY" --all --target-type ALL)"
budget="$(jq -r --arg t "$TENANCY" '[.data[] | select(.["target-type"] == "COMPARTMENT" and (.targets | index($t)) and .amount <= 1)][0].id // empty' <<<"$budgets")"
if [ -z "$budget" ]; then
  if [ "$dry" = 1 ]; then echo "    would create budget $BUDGET_NAME_DEFAULT (1 USD/month)"
  else
    budget="$(oci budgets budget budget create -c "$TENANCY" --amount 1 --reset-period MONTHLY \
      --target-type COMPARTMENT --targets "[\"$TENANCY\"]" --display-name "$BUDGET_NAME_DEFAULT" \
      --description "Any spend means something left the Always Free allowance" | jq -r '.data.id')"
    echo "    created budget $BUDGET_NAME_DEFAULT"
  fi
else
  echo "    using budget $(jq -r --arg id "$budget" '.data[] | select(.id == $id) | .["display-name"]' <<<"$budgets")"
fi
if [ -n "$budget" ]; then
  rules="$(oci budgets budget alert-rule list --budget-id "$budget" --all)"
  recipients="${ALERT_EMAIL:-$(jq -r '[.data[].recipients // empty | select(. != "")][0] // empty' <<<"$rules")}"
  if [ -z "$recipients" ]; then
    user="$(awk -F= '/^user/ {gsub(/[ \r]/, "", $2); print $2; exit}' ~/.oci/config)"
    recipients="$(oci iam user get --user-id "$user" | jq -r '.data.email // empty')"
  fi
  [ -n "$recipients" ] || die "no e-mail for budget alerts: run with ALERT_EMAIL=you@example.com"
  ensure_rule() {  # type, threshold in USD
    local match; match="$(jq -c --arg t "$1" --argjson v "$2" '
      [.data[] | select(.type == $t and ((.["threshold-type"] == "ABSOLUTE" and .threshold <= $v) or
        (.["threshold-type"] == "PERCENTAGE" and .threshold <= ($v * 100))))]' <<<"$rules")"
    if [ "$(jq length <<<"$match")" -gt 0 ]; then
      # A rule made in the console can have no recipients, and then it never e-mails anyone.
      local id; for id in $(jq -r '.[] | select((.recipients // "") == "") | .id' <<<"$match"); do
        if [ "$dry" = 1 ]; then echo "    would set the e-mail of the $1 alert (it has none)"
        else
          oci budgets budget alert-rule update --budget-id "$budget" --alert-rule-id "$id" --recipients "$recipients" --force >/dev/null
          echo "    $1 alert had no e-mail: set it"
        fi
      done
      echo "    $1 alert at <= $2 USD present"; return
    fi
    if [ "$dry" = 1 ]; then echo "    would add $1 alert at $2 USD"; return; fi
    oci budgets budget alert-rule create --budget-id "$budget" --type "$1" --threshold "$2" \
      --threshold-type ABSOLUTE --recipients "$recipients" --display-name "free-tier-$(tr 'A-Z' 'a-z' <<<"$1")" \
      --message "Oracle Cloud is about to charge your card: something is outside the Always Free allowance. Run backend/deploy/oracle/oci/audit.sh." >/dev/null
    echo "    added $1 alert at $2 USD"
  }
  ensure_rule ACTUAL 0.01
  ensure_rule FORECAST 1
fi

[ "$dry" = 1 ] && exit 0
echo "==> Checking the quotas took effect"
ad="$(oci iam availability-domain list -c "$TENANCY" | jq -r '.data[0].name')"
effective() {  # service, limit, [ad]
  oci limits resource-availability get -c "$TENANCY" --service-name "$1" --limit-name "$2" ${3:+--availability-domain "$3"} |
    jq -r '.data["effective-quota-value"] // "none"'
}
ok=1
check() {  # label, expected, actual
  if [ "$3" = "$2" ] || { [ "$3" != none ] && awk -v a="$3" -v b="$2" 'BEGIN { exit !(a + 0 == b + 0) }'; }; then
    printf '    ok    %-34s %s\n' "$1" "$3"
  else
    printf '    WAIT  %-34s %s (want %s)\n' "$1" "$3" "$2"; ok=0
  fi
}
check "A1 OCPUs" "$FREE_A1_OCPUS" "$(effective compute standard-a1-core-count "$ad")"
check "A1 memory GB" "$FREE_A1_MEMORY_GB" "$(effective compute standard-a1-memory-count "$ad")"
check "AMD E4 cores (paid)" 0 "$(effective compute standard-e4-core-count "$ad")"
check "Disk GB" "$FREE_STORAGE_GB" "$(effective block-storage total-storage-gb "$ad")"
check "Flexible load balancers" 0 "$(effective load-balancer lb-flexible-count)"
[ "$ok" = 1 ] && echo "Guardrails active." || echo "Some quotas show old values; Oracle can take a few minutes. Re-run to check."
