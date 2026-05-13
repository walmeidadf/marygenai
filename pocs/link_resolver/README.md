# Link Resolver POC

Goal: classify publication access paths before downloading or parsing full text.

Run against the latest legacy reconciliation output:

```bash
uv run python pocs/link_resolver/resolve_links.py run
```

Or pass a specific JSONL input:

```bash
uv run python pocs/link_resolver/resolve_links.py run \
  --input-path data/normalized/legacy_reconciliation/<run>_legacy_reconciliation_records.jsonl
```

Outputs:

- `data/normalized/link_resolver/*_records.jsonl`: one link resolution record per
  input record;
- `data/normalized/link_resolver/*_summary.json`: access class counts and next
  resolver recommendations.

This first resolver pass is local-only. It classifies known identifiers and
candidate URLs, but does not fetch PubMed, PMC, Europe PMC, Unpaywall, DOI, or
publisher pages.

First completed run:

- run id: `20260513T162415Z`;
- records classified: 7,347;
- `pmc_full_text_available`: 1,676;
- `pubmed_metadata_only`: 3,805;
- `doi_landing_page_available`: 659;
- `publisher_landing_page_only`: 1,207.
