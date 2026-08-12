# Architecture

MaryGenAI is a local-first scientific source-intelligence pipeline with a
deployed read-only retrieval pilot for physicians, researchers, and AI
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
- `retrieval`: immutable DuckDB index construction and read-only queries;
- `viewer`: web-safe projections of retrieval search, facets, snapshot identity,
  and study detail;
- `mcp_server`: MCP tools over local stdio or stateless Streamable HTTP;
- `deployment`: reproducible Lambda packaging without embedding data;
- `analytics`: read-only local reports;
- `persistence`: SQLite schema and connections;
- `review`, `review_api`, `review_ui`: explicit human workflow surfaces.

Public operations should call these modules through the `marygenai` CLI.

The supported frontend lives under `web/`. It uses React with vinext and keeps
website and Dataset Viewer presentation separate from Python data services. It
does not contain a database, authentication layer, review-state writer, or
provider integration.

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

Candidate confidence is model-declared and categorical. The experimental
`retrieval_confidence.v1` evaluator computes a separate deterministic heuristic
ranking signal. It is not calibrated and remains outside the candidate schema
while weights and retrieval behavior are validated.

The current broad v3 provider response is not the final architecture. V4 planning
prefers field-level deterministic enrichment followed by selective semantic
classification. See [Classification Architecture](classification_architecture.md)
and [Classification Data Dictionary](classification_data_dictionary.md).

## Retrieval Surface

The first external integration is a read-only MCP server over discovered,
metadata-enriched, source-ready, and candidate-classified documents. The same
AWS gateway also deploys a web-safe Dataset Viewer projection at
`/api/viewer/*`. Both interfaces use one content-addressed DuckDB snapshot
through API Gateway and a Python 3.13 Lambda. Lambda verifies the S3 object hash,
caches the snapshot under `/tmp`, and opens it with `read_only=True`. It receives
no SQLite database, review workflow state, or provider credentials. MCP and
Viewer have separate bearer credentials, while `/health` remains public and
corpus-free.

Retrieval should support:

- structured filters;
- lexical search;
- ontology-aware expansion;
- optional vector similarity;
- confidence-aware ranking;
- direct evidence and source links.

The retrieval layer is rebuildable. It is not the source of truth. The current
host is responsible for translating non-English questions to concise English
retrieval terms and for presenting candidate, zero-result, access-link, and
study-detail limitations defined by the MCP contract.

## Website And Dataset Viewer

The first web release has two routes:

- `/` explains the project, implemented pipeline, MCP role, current counts,
  safety boundary, limitations, and future university collaboration;
- `/dataset` provides text search, URL-backed filters, deterministic ordering,
  pagination, trust labels, direct/tangential match presentation, and study
  detail with identity, evidence, uncertainty, warnings, and provenance.

The web data path is:

```text
browser
  -> vinext same-origin viewer routes
  -> optional MaryGenAI Viewer API
  -> RetrievalService
  -> immutable DuckDB opened read-only
```

`MARYGENAI_VIEWER_API_BASE_URL` enables the optional server-side proxy. Without
it, the frontend serves a small versioned set of fictional public fixtures and
labels the entire experience as a synthetic demonstration. No private legacy
data or ignored candidate artifact is copied into the frontend.

The authenticated AWS path additionally requires the server-only
`MARYGENAI_VIEWER_API_BEARER_TOKEN`. The proxy adds that credential upstream,
never exposes it to browser JavaScript, and marks candidate responses private
and non-cacheable. A static Pages upload cannot hold this secret; the later
Cloudflare Functions or Worker step provides that server-side boundary.

The Python Viewer API reuses `SearchRequest`, `SearchFilters`, facets, study
detail, projected identity, and snapshot metadata from the retrieval layer. Its
responses deliberately omit local source paths while retaining non-sensitive
source hashes and classification provenance. Cursor pagination remains the
retrieval contract; the web adapter presents stable numbered pages by following
opaque cursors without changing index ordering.

The frontend has a Sites-compatible build configuration and the maintainer
reports a Cloudflare Pages deployment. A static Pages build can serve the site
and synthetic Viewer because the browser falls back to the explicitly labeled
fictional fixtures when `/api/viewer/*` is absent. A deployment with compatible
Pages Functions or Worker output can also serve the same-origin proxy routes.
Real candidate retrieval still needs a separately hosted read-only Viewer API
with access to an approved immutable snapshot. The preferred initial production
path is to reuse the existing AWS API Gateway, Lambda, S3, and hash-verified
DuckDB pattern rather than duplicate
retrieval behavior in the frontend. Publication of candidate data remains a
deliberate operation after exposure, access, and licensing boundaries are
reviewed.

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
