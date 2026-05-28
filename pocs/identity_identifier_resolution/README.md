# Identity Identifier Resolution POC

Goal: evaluate how often `legacy_identity_review` items can recover DOI, PMID,
or PMCID from existing review-queue metadata, especially ScienceDirect PII values
embedded in canonical URLs.

Run a small batch against the local SQLite review database:

```bash
uv run python pocs/identity_identifier_resolution/resolve_review_identifiers.py run --limit 25
```

Useful options:

```bash
uv run python pocs/identity_identifier_resolution/resolve_review_identifiers.py run \
  --status open \
  --limit 100 \
  --title-fallback
```

Resolution flow:

1. Read `legacy_identity_review` items from local SQLite.
2. Extract ScienceDirect PII from URLs like
   `https://www.sciencedirect.com/science/article/pii/S0164121223001234`
   and
   `https://www.sciencedirect.com/science/article/abs/pii/S0164121223001234`.
3. Query Crossref and OpenAlex with the PII and title context.
4. Optionally query Elsevier by PII when `MARYGENAI_ELSEVIER_API_KEY` is set.
5. Use the recovered DOI to query NCBI E-utilities for PMID and PMCID.

Optional environment variables:

- `MARYGENAI_NCBI_EMAIL`: sent to NCBI E-utilities for polite API use;
- `MARYGENAI_NCBI_API_KEY`: optional NCBI API key;
- `MARYGENAI_ELSEVIER_API_KEY`: optional Elsevier API key for direct PII lookup.

Outputs:

- `data/normalized/identity_identifier_resolution/*_records.jsonl`: one audit
  record per reviewed item;
- `data/normalized/identity_identifier_resolution/*_summary.json`: coverage
  counts, candidate source counts, errors, and examples.

This POC does not change review state or write structured identity decisions. It
only produces evidence for a human reviewer or a later review-decision workflow.

## 2026-05-25 ScienceDirect PII Coverage Note

ScienceDirect is a large slice of the current `legacy_identity_review` queue:
the local maintainer database has hundreds of ScienceDirect-linked open or
in-review items. The first PII extractor only matched
`/science/article/pii/{PII}` URLs, but many legacy links use
`/science/article/abs/pii/{PII}` instead. The POC now extracts both forms and
the `--require-sciencedirect-pii` selector includes both forms before writing
audit outputs.

The output remains audit-only. It does not update `review_state`,
`document_identity`, queue workflow status, or review decisions automatically.
The recommended next enrichment step is to use recovered DOI values to query
PubMed E-utilities for PMID and PMCID, preserving the DOI, PMID/PMCID, query,
source, timestamp, and any lookup errors as review evidence.
