# POCs

Each subfolder should contain small, disposable experiments for a single data source.

Practical rule: a POC should produce evidence for architectural decisions, not become a production adapter too early.

Before expanding LLM classification, read
`docs/source_availability_assessment.md`. The current gate is whether source
enrichment can produce at least 5,000 classification-ready texts; metadata-only
coverage does not satisfy that gate.

Current publication-source POCs:

- PubMed expanded metadata: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`
- Legacy reconciliation: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`
- Link resolver: `uv run python pocs/link_resolver/resolve_links.py run`
- Identity identifier resolution: `uv run python pocs/identity_identifier_resolution/resolve_review_identifiers.py run --require-sciencedirect-pii --limit 25`
- Access enrichment: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25`
- Source availability ceiling: `uv run python -m pocs.source_availability_ceiling.assess_ceiling summarize`
- Official source fetch router: `uv run python -m pocs.official_source_fetch_router.fetch_router route`
- PMC OAI source acquisition: `uv run python -m pocs.official_source_fetch_router.fetch_router acquire-pmc-oai --limit 100`
- Unpaywall PDF source acquisition: `uv run python -m pocs.official_source_fetch_router.fetch_router acquire-unpaywall-pdf --limit 50`
- Augmented link acquisition: `uv run python -m pocs.official_source_fetch_router.fetch_router acquire-augmented-links --limit 100`
- LLM study reclassification and evidence synthesis: `uv run python pocs/llm_study_reclassification/reclassify_studies.py prepare-summary-packets --task condition_organ_system_extraction --limit 5`
