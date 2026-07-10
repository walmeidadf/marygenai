# MVP Plan

## Objective

Build a reproducible source-intelligence and candidate-classification pipeline
that makes cannabinoid medical literature discoverable and filterable by humans
and AI assistants.

The MVP should produce read-only retrieval records with publication identity,
source provenance, structured candidate labels, evidence spans, uncertainty, and
trust level. It is not a medical recommendation system.

## MVP Deliverable

A downstream client should be able to request:

> Find source-ready clinical meta-analyses about CBD and epilepsy, prefer
> high-confidence classifications, and return supporting evidence and source
> links.

The system should return candidate records suitable for research triage. It
should not answer whether a patient should receive a treatment.

The target retrieval journey begins with the patient's condition and context.
Study design, evidence setting, source quality, and recency refine and rank the
candidate studies rather than replacing patient-condition relevance.

## Current Capabilities

- private maintainer bootstrap import into auditable JSONL;
- local SQLite operational review state;
- PubMed candidate discovery and identity association;
- targeted access enrichment and artifact-quality audit;
- deduplicated classification corpus rollup;
- strict candidate-classification schema;
- prompt packet generation without provider calls;
- bounded OpenAI-backed classification validation;
- downloaded-corpus retrieval-field profiler;
- frozen patient-oriented retrieval-field sample builder;
- deterministic metadata/parser candidate extraction;
- broad-v4 versus selective field-family packet and cost comparison;
- review CLI, API, and local UI for explicit review workflows.

## Current Local Dataset

The June 2026 legacy-core campaign established:

- about 6,491 operational documents with strong identity;
- about 3,149 strict classification-ready documents;
- about 3,374 broader source-ready documents.

These are maintainer-local generated artifacts, not committed public datasets.
The public growth path is continuous PubMed discovery and future reviewed
snapshot publication.

## Product Quality Gates

### Technical Validity

- provider and HTTP success;
- valid JSON and strict schema pass rate;
- retry and error reasons;
- latency and cost;
- complete run artifacts and provenance.

### Retrieval Utility

- identity and source coverage;
- evidence-span presence;
- useful field coverage for filtering;
- confidence-aware broad and narrow retrieval;
- preservation of relevant records when a field is uncertain.

### Inference Quality

- agreement with normalized English legacy references where available;
- source-supported disagreements;
- unsupported labels and grounding failures;
- systematic error by field or source type;
- confidence and uncertainty calibration.

## Classification Gate Status

The 2026-06-18 100-document schema-v2 run produced:

- 100 provider responses without retries;
- 97 strict-valid records;
- evidence spans for all 97 valid records;
- 90/97 exact principal study-type matches against English legacy context;
- three correctable validation failures caused by `outcome_domains` values;
- no technical provenance fields incorrectly reported as scientific uncertainty.

This supports the product direction but does not yet justify an unattended
full-corpus run. The remaining work is localized schema/prompt hardening,
repeatable evaluation, and confidence semantics.

Schema v3 makes cognition an explicit outcome domain, keeps unsupported list
values empty rather than inserting `cannot_determine`, adds granular
study-design subtype metadata, and makes uncertainty field-scoped and
machine-readable. The official local evaluator produces a targeted input for
the three historical schema failures and seven study-design disagreements.
A deterministic command now also prepares a stratified, title-explicit
study-design benchmark candidate set. Human review is still required before it
becomes a trusted training or calibration reference.

The first 21 legacy-disagreement candidates have now been reviewed as the
development benchmark. A separate 40-record holdout was frozen before
deterministic rule-v2 work, and an official evaluator measures category,
subtype, pair, per-label, legacy-reference, and error-pattern metrics.

Deterministic `study_design_rules.v2` now reaches 20/21 exact
category-plus-subtype matches on the development benchmark and has been applied
to the frozen holdout without inspecting its labels.

V4 preparation now has a reproducible 12-document cross-domain sample, a local
parser baseline, versioned broad and selective packet schemas, contrast-aware
manifests, deterministic selective assembly, and local cost projections. The
selective architecture produced useful provenance and routing lessons, but it
is no longer an MVP blocker.

The first 50-document broad/v3 canary completed on 2026-07-10. It produced
49 strict-valid candidate records, one validation error, no retries, and an
estimated cost of about USD 0.51. Measured usage projects the 3,149-record
strict corpus at about USD 32.01 through standard synchronous calls, or about
USD 16.01 if a Batch-compatible workflow is implemented. The next gate is now
resumable or batch-oriented execution plus a read-only retrieval/MCP prototype.
Local Batch-compatible JSONL preparation is therefore part of the MVP execution
path before another paid provider run.

The first remote 50-document Batch later completed successfully and converted to
50/50 strict-valid records after deterministic technical uncertainty-marker
repair. Measured Batch cost projects the strict corpus at about USD 16.07. The
next full-corpus requirement is chunked Batch execution with local manifests,
status monitoring, prompt/evidence evaluation, and targeted review of the eight
canary documents selected by the evaluator, not another prompt architecture
comparison.

## MVP Workstreams

1. Freeze selective-v4 work as documented findings and future optimization.
2. Preserve the 50-document broad/v3 canary artifacts and use them as the first
   MCP-demo candidate base.
3. Use chunked Batch preparation plus `watch-batch` monitoring before any full
   strict-corpus classification run.
4. After approval and credit top-up if needed, run the first strict-corpus
   candidate-classification batch.
5. Build a read-only retrieval index over candidate records, source identity,
   evidence spans, uncertainty, and provenance.
6. Design and implement a read-only MCP retrieval contract.
7. Prepare medical-team demo journeys and targeted human-review exports.
8. Use reviewer feedback to prioritize field-scoped improvements for
    condition, anatomy, cannabinoid role, population, study structure, and
    outcomes.
9. Continue PubMed discovery and source acquisition using supported commands.
10. Publish a public baseline snapshot when licensing and review boundaries are
    ready.

## Data Safety

Corpus preparation, classification, and evaluation:

- read ignored local artifacts;
- write ignored local artifacts;
- deduplicate by `document_id`;
- do not mutate SQLite, review state, review items, review decisions, or reviewed
  knowledge.

Only explicit review and persistence commands may change operational SQLite state.

## Out Of Scope

- medical advice;
- automatic promotion to reviewed knowledge;
- broad publisher crawling;
- exact table or figure interpretation;
- dosage and protocol reconstruction as a default field;
- choosing a final cloud database before retrieval needs are demonstrated.
