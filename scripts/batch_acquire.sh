#!/usr/bin/env bash
set -euo pipefail

cd /Users/wesley/Projects/MaryGenAI

BATCHES=10
ACQUIRE_LIMIT=100

for i in $(seq 1 "$BATCHES"); do
  echo "=== Batch $i / $BATCHES: acquire-augmented-links ==="
  uv run python -m pocs.official_source_fetch_router.fetch_router acquire-augmented-links \
    --limit "$ACQUIRE_LIMIT" \
    --delay-seconds 0.5 \
    --timeout-seconds 45 \
    --max-bytes 20000000

  echo "=== Batch $i complete ==="
  date
done

echo "All batches complete."