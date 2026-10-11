#!/usr/bin/env bash
# Update Content Corpus on the VM: pull, apply migrations, rebuild, restart.
# Run as the deploy user (in the docker group) from anywhere:
#   ~/strophic/content_corpus/deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
export CORPUS_VERSION
CORPUS_VERSION=$(git rev-parse --short HEAD)

cd deploy
compose() { docker compose --env-file ../.env "$@"; }
compose build
# Migrations are idempotent (sha-tracked) and re-apply the web role's grants.
compose run --rm --no-deps worker-cpu python /app/db/migrate.py
compose up -d --remove-orphans
compose ps
echo "deployed $CORPUS_VERSION"
