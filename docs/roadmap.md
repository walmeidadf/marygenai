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

The next step is to stop treating selective-v4 optimization as an MVP blocker.
Use the broad `candidate_study_classification.v3` contract for the first
provider-backed candidate base, then expose it through a read-only MCP
prototype for medical-team demonstration and human-review recruitment.

1. Freeze the v4 selective work as documented architecture findings and future
   optimization.
2. Build a 50- to 100-document broad/v3 canary from strict classification-ready
   records.
3. Run the canary only with explicit maintainer authorization and available API
   balance guardrails.
4. Evaluate real usage, cost, strict schema validity, retry behavior, latency,
   evidence grounding, and field coverage.
5. Project full strict-corpus and broader-source-ready costs from measured
   canary usage, not only from prompt estimates.
6. After maintainer approval and funding, run the first strict-corpus candidate
   classification batch.
7. Build a local read-only retrieval index over candidate records, source
   identity, evidence spans, uncertainty, and provenance.
8. Implement a read-only MCP surface with structured filters and study-detail
   inspection.
9. Prepare medical-team demo journeys and reviewer-facing exports for targeted
   human review.
10. Continue field-scoped validation where it directly improves reviewer
    workflows or MCP retrieval quality.

## Next: Bounded Scale

1. Run the strict-corpus candidate batch only after the canary passes technical
   and cost gates.
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

- the 50- to 100-document canary fits the maintainer-approved cost guardrail;
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
