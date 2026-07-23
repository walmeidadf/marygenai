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
- contrast-aware manifest and deterministic selective assembly;
- broad/v3 Batch execution for all 3,149 strict classification-ready documents.

The 3,149 valid candidate records are exposed through an isolated local
read-only index and MCP stdio prototype. The next product step is source-routing
and identity remediation for
the conflict-heavy final offset, followed by medical-team demonstration,
physician-authored acceptance testing, and human-review recruitment.
Selective-v4 optimization remains a future optimization path, not an MVP
blocker.

1. Freeze the v4 selective work as documented architecture findings and future
   optimization.
2. Preserve the completed broad/v3 strict corpus as the local candidate base.
3. Preserve and rebuild the implemented local index from ignored candidate,
   corpus, and evaluation artifacts.
4. Validate MCP search, detail, facets, capabilities, and trust language with
   physician-authored questions.
5. Prepare medical-team demo journeys and reviewer-facing exports for targeted
   human review.
6. Preserve the completed one-document targeted-rerun provenance.
7. Continue field-scoped validation where it directly improves reviewer
   workflows or MCP retrieval quality.
8. Audit and repair source routing for final-offset documents with explicit
   identifier conflicts before physician-facing use.

## Next: Bounded Scale

1. Resolve source-identity conflicts before expanding beyond the strict corpus.
2. Apply completed identity adjudications only through a separate deterministic
   and explicitly authorized workflow.
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

1. Extend the implemented MCP contract from strict filter groups to required,
   preferred, and excluded dimensions with explicit query diagnostics.
2. Add structured filters over pathology, anatomy, organ system,
   cannabinoid and role, study type, population, geography, publication period,
   outcome, source readiness, and confidence.
3. Preserve the existing evidence spans, source identity, provenance, grounding
   worklists, review state, and trust level as the contract evolves.
4. Add lexical and ontology-aware retrieval before introducing vector search.
5. Evaluate hybrid retrieval and ranking with realistic physician queries.
6. Evaluate related studies, citations, references, and terminology resolution
   as separate future tools.

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
