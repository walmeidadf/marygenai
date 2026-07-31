# Classification Architecture

## Purpose

MaryGenAI classifies downloaded, source-ready scientific documents so that a
physician or research assistant can retrieve studies relevant to a patient
case. Classification produces candidate retrieval metadata with evidence and
provenance. It does not produce clinical truth or treatment recommendations.

## Corpus And Reference Boundary

The execution universe is the deduplicated downloaded corpus:

```text
discovered documents
  -> acquired source artifacts
  -> source-quality validation
  -> source-ready documents
  -> strict or broader classification eligibility
```

Only documents in this corpus determine classification volume, provider cost,
throughput, and completion rates.

The private normalized English legacy dataset has a different role:

- bootstrap the retrieval vocabulary and ontology;
- provide trusted-but-fallible comparison metadata;
- identify likely error families;
- stratify development and holdout samples;
- act as a prompt guardrail when identity is reliable;
- support local deterministic baselines.

The legacy dataset is not the classification queue, does not define scale, and
must not override explicit source evidence silently.

## Current V3 Flow

```text
classification-ready document
  -> source excerpt and normalized metadata
  -> one broad prompt packet
  -> one LLM response
  -> technical identity and provenance completion
  -> strict Pydantic validation
  -> candidate_study_classification.v3
  -> local evaluation
```

One response currently contains study design, evidence context, conditions,
cannabinoids or exposures, intervention role, population/model, outcome
domains, overall direction, evidence spans, uncertainty, and categorical model
confidence.

Technical validity, retrieval utility, and inference quality are three
evaluation perspectives over this output. They are not three provider calls.

## V3 Retrieval Gap

The classification corpus already carries publication year, condition labels,
organ-system labels, and cannabinoid labels. The v3 candidate schema does not
preserve every clinically useful dimension. In particular, organ systems enter
the prompt metadata but have no structured destination in the response.

V3 also lacks structured fields for study geography, sample size, study period,
age group, sex, comparator, and route of administration. Population detail is
mostly free text. `medical_conditions` currently risks mixing disease,
pathology, symptom, syndrome, adverse event, and substance-use concepts.

These gaps limit precise patient-oriented MCP filtering even when the JSON is
technically valid.

## V4 Direction: Deterministic First, LLM Selective

V4 should assemble a retrieval record from field-level extraction tracks rather
than asking one broad LLM call to rediscover every fact.

```text
canonical identity and bibliographic metadata
  + deterministic or structured-source extraction
  + ontology candidate matching
  + selective LLM semantic classification
  + field-level validation and evidence
  -> candidate retrieval record v4
```

Preferred extraction order:

1. canonical bibliographic or structured-source metadata;
2. deterministic parsing and normalization;
3. ontology and alias matching;
4. LLM classification only for semantic relations or unresolved ambiguity;
5. explicit abstention when evidence remains insufficient.

The local v4 packet builder represents this boundary with four field-routing
states: deterministic resolution, semantic resolution required, insufficient
evidence, and not applicable. Semantic responses contain only field decisions
and evidence references. Identity and provenance are assembled locally so model
output cannot rewrite source identity or review state.

Publication year, identifiers, and source availability should not consume LLM
tokens. Study country and sample size should use structured metadata or parsers
first. The LLM is most valuable for condition relevance, pathology grouping,
anatomical relation, cannabinoid role, population interpretation, study design,
outcomes, and source-supported direction.

## Field-Level Provenance

Every inferred or normalized retrieval value should preserve:

- source value and normalized value;
- extraction method and version;
- evidence span or structured-source location;
- source path and content hash;
- ontology version and entity identifier when available;
- categorical field confidence;
- uncertainty or abstention reason;
- model and prompt only when a model contributed;
- trust and human-review state.

Record-level confidence must not conceal weak individual fields.

## Physician-Oriented Retrieval

The intended MCP journey has three related stages.

### Before A Visit

Retrieve studies by patient condition, pathology or disease family, affected
organ system, age group, relevant cannabinoid, evidence context, outcome, and
publication period.

### During A Visit

Prioritize quick inspection of human relevance, population similarity, safety,
adverse events, study type, evidence excerpts, uncertainty, and source links.

### After A Visit

Support deeper research over intervention details, comparator, route, sample
size, geography, study period, conflicting evidence, and related publications.

The MCP server should expose retrieval evidence. It must not convert retrieval
rank into a treatment recommendation.

## Implemented Read-Only V1 Retrieval Layer

The first retrieval layer materializes all 3,149 strict candidate v3 records,
corpus identity, and evaluation outputs into an isolated ignored DuckDB artifact.
It exposes search, detail, facets, and capabilities through the supported
`marygenai` CLI, MCP stdio, and stateless Streamable HTTP server. The deployed
AWS pilot serves a content-addressed copy of that artifact through API Gateway
and Lambda while preserving the same read-only query service.

V1 uses deterministic case-folded alias keys, explicit `any` or `all` facet
semantics, opaque build-bound pagination cursors, and no silent filter
relaxation. Original candidate labels remain unchanged in detail responses.
Every response preserves candidate trust language and review state. Detail also
returns source path and hash, evidence spans, grounding-review worklist status,
retrieval-confidence semantics, versions, and provenance.

Question decomposition remains the MCP host's responsibility. MaryGenAI does
not receive a patient record, call an LLM, or infer treatment applicability.
The host should send only non-identifying scientific retrieval dimensions. It
also translates Portuguese or other non-English concepts to the primarily
English index and must preserve the machine-readable result-presentation
contract.

The current lexical index does not close the v3 field gaps described above.
Those gaps, realistic clinical acceptance questions, and external MCP research
are preserved in `docs/mcp_clinical_retrieval_research.md`.

## Ranking Components

Ranking should remain decomposable:

- `patient_match`: condition, pathology, anatomy, population, and demographics;
- `intervention_match`: cannabinoid, role, product, route, and comparator;
- `evidence_relevance`: outcomes, study design, context, and sample information;
- `source_confidence`: source quality, grounding, provenance, and uncertainty;
- `recency`: publication year or explicit study period.

These components may support broad-recall and high-precision profiles. They
must remain distinct from clinical evidence strength.

## Cost And Efficiency

Cost evaluation follows the actual downloaded corpus:

```text
downloaded
  -> source-ready
  -> classification-ready
  -> deterministically enriched
  -> LLM-required
  -> provider-successful
  -> schema-valid
  -> evidence-supported fields
```

Required efficiency metrics include:

- LLM invocation rate among eligible documents;
- input and output tokens per invoked document;
- cost per eligible document;
- cost per valid candidate record;
- cost per correct evidence-backed retrieval field;
- latency per document and per field family;
- deterministic coverage before LLM;
- incremental quality gained from LLM use;
- abstention and rerun rates.

The preferred architecture minimizes calls without lowering patient-oriented
retrieval quality.
