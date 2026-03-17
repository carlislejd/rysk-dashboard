#!/usr/bin/env bash
set -e

echo "=== Installing dependencies ==="
pip install -r requirements.txt

echo "=== Initializing database ==="
python -c "from db import init_db; init_db()"

echo "=== Syncing latest trades ==="
python scripts/sync.py

echo "=== Backfilling outcomes for newly expired trades ==="
python scripts/backfill_outcomes.py

echo "=== Build complete ==="
