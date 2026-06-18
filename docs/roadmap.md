# Roadmap

## Product Direction

MaryGenAI is building a source-intelligence and candidate-classification layer
that helps physicians, researchers, and AI assistants find and inspect studies
about cannabinoid medicine.

The first external surface should be read-only retrieval, likely MCP. Human
review remains a higher trust layer, but broad manual curation is not a
prerequisite for useful candidate retrieval.

## Now: Classification Reliability

1. Validate schema-v3 prompt packets against the targeted 10-document rerun set.
2. Re-run only the three schema failures and seven study-design disagreements.
3. Use the repeatable evaluation command for English legacy alignment, evidence
   coverage, unsupported labels, and retrieval utility.
4. Define confidence semantics:
   - model-declared classification confidence;
   - deterministic pipeline confidence;
   - future calibrated retrieval confidence;
   - clinical evidence strength, which remains a separate concept.
5. Re-run only affected and disagreement records before another broad paid run.

## Next: Bounded Scale

1. Run a larger stratified batch after known defects are fixed.
2. Measure quality by condition, study type, source strategy, and source quality.
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
2. Support structured filters over condition, cannabinoid, study type,
   population, outcome, source readiness, and confidence.
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
