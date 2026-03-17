#!/usr/bin/env bash
set -e

echo "=== Initializing database ==="
python -c "from db import init_db; init_db()"

echo "=== Syncing latest trades ==="
python scripts/sync.py || echo "No previous sync — run backfill manually via shell"

echo "=== Backfilling outcomes ==="
python scripts/backfill_outcomes.py || true

echo "=== Starting gunicorn ==="
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --preload
