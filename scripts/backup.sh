#!/usr/bin/env bash
# Requires Docker, plus an operator-managed offsite destination.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export LISTINGO_ENV_FILE=.env.production
compose=(docker compose --env-file "$LISTINGO_ENV_FILE")
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p backups
chmod 700 backups
umask 077
# libpq treats PGDATABASE as a database name, so pass the parsed URL through a private service file.
"${compose[@]}" run --rm --no-deps -T backend python -c '
import os
from psycopg2.extensions import parse_dsn

url = os.environ["LISTINGO_DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://", 1)
parameters = parse_dsn(url)
if any("\n" in value or "\r" in value for value in parameters.values()):
    raise ValueError("Database connection values cannot contain newlines")
print("[listingo_backup]")
for key, value in parameters.items():
    print(f"{key}={value}")
' | "${compose[@]}" run --rm --no-deps -T --entrypoint sh db-backup -ec '
    umask 077
    export PGSERVICEFILE=/tmp/listingo-pg-service.conf PGSERVICE=listingo_backup
    unset PGDATABASE
    cat >"$PGSERVICEFILE"
    exec pg_dump --format=custom --no-password
' >"backups/db-$stamp.dump"
"${compose[@]}" run --rm --no-deps -T --entrypoint pg_restore db-backup --list <"backups/db-$stamp.dump" >/dev/null
tar -czf "backups/files-$stamp.tgz" data secrets .env.production
echo "Created backups/db-$stamp.dump and backups/files-$stamp.tgz"
echo 'Copy both files to encrypted offsite storage; verify by restoring into an isolated database.'
