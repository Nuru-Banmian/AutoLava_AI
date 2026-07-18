#!/usr/bin/env sh
set -eu

APP_DIR=${AUTOLAVA_APP_DIR:-/opt/autolava}
BACKUP_DIR="$APP_DIR/backups"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"
umask 077
cd "$APP_DIR"

docker compose -f compose.yaml -f compose.temporary.yaml exec -T autolava-db \
  sh -c 'exec mysqldump --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -c > "$BACKUP_DIR/autolava-$TIMESTAMP.sql.gz"

find "$BACKUP_DIR" -type f -name 'autolava-*.sql.gz' -mtime +6 -delete
