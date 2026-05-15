# Project Brief

MaryGenAI aims to build a structured, continuously updated evidence base for scientific studies and related documents about cannabinoid therapy in human and veterinary contexts.

The project is inspired by CannaKeys-style metadata but is broader in scope. It will explore:

- human and veterinary evidence;
- clinical trial records;
- publication metadata;
- cannabinoid and terpene ontology;
- medical condition mappings;
- routes of administration;
- dosing and protocol extraction;
- drug interaction evidence;
- human review workflows.

The current phase is moving from source-specific POCs into an MVP for internal
review and curation. The MVP should stay conservative: it validates and enriches
scientific evidence metadata, but it does not provide medical advice or treatment
recommendations.

## Current Objective

Build an internal MVP that validates the legacy dataset, discovers candidate
publications from the end of legacy coverage onward, enriches candidates with
validated source flows, and lets reviewers approve, correct, or reject records and
field-level evidence.

The first MVP milestone is not a production crawler. It is a reviewable evidence
curation workflow that can answer:

> Which legacy records and new candidate publications are reliable enough to enter
> a reviewed cannabinoid evidence knowledge base, with what provenance and review
> state?

The current publication-source plan treats PubMed as the primary publication
identity and metadata hub, then uses PMC, Europe PMC, Unpaywall, DOI, and publisher
links to classify full-text availability before any broad download or crawler
strategy. See [PubMed Source Plan](pubmed_source_plan.md).

For ongoing publication discovery, PubMed is the current primary source of new
study detection. The preferred pipeline is PubMed discovery first, then identifier
normalization, then access enrichment, then targeted full-text/XML extraction only
when needed. Priority should be dominated by `cannabinoid_focus`; study design,
access, recency, and citation metrics are secondary signals.

See [MVP Plan](mvp_plan.md) for the current product direction.

The first MVP implementation milestone is complete: `uv run marygenai
initial-load run` loads the legacy Cannadocs studies and ontology CSVs into
auditable JSONL snapshots and run manifests under ignored `data/` paths. This is
the foundation for identity review, ontology review, incremental discovery, and
later SQLite-backed review queues.

## Non-Goals For Now

- No user-facing medical tool.
- No clinical recommendation engine.
- No large-scale PDF ingestion pipeline.
- No final commitment to PostgreSQL, NoSQL, graph databases, or search infrastructure.
- No citation-first ranking.
- No broad publisher crawler.
