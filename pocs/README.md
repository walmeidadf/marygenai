# POCs

Each subfolder should contain small, disposable experiments for a single data source.

Practical rule: a POC should produce evidence for architectural decisions, not become a production adapter too early.

Current publication-source POCs:

- PubMed expanded metadata: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`
- Legacy reconciliation: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`
- Link resolver: `uv run python pocs/link_resolver/resolve_links.py run`
- Access enrichment: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25`
