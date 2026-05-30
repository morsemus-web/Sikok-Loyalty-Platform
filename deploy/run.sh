#!/usr/bin/env bash
# Pulled by CI / SSH session to redeploy the stack from latest main.
set -euo pipefail

cd /opt/sikok

echo "==> Fetching latest from origin/main"
git fetch --quiet origin main
git reset --hard origin/main

echo "==> Building and starting containers"
sudo docker compose up -d --build --remove-orphans

echo "==> Pruning dangling images"
sudo docker image prune -f >/dev/null

echo "==> Status"
sudo docker compose ps
