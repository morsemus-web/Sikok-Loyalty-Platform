#!/usr/bin/env bash
# Pulled by CI / SSH session to redeploy the stack from latest main.
set -euo pipefail

cd /opt/sikok

echo "==> Fetching latest from origin/main"
git fetch --quiet origin main
git reset --hard origin/main

echo "==> Building and starting containers"
sudo docker compose up -d --build --remove-orphans

echo "==> Applying migrations (idempotent)"
# Wait for postgres to be ready before applying SQL.
for i in $(seq 1 30); do
  if sudo docker compose exec -T db pg_isready -U sikok -d sikok >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
for sql in backend/migrations/*.sql; do
  echo "    - $(basename "$sql")"
  sudo docker compose exec -T db psql -U sikok -d sikok -v ON_ERROR_STOP=1 -q < "$sql" || {
    echo "Migration $(basename "$sql") failed"; exit 1;
  }
done

echo "==> Pruning dangling images"
sudo docker image prune -f >/dev/null

echo "==> Status"
sudo docker compose ps
