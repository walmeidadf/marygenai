# MVP Plan

This document defines the first MaryGenAI MVP after the source POCs. The MVP is
an internal, open-source review and curation platform. It is not a medical advice
tool and should not present treatment recommendations.

## Objective

The MVP should validate the curated legacy dataset and enrich it with candidate
scientific publications discovered after the latest publication date represented
in the legacy data.

The expected outcome is a platform that can:

- load the legacy dataset as the initial trusted reference;
- load the legacy ontology as normalized entities for cannabinoids, medical
  conditions, organ systems, terpenes, glossary terms, and their study links;
- discover candidate publications from the end of the legacy coverage onward;
- enrich candidates with validated source adapters and POC flows;
- prioritize candidates for review with cannabinoid relevance as the dominant
  signal;
- let users inspect, correct, approve, or reject candidate records and fields;
- preserve review provenance for every human or automated decision;
- export reviewed knowledge that can later power scientific evidence search.

The current legacy reconciliation output shows publication years through 2024.
The initial incremental discovery should calculate the latest available legacy
publication date or year, then run PubMed discovery from that point with a small
overlap window to avoid missing records near the boundary.

## Source Strategy

The MVP should use the sources already validated by POCs:

- PubMed for publication identity, metadata, and discovery;
- legacy reconciliation for trusted reference identity and existing curation;
- legacy ontology CSVs for initial condition, cannabinoid, organ system, terpene,
  and glossary entities;
- link resolver outputs for access classification;
- PMC, Europe PMC, and Unpaywall for access and full-text enrichment;
- PMC HTML and Europe PMC XML as preferred full-text inputs when needed;
- iCite as a non-priority citation cost-benefit experiment and optional secondary
  enrichment source.

Semantic Scholar remains useful as a later enrichment source, but the MVP design
should not wait for `SEMANTIC_SCHOLAR_API_KEY`.

## POC Findings Used By The MVP

POC 1 showed that PubMed is strong enough to serve as the publication identity
and metadata hub. DOI, abstract, journal, publication date, authors, publication
types, and publication status had strong coverage in the sampled records.

POC 2 showed that the legacy dataset is suitable for end-to-end validation:
7,347 rows were parsed, and 6,140 rows had directly extractable `PMID`, `PMCID`,
or DOI.

POC 3 and POC 4 showed that access should be classified before retrieval. PMC is
the first full-text path when `PMCID` exists, while Europe PMC and Unpaywall are
useful enrichment sources.

POC 6 showed that full-text and LLM extraction should produce candidate evidence,
not reviewed truth. Dosage, adverse events, arms, protocol details, and similar
fields must preserve field-level provenance and review state.

POC 7 showed that legacy-anchored PubMed discovery can classify publications as
`in_legacy_exact`, `possible_legacy_match`, `needs_manual_identity_review`, or
`new_candidate`.

POC 8 showed that citation metrics can be evaluated as secondary signals, but
their cost-benefit is not a priority for the first MVP. Citation-only ranking can
promote weak cannabinoid-focus records and bury strong recent records with low
citation maturity.

## Prioritization Principle

`cannabinoid_focus` is the core MVP ranking signal and should dominate other
signals. Its weight should be effectively exponential compared with secondary
signals.

Recommended review priority tiers:

1. `direct_title_or_indexed`: primary review queue.
2. `abstract_only`: secondary queue or manual promotion before enrichment.
3. `no_cannabinoid_signal`: exclude from automatic promotion unless manually
   rescued.

Within each cannabinoid-focus tier, secondary ordering may use:

- identity state against the legacy dataset;
- study design and evidence hierarchy;
- human clinical signal;
- priority condition area;
- full-text access availability;
- publication recency;
- citation metrics, only as audit or secondary tie-break signals.

Citation metrics must never override weak cannabinoid focus.

## MVP Workflow

### 1. Initial Load

Status: JSONL Initial Load completed on 2026-05-15. SQLite persistence, the first
local review queue foundation, the first review queue CLI/query layer, and the
first local FastAPI review API were added on 2026-05-15.

Command:

```bash
uv run marygenai initial-load run
uv run marygenai db init
uv run marygenai initial-load persist
```

The initial implementation reads the six legacy Cannadocs CSV exports from
`temp/legacy/cannadocs/`, creates the ignored local `data/` layout, and writes
auditable JSONL snapshots plus a run manifest. The first local run produced:

- 7,780 legacy source records;
- 7,347 canonical publication candidates;
- 433 ontology entities;
- 42,061 document-to-ontology links.

SQLite persistence now loads those snapshots into `data/db/marygenai.sqlite` as
operational review state while keeping JSONL as the audit and interchange source.

Load the legacy studies dataset and normalize publication identity around:

- `PMID`;
- `PMCID`;
- DOI;
- canonical URL;
- normalized title.

Load the legacy ontology CSVs as normalized ontology entities:

- cannabinoids and cannabinoid groups from the cannabinoids table;
- medical conditions, pathologies, and disease families from the medical
  conditions table;
- organ systems from the organ systems table;
- terpenes from the terpenes table;
- glossary terms from the glossary table;
- aliases, English labels, legacy tags, descriptions, and source row provenance;
- legacy study links from ontology rows back to canonical publication candidates.

The initial load should create:

- canonical publication records;
- legacy source records;
- legacy-to-publication associations;
- normalized ontology entities;
- ontology-to-publication links;
- ontology mapping and enrichment queues;
- duplicate and unresolved identity queues;
- field-level legacy reference values for later comparison.

The first SQLite load creates the initial relational subset:

- `run_manifest`;
- `source_record`;
- `document`;
- `document_identity`;
- `publication`;
- `ontology_entity`;
- `document_ontology_link`;
- `review_item`.

The first review queue is `legacy_identity_review`. It opens one item per legacy
publication candidate that lacks PMID, PMCID, and DOI, because those records rely
on canonical URL, normalized title, or weaker legacy identity until reviewed.

The first review access layer exposes Pydantic DTOs and CLI commands for queue
inspection before a UI exists:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review show <review_item_id_or_document_id>
uv run marygenai review update <review_item_id> --status in_review --note "Review started"
```

The CLI reads and updates only operational SQLite review state. It does not
modify Initial Load JSONL snapshots or run manifests.

The first review API exposes the same access layer without adding a UI yet:

```bash
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
```

Minimum endpoints:

- `GET /health`
- `GET /review/queues`
- `GET /review/queues/{queue_type}/items?status=open&limit=20`
- `GET /review/items/{review_item_id}`
- `GET /publications/{document_id}`
- `PATCH /review/items/{review_item_id}/status`

The API reads from `data/db/marygenai.sqlite` by default, returns a clear service
error when the operational database is missing or lacks the review schema, and
does not alter JSONL snapshots.

Populated legacy values should be treated as trusted curated references. Missing
legacy fields should remain interpretable as `not_reported`, `not_applicable`, or
`needs_more_evidence`, depending on the field and record context.

Populated legacy ontology values should also be treated as curated starting
points, but not final external vocabulary mappings. ICD, MeSH, Wikipedia,
Wikidata, PubMed-derived aliases, DrugBank, or other enrichment sources should
produce ontology enrichment candidates with provenance and review state before
they become reviewed ontology knowledge.

### 2. Incremental Discovery

Run PubMed discovery from the latest legacy publication boundary with overlap.
Discovery should classify every record as:

- `in_legacy_exact`;
- `possible_legacy_match`;
- `needs_manual_identity_review`;
- `new_candidate`.

Discovery outputs should remain auditable and should not retrieve full text or
download PDFs.

### 3. Enrichment

Enrichment should run after discovery and prioritization. It should add:

- PubMed metadata;
- access classification;
- PMC full-text path when available;
- Europe PMC metadata or XML/full-text availability;
- Unpaywall open-access status and PDF candidates;
- optional iCite fields as secondary audit metrics;
- optional Semantic Scholar fields when access becomes available.

Enrichment sources should preserve raw payload references, source method,
timestamp, and errors.

### 4. Review Interface

The MVP review interface should support three first screens:

- dashboard: totals, import state, unresolved identity, candidates, and review
  backlog;
- publication queue: sortable/filterable candidate list dominated by
  `cannabinoid_focus`;
- review detail: side-by-side metadata, legacy references, extracted candidates,
  evidence text, source links, and editable review decisions.

Minimum reviewer actions:

- confirm or correct publication identity;
- include or exclude a candidate;
- confirm or correct `cannabinoid_focus`;
- confirm or correct study design;
- approve, edit, reject, or mark field candidates as `not_applicable`,
  `not_reported`, or `needs_more_evidence`;
- add notes or rationale.

### 5. Reviewed Knowledge Export

The reviewed output should include only:

- human-reviewed fields; or
- very conservative automatically reviewed fields from canonical sources.

Conservative automatic review candidates for MVP:

- `PMID`, DOI, and `PMCID` from canonical source payloads;
- title, journal, publication date, authors, and publication types from PubMed;
- `cannabinoid_focus=direct_title_or_indexed` when the signal is present in
  title, MeSH terms, chemicals, or keywords.

Fields that should require human review in the MVP:

- dosage;
- route of administration;
- treatment duration;
- adverse events;
- arms and comparators;
- intervention or protocol details;
- clinical effect claims;
- condition normalization when evidence is ambiguous;
- any treatment recommendation language.

## Minimal Data Model

The MVP should start with a small persistent model:

- `publication`;
- `source_record`;
- `legacy_record`;
- `ontology_entity`;
- `ontology_mapping`;
- `document_ontology_link`;
- `publication_identity`;
- `publication_enrichment`;
- `review_item`;
- `review_decision`;
- `extraction_run`;
- `reviewed_field`.

Each review decision must preserve:

- reviewer identity;
- reviewed field;
- original value;
- reviewed value;
- decision;
- timestamp;
- notes or rationale;
- ontology version;
- extractor version;
- source provenance.

## Suggested Technical Shape

Use Python 3.13+ and `uv`.

Recommended first implementation:

- FastAPI backend;
- SQLite for MVP persistence;
- JSONL exports for audit and interchange;
- Pydantic schemas for import, enrichment, and review contracts;
- a small React UI or another lightweight web UI for review workflows.

Streamlit or spreadsheets can still be useful for quick review experiments, but
the MVP should move toward a purpose-built review queue because field-level
review state and identity decisions are central product behavior.

## Non-Goals

- medical advice or treatment recommendation output;
- citation-first ranking;
- large-scale PDF ingestion;
- broad publisher crawling;
- final database architecture commitment;
- replacing human review for nuanced scientific evidence fields.

## First Implementation Milestone

MVP 0.1 should ship:

- a legacy import command;
- a legacy ontology import command;
- a PubMed discovery command that can start from the legacy boundary;
- an enrichment command for access and PubMed metadata;
- a persistent review queue;
- a publication list ordered by cannabinoid-focus-first ranking;
- a review detail view with editable decisions and provenance;
- a reviewed export format.
