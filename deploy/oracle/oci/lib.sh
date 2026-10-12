# Shared by the scripts in this folder. Source it, don't run it.
# Needs the OCI CLI and jq in WSL, configured with ~/.oci/config (see README: "API key").

export PATH="$HOME/.local/bin:$PATH"
export OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING=True
die() { echo "error: $*" >&2; exit 1; }
command -v oci >/dev/null || die "OCI CLI not found (pip install --user oci-cli)"
command -v jq >/dev/null || die "jq not found (sudo apt install jq)"

# The Always Free allowance this account must stay inside (2026: A1 cut to 2 OCPU / 12 GB).
# https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm
FREE_A1_OCPUS=2
FREE_A1_MEMORY_GB=12
FREE_MICRO_INSTANCES=2           # VM.Standard.E2.1.Micro
FREE_STORAGE_GB=200              # boot + block volumes together
FREE_VOLUME_BACKUPS=5
FREE_VPUS_PER_GB=10              # "Balanced"; higher performance is billed
FREE_OBJECT_BYTES=20000000000    # 20 GB (decimal, under Oracle's 20 GB)
BUDGET_NAME_DEFAULT=free-tier-guard

TENANCY="${OCI_TENANCY:-$(awk -F= '/^tenancy/ {gsub(/[ \r]/, "", $2); print $2; exit}' ~/.oci/config 2>/dev/null)}"
[ -n "$TENANCY" ] || die "no tenancy in ~/.oci/config"
HOME_REGION="$(oci iam region-subscription list --tenancy-id "$TENANCY" | jq -r '.data[] | select(.["is-home-region"]) | .["region-name"]')"
[ -n "$HOME_REGION" ] || die "cannot read the home region (is the API key working? try: oci iam region list)"
# Always Free resources exist only in the home region; every call goes there.
export OCI_CLI_REGION="$HOME_REGION"
