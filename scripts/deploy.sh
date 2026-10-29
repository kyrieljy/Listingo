#!/usr/bin/env bash
# Deploy the current, reviewed checkout. Does not pull Git or change DNS/firewall.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export LISTINGO_ENV_FILE=.env.production
test -f "$LISTINGO_ENV_FILE" || { echo 'Create .env.production from .env.example first' >&2; exit 1; }
compose=(docker compose --env-file "$LISTINGO_ENV_FILE")
"${compose[@]}" config --quiet
mkdir -p data secrets backups
chmod 700 secrets backups
chmod 600 "$LISTINGO_ENV_FILE"
revision=$(git rev-parse HEAD)
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Deploy a clean committed checkout so the release is reproducible.' >&2; exit 1
fi
"${compose[@]}" build backend frontend
"${compose[@]}" up -d redis
"${compose[@]}" stop frontend backend
# Back up a stopped existing installation before schema changes; never delete runtime volumes.
if [[ -f data/.release ]]; then bash scripts/backup.sh; fi
"${compose[@]}" run --rm --no-deps backend python -m alembic -c backend/alembic.ini upgrade head
"${compose[@]}" up -d --force-recreate backend frontend
for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1:5173/api/v1/health >/dev/null; then
    printf '%s\n' "$revision" >data/.release
    "${compose[@]}" exec -T backend python -m alembic -c backend/alembic.ini current >data/.schema-version
    "${compose[@]}" ps
    echo "Release ready: $revision. Validate Nginx/HTTPS before opening traffic."
    exit 0
  fi
  sleep 2
done
echo 'Health check failed. Inspect docker compose logs; do not roll back the DB blindly.' >&2
exit 1
