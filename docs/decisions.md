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

The maintainer's private legacy dataset should be used as a high-trust curated
reference, not merely as historical data. Populated bootstrap values can anchor
validation and comparison for identity, inclusion, study classification,
conditions, compounds, and extracted field values.

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

## 2026-05-15: Use FastAPI As The First Local Review API Layer

The first web-facing review layer uses FastAPI and Uvicorn as a thin local API
over the existing `marygenai.review` DTOs and SQLite repository. It reads
`data/db/marygenai.sqlite` by default, returns clear service errors when the
operational database is missing or uninitialized, and exposes health, queue,
review item, publication detail, and review status update endpoints.

This keeps the future review UI decoupled from the CLI while preserving the same
local-first persistence boundary: status updates mutate only operational SQLite
review state, optional notes are stored in review item metadata history, and
Initial Load JSONL snapshots remain immutable audit artifacts.

## 2026-05-16: Serve The First Review UI As Static FastAPI Assets

The first visual review surface is a small static HTML/CSS/JavaScript UI mounted
on the existing FastAPI review app at `/ui`, with assets under
`marygenai.review_ui`. It consumes the existing health, queue, detail, and status
update endpoints for the `legacy_identity_review` queue.

This avoids adding a separate Node or React build system before the review
workflow is better understood, while still preserving an explicit `review-ui`
CLI boundary for future containerization or frontend replacement. The UI remains
local-first, internal, and focused on review and curation rather than clinical or
public product behavior.

## 2026-05-16: Separate Identity Decisions From Review Item Status

Legacy identity review now stores structured curation decisions in a dedicated
SQLite `review_decision` table instead of overloading `review_item.status`.
Review item status remains operational workflow state, while identity decisions
are append-only records that preserve reviewer identity, reviewed PMID, PMCID,
DOI, canonical URL, rationale, original identity signals, timestamp, software
version, and decision schema provenance.

This keeps the local UI useful for real curation without making JSONL snapshots
mutable or treating a workflow transition as reviewed knowledge. The same shape
can later generalize to field-level ontology, extraction, inclusion, and evidence
review decisions.

## 2026-05-16: Apply Identity Decisions To Workflow Explicitly

Saving a structured legacy identity decision does not automatically close a
review item. Workflow advancement is a separate explicit operation that applies
the latest saved legacy identity decision to the local SQLite review item.

`confirmed_identity` and `corrected_identity` mark the item `resolved` because
the publication identity has enough reviewer-confirmed information to leave the
identity queue. `not_same_publication` marks the item `dismissed` because the
queued legacy association should not continue as the same publication identity.
`unresolved` remains a saved curation decision but cannot close the workflow
item.

The application writes provenance into `review_item.metadata_json`, including
`status_history` and `last_identity_decision_application`, and leaves Initial
Load JSONL snapshots unchanged.

## 2026-05-18: Open Post-Legacy Enrichment With PubMed Candidate Staging

The first enrichment loop beyond the private bootstrap uses PubMed as the primary
source for publication discovery and metadata. Discovery is anchored to the
latest baseline publication year available in local SQLite and starts with a
small default overlap window so records near the boundary can be classified
instead of silently skipped.

The MVP reuses the validated PubMed POC parser and scoring logic, but writes
MVP-shaped snapshots under ignored `data/` paths and persists only operational
state to SQLite. PubMed results are classified against the legacy index as
`in_legacy_exact`, `possible_legacy_match`,
`needs_manual_identity_review`, or `new_candidate`. Exact legacy matches remain
audit outputs only. Non-exact candidates are stored as `needs_review`
publication records, receive a `publication_candidate_discovery` provenance row,
and enter the `publication_candidate_review` queue.

This deliberately does not mutate Initial Load JSONL snapshots and does not
treat discovered PubMed candidates as reviewed knowledge. `cannabinoid_focus`
continues to dominate review priority; citation metrics and other influence
signals remain secondary enrichments.

## 2026-05-18: Keep Private Legacy Data Out Of The Public Repository

MaryGenAI is now documented as a public project, but the maintainer's original
legacy exports remain private and must not be committed. They are high-trust
bootstrap inputs for the maintainer's local workflow, not public fixtures or
project dependencies.

Public users should eventually start from reviewed snapshots exported by
MaryGenAI. Until those snapshots exist, public contributors can run tests, inspect
source adapters, and work on reproducible PubMed/source workflows, but they
should not expect the private legacy CSVs or local SQLite database to be present.

Documentation should distinguish private maintainer bootstrap state from public
capabilities. The `legacy_identity_review` queue is only the weaker-identity
subset of the private bootstrap, not the full set of useful legacy records.

## 2026-05-18: Backfill PubMed Candidates Month By Month From January 2024

The immediate enrichment workflow is to run PubMed discovery in explicit monthly
publication-date windows from `2024/01/01` through the current date. This gives
the maintainer small, auditable batches to classify for relevance and identity
before access enrichment or field extraction.

The January 2024 start date intentionally overlaps with the private bootstrap,
which includes records through 2024. Overlap is useful because PubMed results can
be classified as `in_legacy_exact`, `possible_legacy_match`,
`needs_manual_identity_review`, or `new_candidate` instead of assuming every
2024+ record is new.

## 2026-05-18: Treat Monthly PubMed Windows As Audit Batches, Not Unique Backlog Counts

The first January-June 2024 PubMed discovery runs showed duplicate PMIDs across
different monthly publication-date windows. The PubMed query translation included
the requested `Date - Publication` bounds, so this appears to be a source
metadata behavior rather than a local command error.

Monthly JSONL candidate and review-item counts should therefore be read as audit
counts for that source window. SQLite remains the operational source of truth for
unique candidates because `publication_candidate_discovery` and
`publication_candidate_review` are keyed by canonical publication document id.

Future PubMed discovery should also persist raw ESearch and EFetch payloads under
`data/raw/pubmed/`, not only source request metadata and normalized snapshots, so
date-window behavior and parser decisions can be audited more directly.

## 2026-05-19: Keep Review Status Vocabulary Explicit For Onboarding

MaryGenAI now documents review status semantics in
`docs/review_status_guide.md` because the MVP has multiple related state layers:
queue workflow status, document review state, PubMed candidate identity status,
and structured identity decisions.

The project should keep these layers separate in UI, API, CLI, and documentation.
For example, `review_item.status='resolved'` closes a local workflow item, while
`publication_candidate_discovery.identity_status='new_candidate'` describes the
candidate's relationship to the baseline. Neither status alone makes a PubMed
candidate reviewed knowledge.

## 2026-05-20: Allow Parallel Access Enrichment Without Reviewed-Knowledge Promotion

Human review of PubMed candidates will be slower than discovery and access
classification. The MVP should therefore allow targeted access/full-text
enrichment to run in parallel with review for prioritized candidates, while
keeping all retrieved files, parsed text, and extracted fields as candidate
evidence.

This does not change the review boundary. `needs_manual_identity_review`
candidates should be identity-reviewed before file retrieval or downstream
extraction, and no PubMed discovery or downloaded artifact becomes reviewed
knowledge automatically. The preferred retrieval order remains HTML/XML first:
PMC HTML/NXML when `PMCID` exists, Europe PMC XML/full-text metadata next,
Unpaywall open-access locations for DOI-backed records, and narrow PDF fallback
only for selected records.

All raw payloads, downloaded files, and parsed text outputs should stay under
ignored `data/` paths and preserve source, method, timestamp, access/license
metadata, file hash, and errors.
