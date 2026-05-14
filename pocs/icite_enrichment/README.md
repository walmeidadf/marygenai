# NIH iCite Citation Enrichment POC

Goal: enrich PubMed discovery candidates with NIH iCite citation and influence
metrics while keeping citation separate from evidence quality.

Run against the April 2026 PubMed discovery output:

```bash
uv run python -m pocs.icite_enrichment.enrich_icite run \
  --input-path data/normalized/pubmed_discovery/pdat/2026-04/20260514T220709Z_pubmed_discovery_records.jsonl
```

The POC queries NIH iCite in PMID batches of up to 200 and writes outputs under:

```text
data/normalized/icite_enrichment/
```

Outputs:

- `*_records.jsonl`: PubMed discovery records plus `icite_*` fields and
  `citation_priority_score`;
- `*_review_export.csv`: review queue export sorted by citation priority first,
  with the original PubMed `priority_score` kept as a separate column;
- `*_summary.json`: run metadata, coverage counts, top citation-priority records,
  and guardrail notes.

A local `_manifest.json` records input path and file hash. By default, the CLI
skips iCite API calls if the exact input was already enriched. Use
`--no-skip-existing` to force a rerun.

Important guardrails:

- citation metrics are prioritization signals, not evidence quality;
- missing iCite metrics are not errors;
- `priority_score`, `study_design_rank`, `cannabinoid_focus`, and
  `full_text_review_priority` from POC 7 are preserved;
- citation metrics must not overwrite study design;
- recent studies may have low citation counts because they have had little time to
  accrue citations;
- this POC does not retrieve full text or download PDFs.

The iCite fields evaluated here include total citations / cited-by PMID count,
Relative Citation Ratio, NIH percentile, clinical citation signals, human/animal/
molecular-cellular orientation, and Approximate Potential to Translate.

## Next Analysis

The first April 2026 input is intentionally recent, so citation counts and RCR
coverage are expected to be sparse. The next evaluation should pull older PubMed
discovery windows and compare whether iCite metrics improve the review queue once
papers have had time to accrue citations.

Compare each older-window run by:

- preserving the PubMed discovery rank as the baseline;
- sorting by `citation_priority_score` separately;
- checking whether high-citation records are actually better review candidates;
- flagging cases where citation influence conflicts with study design,
  cannabinoid focus, or human-review priorities;
- measuring how often recent but important records would be under-prioritized by
  citation-only sorting.
