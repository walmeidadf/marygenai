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

## Current Capabilities

- private maintainer bootstrap import into auditable JSONL;
- local SQLite operational review state;
- PubMed candidate discovery and identity association;
- targeted access enrichment and artifact-quality audit;
- deduplicated classification corpus rollup;
- strict candidate-classification schema;
- prompt packet generation without provider calls;
- bounded OpenAI-backed classification validation;
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

## MVP Workstreams

1. Stabilize classification schema and uncertainty representation.
2. Add repeatable legacy-alignment and retrieval-utility evaluation.
3. Define a computed retrieval confidence contract distinct from model
   self-assessment and study evidence strength.
4. Run a larger bounded classification batch after known defects are corrected.
5. Continue PubMed discovery and source acquisition using supported commands.
6. Design a read-only MCP retrieval contract.
7. Publish a public baseline snapshot when licensing and review boundaries are
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
