#!/usr/bin/env bash
set -euo pipefail

cd /Users/wesley/Projects/MaryGenAI

BATCHES=10
OPENALEX_LIMIT=200

for i in $(seq 1 "$BATCHES"); do
  echo "=== Batch $i / $BATCHES: augment-openalex ==="
  uv run python -m pocs.official_source_fetch_router.fetch_router augment-openalex \
    --limit "$OPENALEX_LIMIT" \
    --delay-seconds 0.2 \
    --timeout-seconds 30

  echo "=== Batch $i complete ==="
  date
done

echo "All batches complete."