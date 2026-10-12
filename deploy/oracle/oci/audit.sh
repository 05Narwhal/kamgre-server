#!/usr/bin/env bash
# Read-only check that nothing in the Oracle account can be billed. Changes nothing.
# Exit 0 = everything inside the Always Free allowance; 1 = something needs fixing (listed as FAIL).
# push.sh and launch-retry.sh run it first and stop on FAIL.
#
#   bash backend/deploy/oracle/oci/audit.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

fails=0
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; fails=$((fails + 1)); }
T="$TENANCY"
mapfile -t ads < <(oci iam availability-domain list -c "$T" | jq -r '.data[].name')
# Every compartment, so nothing hides in a sub-compartment.
mapfile -t comps < <({ echo "$T"; oci iam compartment list -c "$T" --all --compartment-id-in-subtree true \
  --lifecycle-state ACTIVE | jq -r '.data[].id'; })
each() { for c in "${comps[@]}"; do "$@" -c "$c" --all 2>/dev/null | jq -c '.data[]?'; done; }
each_ad() { for c in "${comps[@]}"; do for a in "${ads[@]}"; do "$@" -c "$c" --availability-domain "$a" --all 2>/dev/null | jq -c '.data[]?'; done; done; }

echo "==> Region"
n="$(oci iam region-subscription list --tenancy-id "$T" | jq '.data | length')"
[ "$n" = 1 ] && ok "only the home region ($HOME_REGION)" || fail "$n regions subscribed; Always Free is home region only"

echo "==> Instances"
instances="$(each oci compute instance list | jq -sc '[.[] | select(.["lifecycle-state"] != "TERMINATED")]')"
jq -r '.[] | "\(.["display-name"]) \(.shape) \(.["shape-config"].ocpus // "?") OCPU \(.["shape-config"]["memory-in-gbs"] // "?") GB \(.["lifecycle-state"])"' <<<"$instances" | sed 's/^/        /'
bad="$(jq -r '.[] | select(.shape != "VM.Standard.A1.Flex" and .shape != "VM.Standard.E2.1.Micro") | "\(.["display-name"]) (\(.shape))"' <<<"$instances")"
[ -z "$bad" ] && ok "only Always Free shapes" || fail "paid shape: $bad"
read -r cpu mem < <(jq -r '[.[] | select(.shape == "VM.Standard.A1.Flex")] | "\(map(.["shape-config"].ocpus) | add // 0) \(map(.["shape-config"]["memory-in-gbs"]) | add // 0)"' <<<"$instances")
awk -v c="$cpu" -v m="$mem" -v C="$FREE_A1_OCPUS" -v M="$FREE_A1_MEMORY_GB" 'BEGIN { exit !(c <= C && m <= M) }' \
  && ok "A1 total $cpu OCPU / $mem GB (free: $FREE_A1_OCPUS / $FREE_A1_MEMORY_GB)" || fail "A1 total $cpu OCPU / $mem GB exceeds $FREE_A1_OCPUS / $FREE_A1_MEMORY_GB"
micro="$(jq '[.[] | select(.shape == "VM.Standard.E2.1.Micro")] | length' <<<"$instances")"
[ "$micro" -le "$FREE_MICRO_INSTANCES" ] || fail "$micro E2.1.Micro instances (free: $FREE_MICRO_INSTANCES)"
odd="$(jq -r '.[] | select(.["preemptible-instance-config"] or .["capacity-reservation-id"] or .["dedicated-vm-host-id"]) | .["display-name"]' <<<"$instances")"
[ -z "$odd" ] && ok "no preemptible, reserved or dedicated-host capacity" || fail "paid capacity type: $odd"

echo "==> Disks"
boots="$(each_ad oci bv boot-volume list | jq -sc '[.[] | select(.["lifecycle-state"] != "TERMINATED")]')"
vols="$(each oci bv volume list | jq -sc '[.[] | select(.["lifecycle-state"] != "TERMINATED")]')"
total="$(jq -n --argjson b "$boots" --argjson v "$vols" '[($b + $v)[] | .["size-in-gbs"]] | add // 0')"
[ "$total" -le "$FREE_STORAGE_GB" ] && ok "${total} GB of volumes (free: $FREE_STORAGE_GB)" || fail "${total} GB of volumes exceeds $FREE_STORAGE_GB GB"
fast="$(jq -rn --argjson b "$boots" --argjson v "$vols" --argjson max "$FREE_VPUS_PER_GB" \
  '($b + $v)[] | select((.["vpus-per-gb"] // 10) > $max or .["is-auto-tune-enabled"] == true or ((.["autotune-policies"] // []) | length > 0)) | "\(.["display-name"]) (\(.["vpus-per-gb"]) VPU/GB)"')"
[ -z "$fast" ] && ok "all volumes at Balanced performance, no auto-tune" || fail "billed performance level: $fast"
repl="$(jq -rn --argjson b "$boots" --argjson v "$vols" '($b + $v)[] | select(((.["boot-volume-replicas"] // .["block-volume-replicas"] // []) | length) > 0) | .["display-name"]')"
[ -z "$repl" ] || fail "volume replication is billed: $repl"
backups="$(( $(each oci bv boot-volume-backup list | jq -s '[.[] | select(.["lifecycle-state"] != "TERMINATED")] | length') + \
             $(each oci bv backup list | jq -s '[.[] | select(.["lifecycle-state"] != "TERMINATED")] | length') ))"
[ "$backups" -le "$FREE_VOLUME_BACKUPS" ] && ok "$backups volume backups (free: $FREE_VOLUME_BACKUPS)" || fail "$backups volume backups exceeds $FREE_VOLUME_BACKUPS"
for id in $(jq -rn --argjson b "$boots" --argjson v "$vols" '($b + $v)[].id'); do
  pol="$(oci bv volume-backup-policy-assignment get-volume-backup-policy-asset-assignment --asset-id "$id" 2>/dev/null | jq -r '.data[0]["policy-id"] // empty')"
  [ -z "$pol" ] || fail "scheduled backup policy on a volume (fills past $FREE_VOLUME_BACKUPS backups): $id"
done

echo "==> Object storage"
ns="$(oci os ns get | jq -r .data)"
bytes=0
for c in "${comps[@]}"; do
  for b in $(oci os bucket list -c "$c" -ns "$ns" --all 2>/dev/null | jq -r '.data[]?.name'); do
    sz="$(oci os bucket get -bn "$b" -ns "$ns" --fields approximateSize | jq -r '.data["approximate-size"] // 0')"
    bytes=$((bytes + sz))
  done
done
[ "$bytes" -le "$FREE_OBJECT_BYTES" ] && ok "$((bytes / 1000000)) MB in buckets (free: 20 GB)" || fail "$((bytes / 1000000)) MB in buckets exceeds 20 GB"

echo "==> Networking"
lbs="$(each oci lb load-balancer list | jq -sc '.')"
paid_lb="$(jq -r '.[] | select(.["shape-name"] != "flexible" or (.["shape-details"]["maximum-bandwidth-in-mbps"] // 0) > 10) | .["display-name"]' <<<"$lbs")"
[ -z "$paid_lb" ] || fail "load balancer above the free 10 Mbps: $paid_lb"
[ "$(jq length <<<"$lbs")" -le 1 ] || fail "more than one load balancer (1 is free)"
pub_zones="$(each oci dns zone list | jq -r 'select(.scope != "PRIVATE") | .name')"
[ -z "$pub_zones" ] || warn "public DNS zones in Oracle (Cloudflare does DNS here): $pub_zones"
ok "load balancers: $(jq length <<<"$lbs")"

echo "==> Everything else in the account"
# Resource types known to be free (or only billable through limits checked above).
FREE_TYPES=" Instance BootVolume Volume BootVolumeBackup VolumeBackup Image Vnic PrivateIp PublicIp Vcn Subnet
  RouteTable SecurityList NetworkSecurityGroup InternetGateway NatGateway ServiceGateway DHCPOptions DnsResolver
  DnsView CustomerDnsZone Compartment User Group Policy DynamicGroup App TagNamespace TagDefault Budget Bucket
  OnsTopic OnsSubscription EventRule LogGroup Log Alarm Bastion Quota Domain ApiKey "
FREE_TYPES=" $(echo $FREE_TYPES) "
if found="$(oci search resource structured-search --limit 1000 \
    --query-text "query all resources where lifeCycleState != 'TERMINATED' && lifeCycleState != 'DELETED'")"; then
  types="$(jq -r '.data.items[] | .["resource-type"]' <<<"$found" | sort | uniq -c)"
else
  types=""; fail "resource search failed, so unknown resources could not be checked"
fi
unknown=""
while read -r count type; do
  [ -n "$type" ] || continue
  case "$FREE_TYPES" in *" $type "*) ;; *) unknown+=" $type($count)" ;; esac
done <<<"$types"
[ -z "$unknown" ] && ok "only known-free resource types" \
  || fail "resource types not known to be free:$unknown (check pricing; delete, or add to FREE_TYPES in audit.sh if free)"

echo "==> Spend (usage data lags a few hours)"
from="$(date -u -d "$(date -u +%Y-%m-01) -1 month" +%Y-%m-%dT00:00:00Z)"; to="$(date -u -d tomorrow +%Y-%m-%dT00:00:00Z)"
if usage="$(oci usage-api usage-summary request-summarized-usages --tenant-id "$T" --granularity MONTHLY --query-type COST \
    --time-usage-started "$from" --time-usage-ended "$to" --group-by '["service"]')"; then
  spend="$(jq -r '[.data.items[] | select((.["computed-amount"] // 0) > 0)] | map("\(.service) \(.["computed-amount"]) \(.currency)") | join(", ")' <<<"$usage")"
  [ -z "$spend" ] && ok "0.00 since $(cut -c1-10 <<<"$from")" || fail "billed usage (or trial credits used): $spend"
else
  fail "could not read spend from the Usage API"
fi

echo "==> Guardrails"
quotas="$(oci limits quota list -c "$T" --all | jq -r '[.data[].name] | join(" ")')"
case " $quotas " in *" free-tier-allowance "*) ok "quota policies: $quotas" ;; *) fail "quota policies missing: run oci/guardrails.sh" ;; esac
budgets="$(oci budgets budget budget list -c "$T" --all --target-type ALL | jq -c --arg t "$T" \
  '[.data[] | select((.targets | index($t)) and .amount <= 1 and .["alert-rule-count"] > 0)]')"
budget="$(jq -r '.[0] | "\(.["display-name"]) (spent \(.["actual-spend"]), forecast \(.["forecasted-spend"]))" // empty' <<<"$budgets")"
budget_id="$(jq -r '.[0].id // empty' <<<"$budgets")"
# An alert without an e-mail address never reaches anyone.
mailed="$([ -n "$budget_id" ] && oci budgets budget alert-rule list --budget-id "$budget_id" --all |
  jq '[.data[] | select(.type == "ACTUAL" and (.recipients // "") != "")] | length')"
if [ -z "$budget_id" ]; then fail "no 1 USD budget with alerts: run oci/guardrails.sh"
elif [ "${mailed:-0}" -gt 0 ]; then ok "budget alert: $budget"
else fail "budget alerts have no e-mail recipient: run oci/guardrails.sh"
fi

echo
if [ "$fails" = 0 ]; then echo "Audit passed: nothing billable found."; exit 0; fi
echo "Audit found $fails problem(s). Fix them before deploying (see README: Cost safety)."; exit 1
