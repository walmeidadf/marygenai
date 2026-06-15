# Architecture Approach

The project starts as a data-source, ontology, source-intelligence, and
candidate-classification lab. Architecture should emerge from the evidence
gathered in POCs.

The public repository does not include the maintainer's private legacy exports.
The architecture distinguishes private bootstrap inputs from public reviewed
outputs. Private bootstrap data can anchor the maintainer's local review
workflow, but public contributors should eventually start from reviewed
snapshots exported by the project.

## Working Layers

### Raw Layer

Immutable source outputs, stored under `data/raw/` during local experiments.

Examples:

- PubMed XML or JSON;
- Europe PMC API responses;
- ClinicalTrials.gov JSON;
- Unpaywall metadata;
- drug interaction HTML or structured payloads;
- small PDF samples.

### Normalized Layer

Canonical records extracted from raw payloads, stored under `data/normalized/` during POCs.

Candidate entities:

- `source_record`;
- `research_document`;
- `publication`;
- `clinical_trial_record`;
- `drug_interaction_document`;
- `pdf_document`;
- `extraction_run`;
- `human_review`.

POC 6 reinforced that field-level extraction records should store:

- selected source URL and source format;
- extraction method;
- evidence text;
- confidence;
- review state;
- errors and fallback attempts.

POC 7 added a baseline association layer for publication discovery. Fresh
PubMed results should be compared against the private bootstrap or future public
baseline by stable
identifiers first, then canonical URL and normalized title. The association state
should be explicit, for example `in_legacy_exact`, `possible_legacy_match`,
`new_candidate`, or `needs_manual_identity_review`.

The maintainer's private bootstrap is a trusted curated reference. Populated
bootstrap values should be preserved as reference values for comparison and
review. Missing values should not be interpreted as extraction failures without
field applicability context. Public reviewed snapshots should preserve this same
reference/provenance distinction without exposing private raw files.

### Ontology Layer

Versioned vocabularies and mappings stored under `ontology/`.

This should begin as simple structured files, such as YAML or JSON. RDF/OWL or graph databases may be considered later if the relation model justifies them.

### Application Layer

The next application layer is the MVP source-intelligence and
candidate-classification platform documented in [MVP Plan](mvp_plan.md). Its
first maintainer job is to load and validate private bootstrap records, discover
PubMed candidate publications from January 2024 onward, enrich selected
candidates, prepare classification-ready corpora, generate candidate
classifications with provenance, and preserve review decisions when human review
is available.

Candidate storage approaches include:

- SQLite;
- files plus DuckDB;
- PostgreSQL;
- document databases;
- graph databases;
- hybrid search/indexing.

SQLite is the preferred first MVP persistence option because it is simple,
portable, and sufficient for an internal review queue. JSONL exports should remain
available for audit and interchange.

The current local application layer has landed in three small slices:

- `marygenai.review`: reusable Pydantic DTOs and SQLite repository access for
  review queues, publication detail, ontology links, legacy references, and
  status updates;
- `marygenai.review_api`: a FastAPI layer over those DTOs and repository
  functions;
- `marygenai.review_ui`: a static local UI mounted at `/ui` by the FastAPI app
  for the first `legacy_identity_review` workflow.
- `marygenai.pubmed_discovery`: the first post-legacy discovery slice. It
  stages PubMed source records and normalized candidate enrichments under
  ignored `data/` paths, classifies them against legacy identity state, and
  persists non-exact candidates to SQLite review state.

This is still an internal curation surface. It does not make the project a
clinical or public recommendation product.

The future external integration surface should be read-only. A candidate MCP
server can expose discovered, metadata-enriched, source-ready, and
candidate-classified scientific documents to AI tools, but it must preserve trust
levels and avoid presenting candidate classifications as reviewed clinical
truth.

## Design Principles

- Keep source payloads auditable.
- Separate document identity from source identity.
- Separate extraction from review.
- Separate legacy association from new-publication discovery.
- Separate source readiness from AI candidate classification.
- Separate AI candidate evidence from human-reviewed knowledge.
- Treat dosing and drug interactions as specialized extraction domains.
- Prefer field-level provenance over a single record-level confidence score.
- Let `cannabinoid_focus` dominate review ranking; citation metrics are secondary
  audit signals.

## Full-Text Extraction Notes

The first small full-text sample supports an HTML/XML-first architecture:

- prefer PMC HTML when `PMCID` is available;
- use Europe PMC full-text XML when it is available through the API;
- do not rely on Europe PMC rendered article pages as static HTML extraction
  targets;
- keep PDF retrieval as a narrow fallback or supplemental artifact until text
  extraction value justifies a parser;
- route every extracted field through HITL before it becomes reviewed knowledge.

The production pipeline should treat LLM extraction and classification as
evidence-generation steps, not as final truth. LLM outputs need the same
field-level provenance and review state as heuristic extraction outputs.

The preferred LLM shape is a two-stage flow:

- first, extract candidate evidence snippets from section-scoped text;
- then, normalize those candidates into strict Pydantic models.

Small local models may be useful in the first stage, while hosted models can be
used as comparison baselines for structured normalization. Both stages still feed
HITL review.

POC 6b confirmed this shape on records `340`, `164`, and `43`. The runner writes
strict normalized records under `data/normalized/pdf_samples`, preserves provider
and model provenance, records provider errors separately from accepted candidates,
and forces every normalized field to `needs_review=true` and
`review_state=needs_review`.

Provider-specific notes from POC 6b:

- heuristic extraction remains a useful deterministic baseline, but is too noisy
  to prefill all fields without review;
- local Ollama `qwen3:8b` can identify evidence on smaller case-report contexts,
  but should not be trusted as the final JSON producer;
- Groq structured calls were reliable for the three-record comparison when using
  smaller section-selected prompts and a delay between calls, but token-per-minute
  limits were tight;
- OpenRouter free models are useful for exploration, but the free router can be
  slow and explicit free models may return truncated JSON or hit `429`.

The next architecture refinement should add provider retry/backoff based on
rate-limit headers and improve section ranking before any broader LLM run.

## MVP Architecture Requirements

The first MVP should remain local-first while being shaped for later open-source
collaboration and cloud deployment. The recommended persistence shape is local
files plus SQLite for MVP 0.1, with local `data/` paths mirroring future
S3-compatible object keys. Raw payloads, staging outputs, normalized snapshots,
review database state, and reviewed exports should stay separate.

The first Initial Load implementation follows this shape. It lives under
`src/marygenai/initial_load/`, uses Pydantic schemas in `src/marygenai/schemas.py`,
writes through a local storage interface in `src/marygenai/storage.py`, and runs
with:

```bash
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

The maintainer's first run imports the private legacy studies and ontology CSVs from
`temp/legacy/cannadocs/` into ignored JSONL snapshots and a run manifest. SQLite
now provides the first operational review database at `data/db/marygenai.sqlite`.
The initial schema loads run manifests, source records, canonical documents,
publication identities, publication metadata, ontology entities,
document-to-ontology links, and a minimal legacy identity review queue. The
current maintainer local environment has one Initial Load run,
`20260515T143451Z`, and a `legacy_identity_review` queue with 1,206 open items.
That queue is only the weaker identity subset; most bootstrap records are already
usable for matching by PMID, PMCID, or DOI.

The architecture should also preserve a GenAI path. Agentic evidence search,
hybrid lexical/vector retrieval, ontology-aware filters, and RAG over reviewed
evidence are expected future capabilities, but generated answers must remain
grounded in reviewed fields, evidence text, and provenance. PostgreSQL, MongoDB,
Qdrant, search indexes, and graph stores should be evaluated by role and access
pattern rather than selected upfront.

See [MVP Architecture Requirements](mvp_architecture_requirements.md) for the
proposed service boundaries, local data layout, SQLite schema domains, source
adapter contract, Docker path, S3-compatible storage path, and monthly pipeline
requirements.
