#!/usr/bin/env bash
# Keeps the delay statistics (reliability, typical travel times) through a deploy. Needs root.
#   keep-stats.sh save    before migrations: copy every TripDelay row to a CSV and note the count
#   keep-stats.sh check   after them: if rows went missing, put them back from that copy and fail
# The rows are months of observed delays that no feed can give back, so a deploy must never lose them.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "keep-stats.sh needs root (sudo)" >&2; exit 1; }

DIR=/var/backups/prestop-stats  # owned by postgres: psql writes and reads the copies
TABLE=prestop_statistics_tripdelay
psql_() { runuser -u postgres -- psql -X -q -t -A -v ON_ERROR_STOP=1 -d prestop "$@"; }
count() { psql_ -c "SELECT count(*) FROM $TABLE" 2>/dev/null || echo 0; }

case "${1:-}" in
  save)
    install -d -m 0700 -o postgres "$DIR"
    if ! psql_ -c "SELECT 1 FROM $TABLE LIMIT 1" >/dev/null 2>&1; then
      echo "No statistics table yet (first deploy)"; rm -f "$DIR/count"; exit 0
    fi
    stamp="$(date +%Y%m%d-%H%M%S)"
    psql_ -c "\\copy (SELECT * FROM $TABLE) TO '$DIR/tripdelay-$stamp.csv' WITH (FORMAT csv, HEADER)"
    ln -sf "tripdelay-$stamp.csv" "$DIR/latest.csv"
    count > "$DIR/count"
    # Keep the copies of the last five deploys.
    ls -1t "$DIR"/tripdelay-*.csv | tail -n +6 | xargs -r rm -f
    echo "Saved $(cat "$DIR/count") statistics rows to $DIR/tripdelay-$stamp.csv"
    ;;
  check)
    [ -f "$DIR/count" ] || { echo "Statistics: nothing saved before this deploy"; exit 0; }
    before="$(cat "$DIR/count")"
    after="$(count)"
    if [ "$after" -ge "$before" ]; then
      echo "Statistics kept: $after rows (were $before)"
      exit 0
    fi
    echo "Statistics LOST rows during the deploy ($before -> $after); putting them back from $DIR/latest.csv" >&2
    # Rows still there win (the collector keeps writing); only the missing ones come back.
    psql_ >/dev/null <<SQL
CREATE TEMP TABLE keep_stats (LIKE $TABLE INCLUDING DEFAULTS);
\\copy keep_stats FROM '$DIR/latest.csv' WITH (FORMAT csv, HEADER)
INSERT INTO $TABLE SELECT * FROM keep_stats ON CONFLICT DO NOTHING;
SELECT setval(pg_get_serial_sequence('$TABLE', 'id'), (SELECT max(id) FROM $TABLE));
SQL
    echo "Statistics restored: $(count) rows. The deploy stops here: find what deleted them before deploying again." >&2
    exit 1
    ;;
  *)
    echo "usage: keep-stats.sh save|check" >&2; exit 2 ;;
esac
