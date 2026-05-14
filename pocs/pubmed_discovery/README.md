# PubMed Discovery POC

Goal: find strong-evidence PubMed studies that are not already anchored in the
curated legacy dataset.

Run the discovery batch:

```bash
uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100
```

Run the latest closed month explicitly:

```bash
uv run python -m pocs.pubmed_discovery.discover_pubmed run \
  --retmax 100 \
  --datetype pdat \
  --mindate 2026/04/01 \
  --maxdate 2026/04/30
```

The script reads the latest legacy reconciliation records from
`data/normalized/legacy_reconciliation/` unless `--legacy-records-path` is provided.
It searches PubMed with strong-evidence cannabinoid queries, deduplicates by PMID,
compares each record with the legacy identity index, and writes normalized outputs
under `data/normalized/pubmed_discovery/`.

Date-window outputs are organized by PubMed date type and month. For publication
date runs, files are written under:

```text
data/normalized/pubmed_discovery/pdat/YYYY-MM/
```

A local `_manifest.json` is also written under
`data/normalized/pubmed_discovery/` so completed windows can be audited without
querying PubMed again. By default, the CLI skips network calls when it finds an
existing run with the same query set, date window, sort, and `retmax`. Use
`--no-skip-existing` to force a rerun.

Outputs:

- `*_records.jsonl`: all deduplicated PubMed records with identity status and score;
- `*_legacy_matches.jsonl`: exact, possible, and manual-review legacy matches;
- `*_new_candidates.jsonl`: records with no legacy identity signal;
- `*_review_export.csv`: review-ready spreadsheet export;
- `*_summary.json`: query, match, and scoring summary.

The review CSV includes:

- `priority_score`: transparent heuristic score;
- `full_text_review_priority`: whether the record should go to automatic full-text
  enrichment or manual full-text/PDF review;
- `cannabinoid_focus`: whether cannabinoid terms appear in the title/indexed
  PubMed fields or only in the abstract.
- `study_design` and `study_design_rank`: evidence hierarchy from case report up
  through meta-analysis.

Study design ranking:

```text
Case Report < Case Series < Case-Control < Cohort Study <
Controlled Clinical Trial < Randomized Controlled Trial <
Systematic Review < Meta-Analysis
```

Identity statuses:

- `in_legacy_exact`: PMID, PMCID, DOI, canonical URL, or normalized title matched the
  legacy index exactly;
- `possible_legacy_match`: high title similarity without identifier agreement;
- `needs_manual_identity_review`: weak title similarity that should be checked;
- `new_candidate`: no sufficient legacy identity signal.

Fuzzy title matching is intentionally conservative. Records published clearly
after the latest legacy publication year are treated as new candidates unless they
match by stable identifier or exact normalized title.

This POC does not retrieve full text, download PDFs, or treat missing legacy fields
as errors.
