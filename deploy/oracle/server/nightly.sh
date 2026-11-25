#!/usr/bin/env bash
# prestop-nightly.service (02:05-02:55): the heavy reads while no train runs, each step on its own so one failing
# leaves the others. Live polls are untouched (small and continuous, in the API itself).
#   1. today's SŽ closures added to the ghost-trip rule's closure days (prestop_api/gps_habit.py, B1)
#   2. SŽ train and station rollups of yesterday, then earlier days without rows until 02:50 (prestop_statistics/rollup.py)
#   3. Sundays: each train's usual track per station from 90 days of the track scraper (prestop_api/tracks.py)
set -uo pipefail
cd /opt/prestop/app
manage() { /opt/prestop/venv/bin/python manage.py "$@"; }
failed=0
manage gps_habit --learn || failed=1  # first: a minute at most, the rollups stop at 02:50 on their own
manage rollup_stats --backfill 90 --until 02:50 || failed=1
if [ "$(date +%u)" = 7 ]; then manage sz_tracks --days 90 || failed=1; fi
exit $failed
