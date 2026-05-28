# Legacy Identity Validation POC

Goal: validate and link normalized English legacy context records against the
local SQLite baseline without calling hosted LLMs or mutating review state.

Input:

```bash
data/normalized/legacy_english_context/20260525T235818Z_legacy_english_context_records.jsonl
data/db/marygenai.sqlite
```

Run:

```bash
uv run python pocs/legacy_identity_validation/validate_legacy_identity.py run
```

Outputs:

- `data/normalized/legacy_identity_validation/*_records.jsonl`: one audited
  validation record per context;
- `data/normalized/legacy_identity_validation/*_<bucket>.jsonl`: bucket-specific
  subsets for downstream batch selection;
- `data/normalized/legacy_identity_validation/*_summary.json`: bucket counts,
  thresholds, input paths, and match-method counts.

Buckets:

- `exact_identifier_match`
- `strong_title_embedding_match`
- `ambiguous_identity`
- `no_local_match`

This POC uses strong identifiers first: PMID, PMCID, DOI, and canonical URL.
Title/year plus local embeddings are used only when no strong identifier is
available. It does not call Groq and does not alter `review_state`,
`review_item`, or structured review decisions.

To build the identity-confirmed English cohort for later LLM reclassification:

```bash
uv run python pocs/legacy_identity_validation/validate_legacy_identity.py export-confirmed
```

To retrieve PMC full-text artifacts for the identity-confirmed records with
PMCID:

```bash
uv run python pocs/legacy_identity_validation/enrich_confirmed_legacy_access.py run --target pmcid --fetch-pmc-html
```
