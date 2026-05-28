# Legacy English Context POC

Goal: normalize the maintainer-local English legacy export into deduplicated,
LLM-ready context records without replacing the existing Portuguese legacy
bootstrap.

Input:

```bash
temp/legacy-en/studies_html_20240425_1030.csv
```

Run:

```bash
uv run python pocs/legacy_english_context/normalize_legacy_english.py run
```

Outputs:

- `data/normalized/legacy_english_context/*_records.jsonl`: deduplicated English
  context records;
- `data/normalized/legacy_english_context/*_summary.json`: source-row,
  deduplication, identifier, and SQLite match counts.

This POC is local-only and audit-only. It does not commit or expose private
legacy exports, does not update SQLite, and does not create reviewed medical
classifications.
