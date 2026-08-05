# MVP Plan

## Objective

Operate a reproducible candidate-data flywheel that keeps cannabinoid medical
literature discoverable and current while preparing a trustworthy human-review
path that can activate when university curators become available.

The MVP is not a medical recommendation system. It exposes source-linked,
evidence-backed candidate records and preserves a separate promotion path to
human-reviewed knowledge.

## Current Baseline

MaryGenAI currently has:

- public PubMed discovery and identity association;
- targeted lawful source-access enrichment and artifact-quality audit;
- deduplicated corpus construction and source-quality gates;
- evidence-backed candidate classification with strict schemas;
- automated technical, retrieval, grounding, and inference evaluation;
- 3,149 strict-valid legacy-core candidate records;
- an isolated read-only DuckDB index and MCP interface;
- local review CLI, API, and UI for identity workflow operations;
- 1,361 post-legacy PubMed candidates awaiting a new corpus and classification
  cycle;
- a provider-free PubMed source-quality rollup and frozen eight-document v1
  canary, with a visible 92-document shortfall caused by rejected source
  identity mismatches;
- an archived website prototype that is not part of the public supported
  surface.

All indexed records remain `ai_classified_candidate` with
`review_state=needs_review`.

## MVP Deliverables For The Next Cycle

### 1. PubMed Candidate Refresh

Produce a new, reproducible candidate-data slice from the already discovered
PubMed 2024+ records:

- source-quality rollup;
- frozen canary manifest;
- identity/source repair before filling the 100-document target;
- bounded provider-backed classification after explicit authorization;
- automated evaluation and regression report;
- immutable local index rebuild;
- deliberate remote snapshot promotion after validation.

### 2. Dataset Viewer MVP

Provide a table-and-detail experience over the candidate index with filters,
source links, evidence, uncertainty, snapshot version, and explicit trust state.
The Viewer must not imply that candidate records are reviewed or openly
redistributable.

### 3. Public Website

Publish an accurate, community-oriented explanation of the project for
physicians, professors, students, and potential collaborators. The website
should make the dataset funnel, MCP role, safety boundary, limitations, and
curation opportunity understandable without requiring repository knowledge.

### 4. Curation-Ready Package

Prepare, but do not depend on, an external curation team:

- minimum field-level review contract;
- annotation-tool integration decision;
- versioned task export and validated response import;
- training, calibration, and first production packages;
- reviewer and institutional provenance;
- double-review and adjudication policy;
- reviewed-snapshot export contract.

### 5. Targeted Automated Legacy Recovery

Run bounded, measurable recovery experiments that do not require scientific
adjudication, beginning with official PMC failures and deterministic identity
suggestions. Ambiguous identity and scientific decisions remain queued for
humans.

## Operating Tracks

### Maintainer-Controlled Candidate Track

This track may proceed without active curators:

```text
discover
  -> resolve candidate identity
  -> acquire lawful source artifacts
  -> validate source quality
  -> classify candidate metadata
  -> evaluate
  -> rebuild immutable index
  -> expose through MCP and Viewer
```

It must not mutate protected review state or promote reviewed knowledge.

### Curation-Readiness Track

This track prepares tools and contracts so later activation is operational:

```text
freeze task package
  -> distribute to named reviewers
  -> collect independent responses
  -> validate identity, hashes, and schema
  -> preserve append-only decisions
  -> adjudicate when required
  -> export reviewed snapshot
```

The external annotation tool is never the sole source of truth. MaryGenAI must
retain the canonical document, candidate value, reviewed value, evidence,
reviewer, institution, timestamp, task version, rationale, and provenance.

## Quality Gates

### Source Gate

- authentic scientific content rather than challenge or metadata-only payload;
- sufficient usable text and scientific-section signal;
- lawful and auditable acquisition route;
- source URL or path, payload hash, extraction method, and error capture.

### Classification Canary Gate

- explicit maintainer authorization for provider cost;
- valid JSON and at least 98% strict schema validity;
- evidence spans for every strict-valid record;
- complete source, model, prompt, schema, run, and cost provenance;
- no new systematic grounding or enum defect;
- acceptable regression against the existing retrieval contract;
- no mutation of SQLite, review queues, decisions, or reviewed knowledge.

### Viewer Gate

- candidate versus reviewed state is visible on list and detail views;
- no private legacy context, local paths, credentials, or protected state;
- preferred source links and bounded zero-result language;
- useful filters and stable snapshot identity;
- no medical advice or treatment recommendation language.

### Curation-Activation Gate

- reviewer guidelines and examples are approved;
- training and calibration tasks are frozen;
- reviewer identity and institutional affiliation are captured appropriately;
- double-review and adjudication rules are defined;
- imports reject identity, source-hash, schema, and task-version mismatch;
- no response automatically becomes `human_reviewed`.

### Public Baseline Gate

- explicit software and data licenses;
- documented source redistribution boundary;
- reviewed-state promotion rules;
- dataset card, schema, limitations, and provenance;
- versioned export and reproducible Viewer;
- separation between candidate and reviewed releases.

## Prioritized Execution Order

1. Update the product contract and select the PubMed canary.
2. Build the PubMed source-quality rollup and local dry-run artifacts.
3. Build the Dataset Viewer read-only foundation.
4. Publish the community-oriented website.
5. Complete the annotation-tool spike and curation package adapters.
6. Run the provider-backed PubMed canary only after explicit authorization.
7. Expand eligible PubMed candidates after the canary passes.
8. Rebuild and promote an immutable candidate snapshot.
9. Run bounded automated legacy-recovery experiments.
10. Activate trained curators when partnerships are operational.

## Product Evaluation

Realistic, non-identifying physician questions remain a continuous input rather
than a blocking project phase. Use them to evaluate:

- useful candidate retrieval;
- false positives and suspected false exclusions;
- direct versus tangential presentation;
- source-opening behavior;
- missing filters and enrichment fields;
- clarity of candidate, uncertainty, and zero-result language.

## Out Of Scope

- diagnosis or treatment recommendation;
- automatic promotion from AI or annotation-tool response to reviewed
  knowledge;
- unbounded publisher crawling;
- recovering every historical source regardless of measured value;
- exact table, figure, dose, or protocol reconstruction as a default field;
- public dataset redistribution before licensing and source boundaries are
  documented;
- choosing a final multi-user database before the curation integration and
  concurrency requirements are validated.
