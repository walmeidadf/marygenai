# MVP Architecture Requirements

This document defines architecture requirements for the first MaryGenAI MVP and
the migration path from a local internal review tool to an open-source,
cloud-deployable collaboration platform for healthcare professionals and
research reviewers.

The MVP remains a curation and evidence metadata platform. It must not present
medical advice or treatment recommendations.

The public repository does not include the maintainer's private legacy exports.
The architecture must therefore support two entry points:

- maintainer bootstrap: private local files in ignored `temp/legacy/` seed the
  initial trusted reference;
- public baseline: reviewed snapshots exported by the project become the future
  starting point for contributors who do not have the private legacy files.

## Architecture Goals

- Keep Python as the primary implementation language for ingestion,
  normalization, enrichment, scoring, export, and backend services.
- Support local-first operation so heavy legacy loading and source experiments can
  run on a maintainer machine before any cloud deployment.
- Use container-friendly service boundaries so the same system can later run in
  Docker Compose, a single VM, or managed cloud infrastructure.
- Preserve raw source payloads separately from normalized records and reviewed
  knowledge.
- Make source adapters replaceable and additive, including PubMed, PMC, Europe
  PMC, Unpaywall, ClinicalTrials.gov, iCite, Semantic Scholar, and drug
  interaction sources.
- Preserve field-level provenance and human review state as first-class data.
- Make GenAI a native architectural goal: the platform should eventually support
  agentic evidence search, retrieval-augmented generation, hybrid lexical/vector
  retrieval, ontology-aware filters, and grounded answers over reviewed evidence.
- Keep the storage model portable enough to evolve from local files plus SQLite
  to object storage, an operational database, and optional retrieval indexes
  without rewriting source adapters.
- Keep exports auditable through JSONL or Parquet snapshots even after the review
  application has a database or search infrastructure.

## Recommended MVP Service Shape

MVP 0.1 should start as a small Python application with explicit batch commands
and a review web app:

- `ingest`: reads private bootstrap data or future public reviewed snapshots into
  canonical staging models;
- `discover`: runs date-windowed PubMed discovery anchored to the available
  baseline;
- `enrich`: adds source-specific metadata, access paths, citation metrics, full
  text availability, and later Semantic Scholar or drug interaction data;
- `extract`: creates field candidates from abstracts, HTML, XML, or selected PDF
  samples;
- `review-api`: serves review queues, record details, review decisions, and
  exports;
- `review-ui`: provides the human review workflow;
- `export`: writes reviewed knowledge snapshots for audit and downstream use.

For the first implementation, these can live in one repository and one Python
package. They should still be organized as separate modules and CLI commands so
they can later become scheduled jobs or independent containers.

The first `review-ui` implementation is intentionally a static local UI served by
the FastAPI review app at `/ui`. This keeps the review surface available without
introducing a separate frontend build system before review workflow needs are
clear. A separate UI container or richer frontend can be introduced later when
the application boundary is justified.

## Container Requirements

The MVP should be designed to run locally with Docker Compose, but Docker should
not be required for day-to-day POC commands.

Minimum container roles:

- `api`: FastAPI review backend;
- `worker`: batch ingestion, discovery, enrichment, extraction, and export jobs;
- `ui`: review frontend, if the frontend is not served by the API container;
- `db`: SQLite volume for MVP 0.1, with a clear migration path to PostgreSQL,
  MongoDB, or another operational store if review and ontology access patterns
  justify it;
- `vector-store`: optional Qdrant service for later GenAI retrieval experiments,
  hybrid search evaluation, embeddings, and agentic evidence lookup;
- `object-store`: optional local MinIO service for S3-compatible development
  once raw payload volume or cloud simulation justifies it.

The initial local developer flow may still use:

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai db init
uv run marygenai initial-load run
uv run marygenai initial-load persist
uv run marygenai pubmed-discovery run --datetype pdat --mindate 2024/01/01 --maxdate 2024/01/31 --retmax 100
uv run pytest
```

`initial-load` currently requires the maintainer's private legacy CSVs. Public
users should be able to start from reviewed snapshot imports once those exports
are produced.

Containerization should be added when the review API or scheduler becomes part of
the implementation, not before the data model is clear.

## Persistence Strategy

The MVP should use a hybrid persistence strategy:

1. Object-like file layout for immutable payloads, staging outputs, and exports.
2. SQLite for the internal review queue and field-level review decisions.
3. JSONL or Parquet snapshots for audit, interchange, reproducibility, and later
   backfills.

SQLite is the preferred MVP database because it is portable, transparent, and
enough for one maintainer or a small local review group. The current local
database lives at `data/db/marygenai.sqlite` and is initialized with
`uv run marygenai db init`. The schema should avoid SQLite-specific assumptions
so the application can later migrate to a different operational store.

The next operational database should not be predetermined. PostgreSQL is a strong
candidate for review workflow state, relational constraints, and mature
open-source deployment. MongoDB or another document database may become a better
candidate if ontology-enriched entities, source payload derivatives, and
semi-structured clinical metadata dominate the access patterns. Qdrant should be
considered a retrieval index for GenAI and hybrid search rather than the source
of truth.

S3-compatible object storage should be treated as the future home for immutable
payloads and exports. Local `data/` should mirror the future object key layout.

## GenAI And Retrieval Requirements

The project name should be reflected in the architecture. GenAI should not
produce unreviewed medical truth, but it should be a first-class way to explore,
triage, and retrieve reviewed evidence.

Future GenAI capabilities should include:

- agentic search over reviewed publications, ontology entities, conditions,
  compounds, organ systems, drug interaction claims, and evidence snippets;
- hybrid retrieval that combines structured filters, keyword search, ontology
  relationships, and vector similarity;
- citation-grounded answers that point back to reviewed fields, evidence text,
  source payloads, and review decisions;
- reviewer assistance for deduplication, evidence triage, field candidate
  comparison, and ontology mapping;
- strict separation between generated explanations and reviewed knowledge.

The retrieval architecture should keep three roles distinct:

- object storage stores immutable source and snapshot artifacts;
- an operational database stores current review and ontology state;
- a retrieval layer, such as Qdrant or another vector/hybrid search system,
  stores embeddings and search indexes that can be rebuilt from reviewed
  snapshots and provenance.

## Local Data Directory Layout

`data/` remains ignored by Git and should mirror future object storage:

```text
data/
  raw/
    legacy/
      studies/
      ontology/
    pubmed/
      esearch/
      efetch/
    pmc/
      html/
      xml/
    europe_pmc/
      metadata/
      full_text_xml/
    unpaywall/
      doi/
    clinical_trials/
      studies/
    icite/
      pmid_batches/
    semantic_scholar/
      papers/
    drug_interactions/
      source_payloads/
    pdf/
      samples/
  staging/
    source_records/
    identity_resolution/
    access_resolution/
    extraction_candidates/
  normalized/
    ontology/
      cannabinoids/
      medical_conditions/
      pathologies/
      organ_systems/
      terpenes/
      glossary_terms/
      ontology_mappings/
    publications/
    clinical_trial_records/
    drug_interaction_documents/
    publication_enrichments/
    review_items/
  reviewed/
    snapshots/
    reviewed_fields/
    knowledge_exports/
  manifests/
    runs/
    source_windows/
    file_hashes/
  db/
    marygenai.sqlite
```

The layout is created by:

```bash
uv run marygenai initial-load setup-data
```

The PubMed candidate discovery slice writes to the existing local object-key
style layout:

- `data/staging/source_records/pubmed/` for E-utilities request provenance;
- `data/normalized/publication_enrichments/pubmed/` for candidate metadata and
  legacy association state;
- `data/normalized/review_items/` for candidate queue snapshots;
- `data/manifests/source_windows/` and `data/manifests/runs/` for discovery
  summaries and run manifests.

SQLite stores current review state for non-exact candidates in
`document`, `document_identity`, `publication`,
`publication_candidate_discovery`, and `review_item`. The file snapshots remain
the audit layer.

The active MVP `data/` workspace should stay focused on current Initial Load
outputs. Older POC artifacts may be archived under `temp/scratch/` or regenerated
from POC commands when needed, but they should not be mixed into the active MVP
snapshot set.

`temp/` should remain for local scratch files, private legacy exports, manual
experiments, and disposable artifacts:

```text
temp/
  legacy/
  downloads/
  scratch/
  review_exports/
```

Raw payload paths should include source, run id, retrieval date, and stable
identifier when available. Example object-key style:

```text
data/raw/pubmed/efetch/year=2026/month=05/run=20260515T120000Z/pmid=12345678.xml
```

## Future S3-Compatible Layout

The local layout should map directly to object storage:

```text
s3://marygenai-dev/raw/pubmed/...
s3://marygenai-dev/staging/...
s3://marygenai-dev/normalized/...
s3://marygenai-dev/reviewed/...
s3://marygenai-dev/manifests/...
```

Object storage should hold immutable raw payloads, normalized snapshots,
extraction artifacts, export files, and run manifests. The relational database
should hold the current application state, queue state, review decisions, and
indexes pointing back to object keys.

When the operational database is not relational, the same separation still
applies: object storage remains the artifact source of record, while the database
stores current application state and pointers to immutable artifacts.

## Core Data Domains

The MVP data model should keep these domains separate:

- source records: payloads from a specific source request or source document;
- canonical documents: publications, clinical trial records, drug interaction
  documents, PDFs, and full-text documents;
- ontology entities: cannabinoids, terpenes, medical conditions, pathologies,
  organ systems, glossary terms, routes, receptors, ligands, and dosing concepts;
- ontology mappings: links among legacy ontology rows, normalized ontology
  entities, external vocabularies, and evidence documents;
- identity resolution: links between source records and canonical documents;
- enrichments: source-specific metadata added after discovery;
- extraction candidates: machine or heuristic candidate fields requiring review;
- review items: queue entries shown to reviewers;
- review decisions: field-level human decisions with reviewer metadata;
- reviewed knowledge: reviewed fields and exportable evidence metadata.

Do not collapse all source material into an `article` table. Publications,
clinical trial records, interaction documents, and PDFs should be distinct
document types that can link to each other.

Do not treat the legacy ontology CSVs as incidental lookup tables. The legacy
files for cannabinoids, medical conditions, organ systems, terpenes, and glossary
terms should become normalized ontology entities with provenance back to the
legacy rows and with room for later enrichment from Wikipedia, PubMed, ICD, MeSH,
DrugBank, Wikidata, or other vetted sources.

## Minimal Relational Schema

SQLite MVP tables should include:

- `run_manifest`: job type, source, date window, input hashes, output paths,
  counts, errors, and software version;
- `source_record`: source, source record id, raw object path, retrieval method,
  retrieved timestamp, payload hash, run id, and error status;
- `document`: canonical document id, document type, primary title, publication
  date, canonical identifiers, and lifecycle state;
- `document_identity`: identifier type, identifier value, source, confidence, and
  association state;
- `publication`: publication-specific metadata such as journal, authors,
  publication types, language, and abstract;
- `clinical_trial_record`: trial-specific metadata such as registry id, phase,
  status, enrollment, arms, conditions, interventions, and linked publications;
- `drug_interaction_document`: interaction source, substances, severity,
  mechanism, clinical note candidate, and source provenance;
- `ontology_entity`: entity type, canonical label, aliases, descriptions,
  language, lifecycle state, and provenance;
- `ontology_mapping`: source entity, target entity or external identifier,
  mapping type, confidence, source, evidence, and review state;
- `ontology_entity_enrichment`: enrichment source, raw object path, normalized
  fields, evidence, timestamp, and review state;
- `document_ontology_link`: document id, ontology entity id, link type, source,
  confidence, evidence text, and review state;
- `document_enrichment`: source-specific enrichment payload references and
  normalized fields;
- `extraction_run`: extractor name, version, model, prompt version, source text
  scope, configuration, timestamp, and status;
- `extraction_candidate`: document id, field name, candidate value, evidence
  text, confidence, provenance, extractor version, and review state;
- `review_item`: queue type, document id, priority tier, priority score, assignee,
  status, and due or batch metadata;
- `review_decision`: reviewer identity, field name, original value, reviewed
  value, decision, timestamp, notes, ontology version, extractor version, and
  provenance reference;
- `reviewed_field`: current reviewed value per document field, derived from
  accepted review decisions;

Indexes should prioritize identifier lookup, queue filtering, review status,
ontology entity lookup, document-to-ontology traversal, and date-windowed
pipeline runs.

The first implemented SQLite subset is intentionally narrower than the full
target model. It creates `run_manifest`, `source_record`, `document`,
`document_identity`, `publication`, `ontology_entity`, `document_ontology_link`,
and `review_item`, then populates a minimal `legacy_identity_review` queue from
Initial Load publication candidates that lack PMID, PMCID, and DOI.

The first review access implementation sits above that SQLite subset and below
any web API or UI. It provides Pydantic DTOs for queue items, publication
summaries, publication detail records, ontology links, legacy reference values,
and simple review status updates. The current CLI uses this same access layer to
list queues, list open `legacy_identity_review` items, show publication detail,
and update review item status with an optional note.

The first FastAPI review API now reuses that same access layer. It serves local
health, queue, queue item, publication detail, and status-update endpoints from
`data/db/marygenai.sqlite` by default. Status updates remain limited to the
operational SQLite `review_item` state and preserve optional notes in the same
metadata history used by the CLI. The API does not modify Initial Load JSONL
snapshots or run manifests.

## Source Adapter Requirements

Each source adapter should expose a small common contract:

- source name and version;
- required configuration and credentials;
- request window or input identifiers;
- raw payload writer;
- normalized output schema;
- retry and backoff policy;
- rate-limit behavior;
- error capture;
- manifest output.

Adapters should write raw payloads and normalized records through shared storage
interfaces rather than hardcoded file paths. That keeps local disk and S3-like
storage interchangeable.

Semantic Scholar should be modeled as an enrichment adapter, not a blocking
dependency. Its API key can be absent in MVP 0.1. When present, it should enrich
existing canonical publications by DOI, PMID, title, or Semantic Scholar paper id.

Drug interaction sources should be modeled as specialized adapters that produce
`drug_interaction_document` records and interaction claim candidates. They should
not be forced into the publication model.

Ontology enrichment sources should also be adapters. For example, Wikipedia or
Wikidata may enrich pathology descriptions and aliases, PubMed or MeSH may enrich
biomedical terms, and ICD sources may enrich condition coding. These enrichments
must preserve source provenance and review state before becoming reviewed
ontology knowledge.

## Pipeline Requirements

The expected monthly update flow is:

1. Select the reviewed baseline or private bootstrap boundary.
2. Run PubMed discovery for explicit monthly windows. The current maintainer
   backfill starts at `2024/01/01` and continues through the current date.
3. Resolve identity against legacy and existing canonical documents.
4. Prioritize by `cannabinoid_focus` before citation or influence metrics.
5. Enrich selected candidates through PubMed, access resolvers, Europe PMC,
   Unpaywall, iCite, and optional Semantic Scholar.
6. Retrieve full text only for prioritized records with stable access paths.
7. Create extraction candidates for high-value fields.
8. Populate review queues.
9. Preserve all review decisions.
10. Export reviewed knowledge snapshots.

Each run must be idempotent. Re-running the same source window with the same
configuration should skip already completed payloads unless explicitly forced.

## Review And Collaboration Requirements

The review system must support:

- reviewer identity;
- role-aware access later, even if MVP 0.1 starts with local users;
- identity review for duplicates and uncertain matches;
- inclusion or exclusion decisions;
- field-level approval, correction, rejection, `not_applicable`, `not_reported`,
  and `needs_more_evidence`;
- notes or rationale;
- ontology version;
- extractor version;
- source provenance and evidence text.

The future open-source platform should be able to accept contributions as source
adapters, ontology updates, review exports, and reproducible pipeline runs without
requiring public access to private local data.

## Storage Migration Path

The persistence path should be:

1. Local files plus SQLite for MVP 0.1.
2. Docker Compose with persistent volumes for API, worker, UI, and SQLite.
3. Optional MinIO in local Compose to validate S3-like object keys.
4. Evaluate PostgreSQL, MongoDB, or another operational store when SQLite becomes
   limiting for multi-user review, ontology editing, or document-shaped access.
5. Optional Qdrant or another vector/hybrid retrieval layer for GenAI search,
   embeddings, agentic evidence lookup, and RAG experiments.
6. Managed S3-compatible object storage for raw payloads, normalized snapshots,
   extraction artifacts, and exports.
7. Optional dedicated search or graph layer only after review workflows and
   ontology traversal needs prove the access patterns.

PostgreSQL, MongoDB, OpenSearch, graph databases, and vector indexes should
remain architecture options rather than MVP prerequisites. The project should
choose them based on demonstrated review, ontology, collaboration, hybrid search,
and GenAI retrieval requirements.

## Security And Compliance Requirements

- Do not commit secrets, raw downloads, generated datasets, PDFs, or local
  scratch files.
- Do not commit private legacy exports.
- Do not make private legacy files a requirement for public contributors once
  reviewed baseline snapshots are available.
- Read credentials from environment variables or local ignored `.env` files.
- Keep source rate limits and terms of use visible in source adapter docs.
- Record source URLs and access methods for auditability.
- Avoid broad publisher scraping unless legality and operational stability are
  validated.
- Keep the product boundary explicit: reviewed evidence metadata is not medical
  advice.

## Initial Implementation Milestones

MVP architecture should be implemented incrementally:

1. Done: define first Pydantic contracts for source records, canonical
   publication candidates, ontology entities, document-to-ontology links, and run
   manifests.
2. Done: add a local storage interface that writes JSONL and JSON manifests to
   ignored `data/` paths.
3. Done: add an Initial Load CLI that imports legacy studies and ontology CSVs.
4. Done: add idempotent SQLite schema initialization, Initial Load persistence,
   and a minimal legacy identity review queue.
5. Done: add a reusable review queue query/status layer and CLI for the first
   `legacy_identity_review` queue.
6. Done: build the first FastAPI review endpoints around publications, review
   items, and review status updates.
7. Done: convert the validated PubMed discovery POC into a reusable candidate
   discovery command and SQLite review queue.
8. Done: build the first review UI around queue and detail screens for the
   legacy identity workflow.
9. Next: convert validated access and metadata enrichment POCs into reusable
   pipeline commands.
10. Later: add Docker Compose once API, worker, and database roles exist.
