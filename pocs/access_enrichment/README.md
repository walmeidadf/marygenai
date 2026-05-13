# Access Enrichment POC

Goal: enrich link resolver outputs with network-backed metadata from Europe PMC and
Unpaywall without downloading PDFs.

Run a small sample:

```bash
uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25
```

Inputs:

- latest `data/normalized/link_resolver/*_link_resolver_records.jsonl` by default.

Outputs:

- `data/raw/access_enrichment/*`: raw Europe PMC and Unpaywall JSON responses;
- `data/normalized/access_enrichment/*_records.jsonl`: one enrichment record per
  sampled source record;
- `data/normalized/access_enrichment/*_summary.json`: aggregate coverage metrics.

Environment:

- `UNPAYWALL_EMAIL` is required for Unpaywall DOI enrichment.

This POC records PDF URLs if APIs expose them, but it does not download PDFs.

Current completed run:

- run id: `20260513T170323Z`;
- sampled records: 20;
- Europe PMC queried: 20;
- Europe PMC found: 15;
- Unpaywall queried: 20;
- Unpaywall found: 16;
- Unpaywall open access: 11;
- Unpaywall PDF URLs: 7;
- open-access PDF candidates: 10;
- open-access landing candidates: 1;
- records with errors: 0.
