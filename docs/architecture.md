# Architecture

MaryGenAI is a local-first scientific source-intelligence pipeline designed to
grow into a read-only retrieval service for physicians, researchers, and AI
assistants.

## Architectural Boundary

The system has two distinct jobs:

1. Build auditable scientific-document records and candidate retrieval labels.
2. Preserve an optional human-review layer that can promote candidate evidence
   into reviewed knowledge.

The first job must not mutate review queues, decisions, or reviewed knowledge.

## Supported Modules

Supported implementation lives under `src/marygenai/`:

- `initial_load`: maintainer-only private bootstrap import;
- `pubmed_discovery`: date-windowed publication discovery and identity matching;
- `access_enrichment`: source-access and full-text enrichment;
- `classification_corpus`: deduplicated source-ready corpus rollup;
- `classification`: prompt preparation and bounded candidate classification;
- `analytics`: read-only local reports;
- `persistence`: SQLite schema and connections;
- `review`, `review_api`, `review_ui`: explicit human workflow surfaces.

Public operations should call these modules through the `marygenai` CLI.

## Data Layers

```text
data/
  raw/           # immutable source payloads
  staging/       # source-specific normalized records
  processed/     # extracted or normalized source text
  normalized/    # canonical documents, corpora, and candidate classifications
  reviewed/      # future promoted human-reviewed snapshots
  manifests/     # run configuration, counts, hashes, and errors
  db/            # local SQLite operational review state
```

`data/` is ignored by Git and should map cleanly to future object storage.

`temp/` contains private legacy inputs, archived experiments, and scratch
artifacts. It is not a public runtime dependency except for explicit
maintainer-only bootstrap commands.

## Core Domains

Keep these domains separate:

- source record;
- canonical document;
- publication;
- clinical trial record;
- drug interaction document;
- source-text artifact;
- ontology entity and document mapping;
- candidate classification;
- review item and review decision;
- reviewed knowledge.

Do not force every scientific object into an article model.

## Identity And Deduplication

Stable identity should prefer PMID, PMCID, and DOI, followed by canonical URL and
normalized title/year matching. Corpus outputs deduplicate by `document_id`.

Source-window counts and canonical-document counts are different metrics because
the same PMID may appear in more than one discovery window.

## Source Strategy

PubMed is the primary discovery and bibliographic identity hub. It is not a
general full-text crawler.

Preferred source routes:

1. PMC official structured or declared full text;
2. repository or open-access structured text;
3. lawful digital PDF extraction;
4. selected publisher or repository links;
5. OCR only for residual scanned or poor-text-layer PDFs.

Every artifact must pass content-quality checks. HTTP success and metadata-only
payloads do not make a document source-ready.

## Candidate Classification

Classification is a retrieval-enrichment stage:

```text
source text
  -> prompt packet
  -> provider response
  -> strict schema validation
  -> candidate classification artifact
  -> retrieval index or later human review
```

Candidate outputs preserve:

- source path and content hash;
- model, prompt, schema, and extractor versions;
- evidence spans;
- field and record confidence;
- warnings and uncertainty;
- token usage and latency;
- trust and review boundaries.

Current confidence is model-declared and categorical. A future calibrated
retrieval score should be computed separately from deterministic and empirical
signals.

## Retrieval Surface

The intended first external integration is a read-only MCP server over discovered,
metadata-enriched, source-ready, and candidate-classified documents.

Retrieval should support:

- structured filters;
- lexical search;
- ontology-aware expansion;
- optional vector similarity;
- confidence-aware ranking;
- direct evidence and source links.

The retrieval layer is rebuildable. It is not the source of truth.

## Persistence

Current persistence:

- ignored local files for immutable payloads and snapshots;
- SQLite for operational review state;
- JSONL for audit and interchange.

Future object storage, PostgreSQL, document stores, search engines, graph stores,
or vector databases should be adopted only when demonstrated access patterns
justify them.

## Safety And Trust

Trust levels remain explicit:

- `source_discovered`;
- `metadata_enriched`;
- `source_text_available`;
- `ai_classified_candidate`;
- `human_reviewed`.

Only the last level represents reviewed knowledge. Neither retrieval confidence
nor study design is a clinical recommendation.
