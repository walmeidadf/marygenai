# Candidate Classification V4 Plan

## Objective

Design a patient-oriented candidate retrieval contract that is sufficiently
structured for a read-only MCP server while minimizing unnecessary LLM calls.

V4 should improve retrieval-field coverage and correctness without turning
candidate metadata into clinical truth.

## Current Status

Completed as of 2026-06-23:

- patient-oriented classification architecture and data dictionary;
- reproducible profiling of the downloaded classification corpus;
- a frozen 12-document retrieval-field validation sample;
- a deterministic metadata/parser baseline with field evidence and provenance;
- local comparison against available legacy guardrails;
- official CLI commands, tests, and documentation.

The current downloaded corpus profile contains 6,490 canonical records, 3,374
source-ready records, 3,149 strict classification-ready records, and 225 broader
source-ready records. These locally generated counts define the current execution
universe; the legacy reference size does not.

The immediate next implementation is compact semantic prompt-packet preparation
and cost estimation. It must not call an LLM by default.

## Design Principles

1. The downloaded classification-eligible corpus defines execution scale.
2. The normalized English legacy dataset is a guardrail and normative bootstrap,
   not the classification queue.
3. Prefer metadata, parsers, and ontology matching before LLM extraction.
4. Use field-scoped evidence, confidence, uncertainty, and provenance.
5. Evaluate field families independently; do not hide errors in one record score.
6. Optimize cost per correct evidence-backed retrieval field.
7. Preserve broad recall when a narrow field is uncertain.

## Proposed Field Families

### Bibliographic And Study Context

- publication year;
- study and enrollment period;
- study countries;
- source and access quality.

### Clinical Topic

- medical conditions;
- pathologies or disease families;
- symptoms or indications;
- anatomical entities;
- organ systems;
- comorbidities.

### Cannabinoid And Intervention

- cannabinoid or exposure;
- entity-level role;
- principal intervention/exposure role;
- product or formulation;
- route;
- comparator.

### Population And Scale

- population category and description;
- age groups;
- sex or gender;
- species;
- sample size and sample-size scope.

### Study Structure

- publication type;
- study-design category and subtype;
- evidence context;
- randomization and blinding.

### Findings

- outcome domains and specific outcome entities;
- overall direction;
- adverse events;
- evidence-linked candidate findings.

## Architecture Options To Compare

### A. Broad LLM Record

One provider call predicts every semantic field. This is the current general
shape. It is simple but spends tokens on metadata fields and can create
cross-field errors.

### B. Independent Field-Family Calls

Separate calls classify clinical topic, cannabinoid/intervention, population,
study structure, and findings. This improves task focus but may multiply cost
and latency.

### C. Deterministic Assembly With Selective LLM Calls

Metadata and parsers fill direct facts. Ontology matching proposes entities.
Field-family LLM calls run only where semantic interpretation is required or
deterministic confidence is below a threshold.

Option C is the preferred hypothesis. It must earn that position through
measured quality and cost.

## Small Validation Sequence

### Phase 0: Local Baseline

No provider call:

- profile the current downloaded corpus and legacy-reference coverage;
- verify publication-year agreement;
- identify which fields already exist in structured metadata;
- prepare a 12- to 20-document stratified test set;
- build prompt packets and expected cost inputs;
- validate schemas, provenance, and evidence requirements.

### Phase 1: Metadata And Parser Capability

On the frozen sample:

- extract publication year, study country, sample size, route, species, and
  explicit design phrases;
- measure coverage, exactness, ambiguity, and extraction provenance;
- record which documents still need semantic classification.

The first 12-document baseline produced valid local artifacts for every input.
It found source candidates for sample size in 8 records, route in 8, country
mentions in 9, population in 12, and explicit design signals in 9. Against
available legacy guardrails, the candidate set contained the reference sample
size in 5 of 6 records and an overlapping route in 4 of 6.

This is candidate-retrieval performance, not final field accuracy. Multiple
numbers, cited designs, background species, affiliations, and non-primary routes
remain common. The parser should therefore select compact evidence candidates
for later semantic resolution rather than write final retrieval values silently.

### Phase 2: Small LLM Comparison

With explicit maintainer authorization, run 5 to 10 documents through:

1. one broad v4 prompt;
2. selective field-family prompts only for unresolved fields.

Use the same documents and model settings. Do not compare architectures on
different samples.

Before authorization, prepare and inspect:

- a versioned broad-v4 response schema and prompt;
- versioned field-family schemas and prompts;
- bounded parser evidence included in each packet;
- packet character and estimated token counts;
- projected provider cost inputs;
- local schema-valid mock responses;
- an evaluator that reports field quality and efficiency separately.

Recommended first semantic families:

1. clinical topic, anatomy, and organ system;
2. cannabinoid identity and scientific role;
3. population, sample-size selection, geography, and study structure;
4. outcomes and overall direction.

### Phase 3: Field-Scoped Review

Review each field family independently:

- clinical topic;
- anatomy and organ system;
- cannabinoid and role;
- population and sample;
- study structure;
- outcomes and direction.

The review artifact must retain the original source value, candidate value,
reviewed value, evidence, reviewer, method, and rationale.

## Evaluation Metrics

### Technical Validity

- provider and JSON success;
- strict schema pass rate;
- retries and latency;
- token usage and cost;
- complete source, model, prompt, schema, and run provenance.

### Retrieval Utility

- field coverage before and after LLM;
- evidence-supported field yield;
- broad-recall preservation under abstention;
- patient-query filterability;
- source-link and evidence availability.

### Inference Quality

- field-level precision, recall, and F1 where references permit;
- unsupported-label rate;
- relation errors, such as a background cannabinoid labeled as intervention;
- uncertainty precision and abstention quality;
- error patterns by field, source strategy, study type, and condition.

### Efficiency

- deterministic coverage rate;
- LLM invocation rate;
- tokens and cost per invoked document;
- cost per valid record;
- cost per populated field;
- cost per correct evidence-backed field;
- incremental quality per additional provider dollar;
- rerun cost.

## Initial Sample Design

The first sample should be drawn from the downloaded source-ready corpus and
stratified across:

- strict and broader source readiness;
- PMC, PDF, and augmented-link source strategies;
- predominantly direct source-text cannabinoid signal, plus a small low-focus
  contrast group;
- human clinical, observational, animal, laboratory, and review contexts;
- common and rare conditions;
- single and multiple cannabinoids;
- records with and without organ-system labels;
- records with and without legacy country or sample-size references;
- recent and older publication years.

Legacy availability is a sample annotation, not an eligibility requirement.

## Next-Session Entry Point

Start from the official local artifacts produced by:

```bash
uv run marygenai classification profile-retrieval-fields --sample-size 12
uv run marygenai classification extract-retrieval-metadata \
  --input-path <retrieval_field_validation_sample.jsonl>
```

Implement prompt-packet preparation under `src/marygenai/` and expose it through
the `marygenai classification` CLI. Do not call a provider until packet contents,
schemas, cost estimates, and tests have been reviewed.

## V4 Promotion Gate

Do not replace v3 or run a broad paid batch until:

- the data dictionary is accepted;
- the local deterministic baseline is reproducible;
- at least one field-scoped reviewed sample exists;
- selective LLM use improves meaningful retrieval fields;
- cost and latency are measured against the broad-call baseline;
- no essential MCP filter is silently discarded;
- candidate and reviewed states remain separate.
