#!/usr/bin/env bash
set -e

echo "=== Installing dependencies ==="
pip install -r requirements.txt

echo "=== Build complete (DB init happens at runtime when disk is mounted) ==="
