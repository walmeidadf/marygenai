# Roadmap

## Product Direction

MaryGenAI is building a source-intelligence and candidate-classification layer
that helps physicians, researchers, and AI assistants find and inspect studies
about cannabinoid medicine.

The first external surface is the deployed read-only MCP pilot. Human review
remains a higher trust layer, but broad manual curation is not a prerequisite
for useful candidate retrieval.

## Now: Physician Pilot And Feedback

Completed in the v4 preparation cycle:

- patient-oriented data dictionary and classification architecture;
- downloaded-corpus profiling and execution-universe correction;
- frozen 12-document cross-domain validation sample;
- deterministic metadata/parser baseline with evidence candidates;
- initial parser-versus-legacy guardrail comparison;
- broad-v4 versus selective field-family packet and cost projection;
- contrast-aware manifest and deterministic selective assembly;
- broad/v3 Batch execution for all 3,149 strict classification-ready documents.

The 3,149 valid candidate records are exposed through an isolated read-only
index and a remote AWS MCP pilot. The custom domain has passed end-to-end hosted
ChatGPT and Claude connector tests. The next product step is a controlled
physician demonstration and an acceptance benchmark that will decide which MCP,
source-growth, and enrichment changes matter first. Selective-v4 optimization
remains a future path, not an MVP blocker.

1. Run the physician demonstration without patient-identifying information.
2. Record the specialty, question, effective query, opened sources, usefulness,
   false positives, false exclusions, and missing dimensions.
3. Convert the highest-value questions into repeatable acceptance cases.
4. Validate candidate wording, zero-result scope, access links, and detail-first
   evidence claims across supported hosts.
5. Prioritize retrieval, discovery, and enrichment changes from observed user
   value rather than from schema completeness alone.

## Next: MCP Retrieval Improvements

1. Add required, preferred, and excluded query dimensions with diagnostics.
2. Add explicit publication-date sorting and distinguish online, issue, and
   indexed dates.
3. Improve direct-versus-tangential matching without treating rank as evidence
   strength.
4. Add versioned terminology aliases and ontology-aware expansion before vector
   search.
5. Evaluate study comparison, related studies, citations, and references as
   separate tools.

## Next: Continuous Source Growth

1. Continue explicit-window PubMed discovery.
2. Deduplicate canonical documents across windows.
3. Prioritize direct cannabinoid focus.
4. Enrich source access through official and lawful routes.
5. Keep invalid payload, source triage, and identity/focus queues separate.
6. Publish source-intelligence snapshots when licensing permits.

Each refresh should classify only newly eligible or intentionally changed
records, rebuild an immutable content-addressed index, validate it locally, and
promote it to the remote pilot without mutating SQLite or review state.

## Next: Enrichment And Quality

1. Reconcile bibliographic publication type and publication-date semantics with
   authoritative metadata while preserving candidate classification separately.
2. Resolve or expose DOI, PMID, and PMCID conflicts through explicit provenance
   and authorized adjudication.
3. Validate physician-facing URL health and access status.
4. Add structured pathology, anatomy, organ system, population, geography,
   comparator, route, dose, outcome, and adverse-event fields where acceptance
   questions demonstrate value.
5. Preserve field-level evidence, uncertainty, source identity, review state,
   and trust level as the contract evolves.

## Later: Reviewed Public Baseline

1. Define promotion from candidate evidence to human-reviewed knowledge.
2. Export reviewed snapshots without exposing private legacy inputs.
3. Preserve reviewer, original value, reviewed value, rationale, timestamp,
   ontology version, and extractor version.
4. Let public users bootstrap from reviewed snapshots.

## Mass Classification Gate Achieved

The completed strict-corpus campaign demonstrated that:

- the 500-document Batch tranche fits the maintainer-approved cost guardrail;
- execution is resumable, idempotent, and constrained by enqueued-token guards;
- strict validation and retry/repair policy are measured;
- retrieval usefulness is demonstrated, not only label agreement;
- confidence and uncertainty have stable semantics;
- source, evidence, model, prompt, and cost provenance are complete;
- candidate output remains isolated from reviewed knowledge.

## MCP Pilot Gate Achieved

The deployed pilot demonstrated that:

- candidate records have a stable retrieval schema;
- filtering dimensions are useful on real questions;
- evidence and source links are consistently returned;
- trust levels and uncertainty are unambiguous;
- retrieval cannot be mistaken for medical advice.
