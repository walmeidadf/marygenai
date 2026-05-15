# Decision Log

## 2026-05-10: Use English Throughout The Project

All code, variables, filenames, comments, schemas, documentation, and CLI output should be written in English.

## 2026-05-10: Use Python 3.13+ And `uv`

The project uses Python 3.13+ and `uv` for virtual environment and dependency management.

## 2026-05-10: Start As A POC Lab

The project will start with source-specific POCs before committing to a production crawler, final database, or review interface.

## 2026-05-10: Keep Legacy Files Local

Legacy exports are useful for analysis but should not be committed. They are stored in `temp/legacy/`, and `temp/` is ignored by Git.

## 2026-05-10: Defer Database Choice

PostgreSQL, NoSQL, graph databases, and file-based approaches remain open options. The decision should follow source POC results and ontology modeling needs.

## 2026-05-10: Defer Review Interface Choice

Human review is required, but Label Studio is not yet a fixed decision. Any review workflow must preserve field-level review provenance.

## 2026-05-13: Treat PubMed As Metadata Hub Before Full-Text Crawling

PubMed/NLM is the primary publication identity and metadata source for the next
publication POCs. The project will first expand PubMed metadata testing, reconcile
legacy PubMed/NLM links, and classify full-text availability through PMC, Europe
PMC, Unpaywall, DOI, and publisher links before designing any continuous crawler or
bulk PDF workflow.

## 2026-05-13: Use PubMed As The Primary Study Discovery Source

For the publication-source track, PubMed is the current primary source for detecting
new candidate studies. It should be used to discover and prioritize records, while
PMC, Europe PMC, Unpaywall, DOI, and publisher links should be used later for
access enrichment. PubMed should not be treated as a direct file crawler.

## 2026-05-13: Prefer HTML/XML Before PDF For Full-Text Extraction

The first POC 6 sample showed that direct PMC HTML and structured full-text XML are
better first-choice extraction inputs than PDF. Europe PMC rendered article pages
should not be treated as stable static HTML fetch targets because they can return
JavaScript-dependent placeholder content. When a `PMCID` is available, the
pipeline should prefer PMC HTML and use Europe PMC full-text XML when available.
PDF retrieval should remain a narrow fallback or supplemental artifact until a PDF
parser is justified by extraction gaps.

All full-text extraction outputs remain candidate evidence until human review.

## 2026-05-13: Normalize LLM Evidence Through Strict Review-First Schemas

POC 6b keeps LLM extraction out of the final-truth role. LLMs and heuristics may
generate candidate evidence snippets and candidate values from section-scoped
text, but normalized POC outputs must pass strict Pydantic models and every field
must remain `needs_review=true` with `review_state=needs_review`.

Provider behavior should be recorded as provenance and operational evidence.
Local models may be useful for candidate discovery, while hosted models can be
used for structured comparison. Rate-limit headers, provider errors, and rejected
JSON are part of the POC result, not incidental noise.

## 2026-05-14: Use Review-Ready JSONL Rows Before Choosing A Review Tool

POC 6c uses field-level JSONL rows as the first human-review interchange format.
Each row preserves the source record id, field, candidate value, evidence text,
section, provider, model, confidence, ontology version, extractor version, and
empty review placeholders for reviewer identity, reviewed value, timestamp, and
notes.

This keeps the review contract explicit while deferring the final interface choice
between Label Studio, spreadsheet review, or a custom review UI.

## 2026-05-14: Treat Legacy As A Trusted Curated Reference

The legacy dataset should be used as a high-trust curated reference, not merely as
historical data. Populated legacy values can anchor validation and comparison for
identity, inclusion, study classification, conditions, compounds, and extracted
field values.

Missing legacy values should remain interpretable. For sparse or context-dependent
fields such as dosage and treatment duration, absence may mean `not_applicable` or
`not_reported`, especially for simpler studies or records without intervention,
control group, placebo, or protocol details.

## 2026-05-14: Separate Discovery From Full-Text Extraction

New-publication discovery should first associate PubMed results against the legacy
identity index and classify records as exact matches, possible matches, new
candidates, or manual identity-review items. Full-text access enrichment and
field extraction should run only after records are prioritized for inclusion.

## 2026-05-15: Use Citation Metrics As A Secondary Ranking Signal

The April 2025 PubMed discovery plus iCite validation showed that citation
metrics are useful for review-queue experiments but unsafe as the primary sort.
The window produced 67 deduplicated records, with iCite coverage for all PMIDs,
but citation-only ranking promoted several weak cannabinoid-focus records and
buried some strong recent RCTs and reviews with low citation maturity.

Review prioritization should therefore keep cannabinoid focus, PubMed discovery
score, study design, and full-text review priority as the baseline. Citation
count, Relative Citation Ratio, and related iCite fields should be used as
secondary signals and audit columns, not replacements for cannabinoid relevance,
evidence design, or human review.

## 2026-05-15: Start MVP Design Around Review And Curation

The source POCs are sufficient to start designing an MVP for internal evidence
review and knowledge-base curation while Semantic Scholar access remains pending.
The MVP should use the validated PubMed, legacy reconciliation, access enrichment,
iCite enrichment, and review-row flows already available.

The MVP should not be framed as a medical advice product. Its first product
surface should help human reviewers inspect candidate studies, compare provenance,
resolve inclusion and identity decisions, and preserve field-level review
metadata. Semantic Scholar can be added later as an enrichment source rather than
a blocker for the first MVP design.

## 2026-05-15: Make Cannabinoid Focus The Dominant MVP Ranking Signal

The MVP review queue should be dominated by `cannabinoid_focus`. Direct evidence
in title or indexed PubMed metadata should place a record in the primary review
queue. Abstract-only records should be handled cautiously, and records without a
cannabinoid signal should not be promoted automatically by recency, study design,
or citation metrics.

iCite remains a cost-benefit evaluation and optional secondary enrichment source,
not a priority for the first MVP. Citation metrics must not outrank cannabinoid
relevance.

## 2026-05-15: Use Local-First Hybrid Persistence For MVP Architecture

The first MVP should use a local-first hybrid persistence model: immutable raw
payloads and snapshots in ignored local files, review application state in
SQLite, and JSONL or Parquet exports for audit and interchange. Local `data/`
paths should mirror future S3-compatible object keys so raw payloads, staging
outputs, normalized records, reviewed snapshots, and run manifests can later move
to object storage without changing source adapter contracts.

Docker Compose should be introduced around concrete API, worker, UI, and database
roles, not before the review data model is clear. PostgreSQL, search indexes,
graph storage, and vector indexes remain future options to add when multi-user
concurrency, search, relationship traversal, or semantic retrieval requirements
are demonstrated.

## 2026-05-15: Keep GenAI Retrieval And Ontology Storage Options Open

MaryGenAI should explicitly preserve a GenAI architecture path. The future
platform should support agentic evidence search, hybrid lexical/vector retrieval,
ontology-aware filters, and RAG over reviewed evidence while keeping generated
answers grounded in reviewed fields, evidence text, and provenance.

PostgreSQL should not be assumed as the only next database. PostgreSQL remains a
strong option for relational review workflow state, while MongoDB or another
document database may fit ontology-enriched entities and semi-structured metadata
if those access patterns dominate. Qdrant should be considered a rebuildable
retrieval layer for embeddings and hybrid search, not the source of truth.

The legacy ontology CSVs for cannabinoids, medical conditions, organ systems,
terpenes, and glossary terms should become normalized ontology entities with
provenance and review state, then later accept vetted enrichments from sources
such as Wikipedia, PubMed, MeSH, ICD, DrugBank, or Wikidata.

## 2026-05-15: Start Initial Load With JSONL Snapshots And Run Manifests

The MVP initial load should start with Pydantic contracts, ignored local JSONL
snapshots, and run manifests before populating an operational database. This keeps
legacy studies, source records, publication candidates, ontology entities, and
document-to-ontology links auditable while preserving the option to add SQLite as
the first review persistence layer once queue and review workflows are clearer.

The local `data/` layout should be created by setup code and mirror the future
object-storage layout from the MVP architecture requirements. Legacy CSV exports
remain in `temp/legacy/` and are read in place without renaming Unicode filenames.

## 2026-05-15: Use SQLite As Local Operational State For MVP Review Queues

SQLite is now the first operational persistence layer for the MVP review workflow.
Initial Load JSONL snapshots and run manifests remain the audit and interchange
source, while `data/db/marygenai.sqlite` stores current local application state.

The first schema is intentionally narrow and idempotent. It creates
`run_manifest`, `source_record`, `document`, `document_identity`, `publication`,
`ontology_entity`, `document_ontology_link`, and `review_item`. The initial queue
is `legacy_identity_review`, populated from legacy publication candidates that
lack PMID, PMCID, and DOI and therefore need human identity review before they
can be treated as strongly resolved.

This does not choose the final database architecture. PostgreSQL, document
stores, search indexes, graph stores, and vector indexes remain future options
based on demonstrated review, ontology, collaboration, and GenAI retrieval access
patterns.

## 2026-05-15: Put Review Queue Access Behind Reusable DTOs Before UI

The first review workflow implementation should expose SQLite review state
through a small Pydantic access layer before adding FastAPI or a review UI. Queue
items, publication summaries, publication detail records, ontology links, legacy
reference values, and simple status updates are DTOs that can be reused by CLI,
API endpoints, and later UI screens.

The CLI is the first consumer of that layer. It can list queues, list open
`legacy_identity_review` items, show publication details, and update review item
status with an optional note. These operations mutate only operational SQLite
review state and do not alter Initial Load JSONL snapshots or run manifests.
