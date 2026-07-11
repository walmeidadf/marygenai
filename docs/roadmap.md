# Roadmap

## Product Direction

MaryGenAI is building a source-intelligence and candidate-classification layer
that helps physicians, researchers, and AI assistants find and inspect studies
about cannabinoid medicine.

The first external surface should be read-only retrieval, likely MCP. Human
review remains a higher trust layer, but broad manual curation is not a
prerequisite for useful candidate retrieval.

## Now: First Candidate Base And Read-Only MCP

Completed in the v4 preparation cycle:

- patient-oriented data dictionary and classification architecture;
- downloaded-corpus profiling and execution-universe correction;
- frozen 12-document cross-domain validation sample;
- deterministic metadata/parser baseline with evidence candidates;
- initial parser-versus-legacy guardrail comparison;
- broad-v4 versus selective field-family packet and cost projection;
- contrast-aware manifest and deterministic selective assembly.
- broad/v3 Batch execution for a first 500-document strict
  classification-ready candidate base.

The next step is to expose the first 500 candidate records through a read-only
MCP prototype for medical-team demonstration and human-review recruitment.
Selective-v4 optimization remains a future optimization path, not an MVP
blocker.

1. Freeze the v4 selective work as documented architecture findings and future
   optimization.
2. Preserve the 500-document broad/v3 Batch tranche as the first local
   candidate base.
3. Build a local read-only retrieval index over candidate records, source
   identity, evidence spans, uncertainty, and provenance.
4. Implement a read-only MCP surface with structured filters and study-detail
   inspection.
5. Prepare medical-team demo journeys and reviewer-facing exports for targeted
   human review.
6. Continue remaining strict-corpus Batch classification in the background only
   with explicit maintainer authorization and sequential enqueued-token-safe
   chunks.
7. Continue field-scoped validation where it directly improves reviewer
    workflows or MCP retrieval quality.

## Next: Bounded Scale

1. Continue the remaining strict-corpus candidate batches only after the
   maintainer confirms budget and priority.
2. Use sequential chunks sized by estimated enqueued tokens; the current safe
   default is about 150 records per submitted Batch.
3. Measure quality by field family, condition, study type, source strategy, and
   source quality.
4. Test broad-recall versus high-confidence retrieval behavior.
5. Keep cost, failure handling, and repair provenance visible.
6. Preserve resumable, idempotent batch execution.

## Next: Continuous Source Growth

1. Continue explicit-window PubMed discovery.
2. Deduplicate canonical documents across windows.
3. Prioritize direct cannabinoid focus.
4. Enrich source access through official and lawful routes.
5. Keep invalid payload, source triage, and identity/focus queues separate.
6. Publish source-intelligence snapshots when licensing permits.

## Next: Read-Only Retrieval

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

- the 500-document Batch tranche fits the maintainer-approved cost guardrail;
- execution is resumable, idempotent, and constrained by enqueued-token guards;
- strict validation and retry/repair policy are measured;
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
