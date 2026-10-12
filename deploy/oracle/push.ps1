<#
.SYNOPSIS
Deploys the Prestop backend to the Oracle server by running push.sh in WSL.
The web app is deployed separately by Vercel on every push to GitHub (see README).

.EXAMPLE
powershell -File backend/deploy/oracle/push.ps1
#>
param([string]$Distro = 'kali-linux')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Push-Location $root
try {
    wsl -d $Distro -- bash backend/deploy/oracle/push.sh
    if ($LASTEXITCODE) { throw "Deploy failed (exit $LASTEXITCODE)" }
    # AGPL: the source of what the server runs is published for its users.
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/publish-backend.ps1
} finally {
    Pop-Location
}
