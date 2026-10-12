#!/usr/bin/env bash
# Nightly database dump (prestop-backup.timer). Runs as the prestop user.
set -euo pipefail
dir=/var/backups/prestop
keep="${BACKUP_KEEP_DAYS:-7}"
file="$dir/prestop-$(date +%F).dump"
pg_dump -h /var/run/postgresql -d prestop -Fc -Z 6 -f "$file.part"
mv "$file.part" "$file"
find "$dir" -name 'prestop-*.dump' -mtime +"$keep" -delete
echo "backup: $file ($(du -h "$file" | cut -f1))"
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  rclone --config /etc/prestop/rclone.conf copy "$file" "$BACKUP_RCLONE_REMOTE"
  rclone --config /etc/prestop/rclone.conf delete --min-age "${keep}d" "$BACKUP_RCLONE_REMOTE"
  echo "copied to $BACKUP_RCLONE_REMOTE"
fi
