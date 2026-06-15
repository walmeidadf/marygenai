# Project Brief

MaryGenAI aims to build a structured, continuously updated scientific
source-intelligence engine for studies and related documents about cannabinoid
therapy in human and veterinary contexts.

The project still values human-reviewed evidence as the highest trust layer, but
the near-term MVP no longer assumes large-scale human curation is available. The
current product direction is to discover candidate documents, resolve identity,
enrich metadata, acquire source text, prepare classification-ready corpora, and
generate provenance-aware AI classification candidates that can later be reviewed
by humans.

The repository is public. The maintainer's original legacy exports are private
and intentionally absent from the repository. They are used locally as a trusted
bootstrap and validation anchor while the project produces public reviewed
snapshots that future users can treat as the baseline.

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

The current phase is moving from source-specific POCs into a local-first MVP for
source intelligence and candidate classification. The MVP should stay
conservative: it validates and enriches scientific evidence metadata and source
text, but it does not provide medical advice or treatment recommendations.

## Current Objective

Build a local-first MVP that validates the maintainer's private legacy bootstrap,
discovers PubMed candidate publications from January 2024 onward, enriches
candidates with validated source flows, prepares classification-ready corpora,
and produces candidate study classifications with explicit provenance and trust
levels.

The first MVP milestone is not a production crawler. It is a reviewable source
intelligence workflow that can answer:

> Which bootstrap records and new candidate publications have enough identity,
> metadata, and source text to support candidate classification, with what
> provenance, quality gates, and trust state?

The current publication-source plan treats PubMed as the primary publication
identity and metadata hub, then uses PMC, Europe PMC, Unpaywall, DOI, and publisher
links to classify full-text availability before any broad download or crawler
strategy. See [PubMed Source Plan](pubmed_source_plan.md).

For ongoing publication discovery, PubMed is the current primary source of new
study detection. The preferred pipeline is PubMed discovery first, then identifier
normalization, then access enrichment, then targeted full-text/XML extraction only
when needed. Priority should be dominated by `cannabinoid_focus`; study design,
access, recency, and citation metrics are secondary signals.

See [MVP Plan](mvp_plan.md) and
[Classification Dataset Plan](classification_dataset_plan.md) for the current
product direction.

The first MVP implementation milestone is complete for the maintainer workflow:
`uv run marygenai initial-load run` loads private legacy Cannadocs studies and
ontology CSVs into auditable JSONL snapshots and run manifests under ignored
`data/` paths. The public project should not require those private CSVs once
reviewed snapshots are exported.

## Non-Goals For Now

- No user-facing medical tool.
- No clinical recommendation engine.
- No claim that AI-classified records are human-reviewed knowledge.
- No final commitment to PostgreSQL, NoSQL, graph databases, or search infrastructure.
- No citation-first ranking.
- No broad publisher crawler.
