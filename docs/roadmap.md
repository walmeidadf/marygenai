# Roadmap

## Product Direction

MaryGenAI is building a source-intelligence and candidate-classification layer
that helps physicians, researchers, and AI assistants find and inspect studies
about cannabinoid medicine.

The first external surface should be read-only retrieval, likely MCP. Human
review remains a higher trust layer, but broad manual curation is not a
prerequisite for useful candidate retrieval.

## Now: Classification Reliability

Completed in the current v4 preparation cycle:

- patient-oriented data dictionary and classification architecture;
- downloaded-corpus profiling and execution-universe correction;
- frozen 12-document cross-domain validation sample;
- deterministic metadata/parser baseline with evidence candidates;
- initial parser-versus-legacy guardrail comparison.

Immediate next step: build broad and selective semantic prompt packets, validate
their schemas locally, and estimate tokens and cost before any provider call.

1. Accept the v4 patient-oriented data dictionary and retrieval architecture.
2. Profile the downloaded corpus to measure deterministic field coverage and
   the actual LLM-eligible execution universe.
3. Freeze a small cross-domain validation sample from source-ready documents.
4. Test metadata and parser extraction for publication year, geography, sample
   size and scope, route, species, and explicit study structure.
5. Run field-scoped review for condition, pathology, anatomy, cannabinoid role,
   population, outcomes, and study structure.
6. Compare broad-record and selective LLM calls on the same authorized sample.
7. Report LLM invocation rate, tokens, latency, cost per valid record, and cost
   per correct evidence-backed field.
8. Test `retrieval_confidence.v1` on realistic broad versus narrow retrieval
   queries and a small broader-source-ready contrast set.
9. Perform weight sensitivity analysis before adding retrieval confidence to a
   public schema.
10. Complete the frozen 40-record study-design holdout interpretation without
    treating study design as the only inference-quality domain.
11. Re-test classical classifiers and NLI semantic support against reviewed
    field-scoped benchmarks before adding either signal to retrieval confidence.
12. Re-run only affected and disagreement records before another broad paid run.

## Next: Bounded Scale

1. Run a larger stratified batch after known defects are fixed.
2. Measure quality by field family, condition, study type, source strategy, and
   source quality.
3. Test broad-recall versus high-confidence retrieval behavior.
4. Estimate full-corpus cost and failure handling.
5. Establish resumable, idempotent batch execution.

## Next: Continuous Source Growth

1. Continue explicit-window PubMed discovery.
2. Deduplicate canonical documents across windows.
3. Prioritize direct cannabinoid focus.
4. Enrich source access through official and lawful routes.
5. Keep invalid payload, source triage, and identity/focus queues separate.
6. Publish source-intelligence snapshots when licensing permits.

## Later: Read-Only Retrieval

1. Define an MCP resource and query contract.
2. Support structured filters over condition, pathology, anatomy, organ system,
   cannabinoid and role, study type, population, geography, publication period,
   outcome, source readiness, and confidence.
3. Return evidence spans, source identity, provenance, and trust level.
4. Add lexical and ontology-aware retrieval before introducing vector search.
5. Evaluate hybrid retrieval and ranking with realistic physician queries.

## Later: Reviewed Public Baseline

1. Define promotion from candidate evidence to human-reviewed knowledge.
2. Export reviewed snapshots without exposing private legacy inputs.
3. Preserve reviewer, original value, reviewed value, rationale, timestamp,
   ontology version, and extractor version.
4. Let public users bootstrap from reviewed snapshots.

## Readiness Criteria For Mass Classification

Mass classification is justified when:

- known schema and prompt defects are corrected;
- execution is resumable and idempotent;
- strict validation and retry policy are measured;
- retrieval usefulness is demonstrated, not only label agreement;
- confidence and uncertainty have stable semantics;
- source, evidence, model, prompt, and cost provenance are complete;
- candidate output remains isolated from reviewed knowledge.

## Readiness Criteria For MCP

The MCP surface is justified when:

- candidate records have a stable retrieval schema;
- filtering dimensions are useful on real questions;
- evidence and source links are consistently returned;
- trust levels and uncertainty are unambiguous;
- retrieval cannot be mistaken for medical advice.
