# Architecture Approach

The project starts as a data-source and ontology lab. Architecture should emerge from the evidence gathered in POCs.

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

POC 7 should add a legacy association layer for publication discovery. Fresh
PubMed results should be compared against the curated legacy dataset by stable
identifiers first, then canonical URL and normalized title. The association state
should be explicit, for example `in_legacy_exact`, `possible_legacy_match`,
`new_candidate`, or `needs_manual_identity_review`.

The legacy dataset is a trusted curated reference. Populated legacy values should
be preserved as reference values for comparison and review. Missing legacy values
should not be interpreted as extraction failures without field applicability
context.

### Ontology Layer

Versioned vocabularies and mappings stored under `ontology/`.

This should begin as simple structured files, such as YAML or JSON. RDF/OWL or graph databases may be considered later if the relation model justifies them.

### Application Layer

Deferred until after source POCs. Candidate storage approaches include:

- files plus DuckDB;
- SQLite;
- PostgreSQL;
- document databases;
- graph databases;
- hybrid search/indexing.

## Design Principles

- Keep source payloads auditable.
- Separate document identity from source identity.
- Separate extraction from review.
- Separate legacy association from new-publication discovery.
- Treat dosing and drug interactions as specialized extraction domains.
- Prefer field-level provenance over a single record-level confidence score.

## Full-Text Extraction Notes

The first small full-text sample supports an HTML/XML-first architecture:

- prefer PMC HTML when `PMCID` is available;
- use Europe PMC full-text XML when it is available through the API;
- do not rely on Europe PMC rendered article pages as static HTML extraction
  targets;
- keep PDF retrieval as a narrow fallback or supplemental artifact until text
  extraction value justifies a parser;
- route every extracted field through HITL before it becomes reviewed knowledge.

The production pipeline should treat LLM extraction as an evidence-generation
step, not as final truth. LLM outputs need the same field-level provenance and
review state as heuristic extraction outputs.

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
