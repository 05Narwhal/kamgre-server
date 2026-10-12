#!/usr/bin/env bash
# prestop-restore <file.dump>: replace the database with a backup. Needs root.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
file="${1:?usage: prestop-restore /var/backups/prestop/prestop-YYYY-MM-DD.dump}"
[ -r "$file" ] || { echo "cannot read $file" >&2; exit 1; }
read -r -p "This REPLACES the live database with $file. Type 'restore' to continue: " answer
[ "$answer" = restore ] || { echo "cancelled"; exit 1; }
systemctl stop prestop-web prestop-collector prestop-ingest
runuser -u postgres -- dropdb --if-exists prestop
runuser -u postgres -- createdb -O prestop prestop
runuser -u postgres -- psql -q -d prestop -c 'CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS hstore; CREATE EXTENSION IF NOT EXISTS pg_prewarm;'
runuser -u postgres -- pg_restore -d prestop --no-owner --role=prestop --exit-on-error < "$file"
systemctl start prestop-web prestop-collector prestop-ingest
echo "restored $file"
