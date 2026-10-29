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
# Credentials are passed through PGDATABASE, never command-line arguments.
"${compose[@]}" run --rm --no-deps -T db-backup >"backups/db-$stamp.dump"
tar -czf "backups/files-$stamp.tgz" data secrets .env.production
echo "Created backups/db-$stamp.dump and backups/files-$stamp.tgz"
echo 'Copy both files to encrypted offsite storage; verify by restoring into an isolated database.'
