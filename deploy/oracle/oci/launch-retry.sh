#!/usr/bin/env bash
# Retries creating the Always Free A1 instance until Oracle has capacity ("Out of host capacity").
# Runs in WSL with the OCI CLI configured (see README: "Out of host capacity"), or in OCI Cloud Shell.
#
#   SSH_PUBLIC_KEY=~/.ssh/oracle_prestop.pub bash backend/deploy/oracle/oci/launch-retry.sh
#
# Optional: NAME, OCPUS (2), MEMORY_GB (12), BOOT_GB (100), SUBNET_NAME (first public subnet),
#           INTERVAL seconds between rounds (60), COMPARTMENT (the root compartment).
# Never exceeds the Always Free allowance: 2 OCPU / 12 GB is the whole free A1 quota.
set -uo pipefail

NAME="${NAME:-prestop}"
OCPUS="${OCPUS:-2}"
MEMORY_GB="${MEMORY_GB:-12}"
BOOT_GB="${BOOT_GB:-100}"
INTERVAL="${INTERVAL:-60}"
SSH_PUBLIC_KEY="${SSH_PUBLIC_KEY:?set SSH_PUBLIC_KEY to your .pub file (ssh-keygen -y -f key > key.pub makes one)}"
[ -r "$SSH_PUBLIC_KEY" ] || { echo "cannot read $SSH_PUBLIC_KEY" >&2; exit 1; }
command -v oci >/dev/null || { echo "OCI CLI not found (see README)" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found: sudo apt install jq" >&2; exit 1; }
if [ "$OCPUS" -gt 2 ] || [ "$MEMORY_GB" -gt 12 ] || [ "$BOOT_GB" -gt 200 ]; then
  echo "refusing: above the Always Free allowance (2 OCPU, 12 GB, 200 GB disk)" >&2; exit 1
fi
# Only launch into an account whose guardrails are in place and that has nothing billable.
if ! audit="$(bash "$(dirname "${BASH_SOURCE[0]}")/audit.sh" 2>&1)"; then
  printf '%s\n' "$audit" | grep -E 'FAIL|problem' >&2
  echo "refusing to launch until audit.sh passes (run oci/guardrails.sh first)" >&2; exit 1
fi

# Root compartment = tenancy OCID (Cloud Shell sets OCI_TENANCY; locally it is in ~/.oci/config).
COMPARTMENT="${COMPARTMENT:-${OCI_TENANCY:-$(awk -F= '/^tenancy/ {gsub(/ /, "", $2); print $2; exit}' ~/.oci/config 2>/dev/null)}}"
[ -n "$COMPARTMENT" ] || { echo "set COMPARTMENT to your tenancy OCID" >&2; exit 1; }

echo "Looking up the existing setup..."
existing="$(oci compute instance list -c "$COMPARTMENT" --all 2>/dev/null |
  jq -r '.data[]? | select(.shape == "VM.Standard.A1.Flex" and .["lifecycle-state"] != "TERMINATED") | "\(.["display-name"]) (\(.["lifecycle-state"]))"')"
if [ -n "$existing" ]; then
  echo "An A1 instance already exists: $existing. Not creating another." >&2; exit 1
fi

if [ -n "${SUBNET_NAME:-}" ]; then
  subnet="$(oci network subnet list -c "$COMPARTMENT" --all | jq -r --arg n "$SUBNET_NAME" '[.data[] | select(.["display-name"] == $n)][0].id // empty')"
else
  subnet="$(oci network subnet list -c "$COMPARTMENT" --all | jq -r '[.data[] | select(.["prohibit-public-ip-on-vnic"] == false and .["lifecycle-state"] == "AVAILABLE")][0].id // empty')"
fi
[ -n "$subnet" ] || { echo "no public subnet found (create one with the VCN wizard)" >&2; exit 1; }
echo "  subnet: $(oci network subnet get --subnet-id "$subnet" | jq -r '.data["display-name"]')"

image="$(oci compute image list -c "$COMPARTMENT" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
  --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC --limit 1 | jq -r '.data[0].id // empty')"
[ -n "$image" ] || { echo "no Ubuntu 24.04 image for A1 found" >&2; exit 1; }
echo "  image:  $(oci compute image get --image-id "$image" | jq -r '.data["display-name"]')"

mapfile -t ads < <(oci iam availability-domain list -c "$COMPARTMENT" | jq -r '.data[].name')
echo "  availability domains: ${ads[*]}"
echo "  shape:  VM.Standard.A1.Flex, $OCPUS OCPU, $MEMORY_GB GB, ${BOOT_GB} GB boot volume"
echo
echo "Trying every ${INTERVAL}s until it works (Ctrl+C to stop)."

attempt=0
while true; do
  for ad in "${ads[@]}"; do
    attempt=$((attempt + 1))
    out="$(oci compute instance launch \
      --compartment-id "$COMPARTMENT" --availability-domain "$ad" \
      --display-name "$NAME" --shape VM.Standard.A1.Flex \
      --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
      --image-id "$image" --boot-volume-size-in-gbs "$BOOT_GB" \
      --subnet-id "$subnet" --assign-public-ip true \
      --ssh-authorized-keys-file "$SSH_PUBLIC_KEY" \
      --wait-for-state RUNNING --max-wait-seconds 900 2>&1)"
    status=$?
    if [ $status -eq 0 ]; then
      id="$(printf '%s' "$out" | sed -n '/^{/,$p' | jq -r '.data.id')"
      ip="$(oci compute instance list-vnics --instance-id "$id" | jq -r '.data[0]["public-ip"]')"
      printf '\n%s  Created after %s attempts in %s.\nPublic IP: %s\nPut it in config.local: SSH_TARGET=ubuntu@%s\n' "$(date '+%F %T')" "$attempt" "$ad" "$ip" "$ip"
      exit 0
    fi
    case "$out" in
      *"Out of host capacity"*|*"Out of capacity"*)
        printf '%s  attempt %s (%s): out of capacity\n' "$(date '+%F %T')" "$attempt" "${ad##*:}" ;;
      *TooManyRequests*|*"429"*)
        printf '%s  attempt %s: rate limited, waiting longer\n' "$(date '+%F %T')" "$attempt"; sleep $((INTERVAL * 3)) ;;
      *LimitExceeded*|*QuotaExceeded*)
        echo "$out" | tail -5; echo "Free-tier limit reached (an instance may already exist). Stopping." >&2; exit 1 ;;
      *)
        echo "$out" | tail -8; echo "Unexpected error. Stopping so nothing wrong gets retried." >&2; exit 1 ;;
    esac
  done
  sleep "$((INTERVAL + RANDOM % 15))"
done
