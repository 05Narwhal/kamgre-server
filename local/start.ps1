# Starts the local Prestop backend from Windows: `yarn backend`.
#
# 1. Starts PostGIS + Redis inside WSL (needed once per WSL boot; harmless otherwise).
# 2. Stops an API server or collector left running from an earlier start, so the
#    new server can bind port 8066 and only one collector polls.
# 3. Starts the local Valhalla road router if it is set up (ojpp.sh valhalla).
# 4. Opens windows for the API server (:8066), the delay collector and, when VAPID
#    keys are set in ojpp-django/.env, the push sender. Close a window (or Ctrl+C)
#    to stop it.
# This terminal stays free, e.g. for `yarn dev:live`.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$distro = 'kali-linux'

Push-Location $repo
try {
    wsl -d $distro -u root -- bash backend/local/ojpp.sh up
    if ($LASTEXITCODE -ne 0) { throw "Starting PostGIS/Redis failed (exit $LASTEXITCODE)." }
    wsl -d $distro -- bash backend/local/ojpp.sh stop
    # The local road router for bus shapes, when it is set up (ojpp.sh valhalla); it keeps running.
    wsl -d $distro -- bash backend/local/ojpp.sh valhalla
} finally {
    Pop-Location
}

$serve = "wsl -d $distro -- bash backend/local/ojpp.sh serve"
$collect = "wsl -d $distro -- bash backend/local/ojpp.sh collect"
$push = "wsl -d $distro -- bash backend/local/ojpp.sh push"
$pushReady = Select-String -Quiet -Path (Join-Path $repo 'backend\ojpp-django\.env') -Pattern '^PRESTOP_VAPID_PRIVATE_KEY=.' -ErrorAction SilentlyContinue

if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
    # `-w new` forces a separate Windows Terminal window for each process.
    Start-Process wt.exe -ArgumentList "-w new new-tab --title `"Prestop API`" -d `"$repo`" $serve"
    Start-Process wt.exe -ArgumentList "-w new new-tab --title `"Prestop collector`" -d `"$repo`" $collect"
    if ($pushReady) { Start-Process wt.exe -ArgumentList "-w new new-tab --title `"Prestop push`" -d `"$repo`" $push" }
} else {
    Start-Process powershell -WorkingDirectory $repo -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle = 'KamGre API'; $serve"
    Start-Process powershell -WorkingDirectory $repo -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle = 'KamGre collector'; $collect"
    if ($pushReady) { Start-Process powershell -WorkingDirectory $repo -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle = 'KamGre push'; $push" }
}

Write-Host ''
Write-Host 'Backend starting: API on http://localhost:8066/api/v1, delay collector every 60 s.'
if ($pushReady) { Write-Host 'Push sender: reminders and live trip changes every 20 s.' } else { Write-Host 'Push sender not started: no VAPID keys in backend/ojpp-django/.env (manage.py vapid_keys).' }
Write-Host 'Run the app here with: yarn dev:live'
