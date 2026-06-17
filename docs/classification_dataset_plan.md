# Classification Dataset Plan

This document defines the next MaryGenAI workstream after the June 2026 source
acquisition campaign. The goal is not to run broad classification immediately.
The goal is to freeze the classification substrate, define the output schema, and
run a small stratified candidate-classification POC over real source text.

## Product Direction

MaryGenAI is now framed as a cannabinoid scientific source-intelligence and
candidate-classification engine. The first useful product is a reproducible
pipeline that can:

- discover scientific documents;
- resolve publication identity;
- enrich metadata and access signals;
- acquire source text when allowed;
- determine whether a document is classification-ready;
- generate AI classification candidates with provenance;
- later expose discovered, enriched, source-ready, and candidate-classified
  documents through read-only retrieval surfaces, potentially an MCP server.

Human review remains the highest trust layer, but large-scale human curation is
not assumed for the next milestone. AI outputs are candidate evidence only.

## Working Dataset

The first classification dataset should be a deduplicated rollup of the current
legacy-core source acquisition results.

Primary dataset:

- universe: operational legacy-core documents;
- count: 6,491 documents;
- strict classification-ready count: about 3,149 documents;
- source-ready count without requiring the simple cannabinoid term detector:
  about 3,374 documents.

Use the strict classification-ready set as the first default dataset. Keep the
broader source-ready set as a secondary queue for detector tuning and prompt
validation.

The corpus rollup should read ignored local artifacts only and must not mutate
SQLite, review queues, review decisions, or reviewed knowledge.

Recommended output path:

```text
data/normalized/classification_corpus/<run_id>_classification_corpus_records.jsonl
data/normalized/classification_corpus/<run_id>_classification_corpus_summary.json
```

## Corpus Rollup Fields

Each rollup record should include:

- `document_id`;
- `legacy_study_id`;
- `primary_title`;
- `publication_year`;
- `pmid`;
- `pmcid`;
- `doi`;
- `canonical_url`;
- `legacy_study_type`;
- `legacy_result`;
- `legacy_type_of_study`;
- `legacy_study_result`;
- `legacy_key_findings`;
- `medical_condition_labels`;
- `organ_system_labels`;
- `cannabinoid_labels`;
- `source_strategy`;
- `source_url`;
- `source_text_path`;
- `raw_payload_path`;
- `extracted_text_chars`;
- `scientific_section_hit_count`;
- `cannabinoid_term_hit_count`;
- `source_ready`;
- `classification_ready`;
- `classification_dataset_split`;
- `trust_level`;
- `provenance`.

Recommended `trust_level` values:

- `source_discovered`;
- `metadata_enriched`;
- `source_text_available`;
- `ai_classified_candidate`;
- `human_reviewed`.

The initial rollup should assign source-ready records to
`source_text_available`, not `ai_classified_candidate`.

## Candidate Classification Schema

The first AI classification output should be coarse, provenance-heavy, and
designed for later review. It should avoid fields that require table extraction,
figure interpretation, or exact protocol reconstruction.

Recommended record identity fields:

- `classification_id`;
- `document_id`;
- `classification_run_id`;
- `schema_version`;
- `extractor_name`;
- `extractor_version`;
- `model_provider`;
- `model_name`;
- `prompt_version`;
- `source_text_path`;
- `source_text_sha256`;
- `created_at`.

Recommended classification fields:

- `study_design_category`: one of the English legacy study-type domain values
  `meta_analysis`, `clinical_meta_analysis`, `clinical_trial`,
  `double_blind_clinical_trial`, `animal_study`, `laboratory_study`, `other`,
  `cannot_determine`;
- `evidence_context`: one of `human_clinical`, `human_observational`,
  `animal_preclinical`, `in_vitro_or_cellular`, `review_or_synthesis`,
  `mixed`, `cannot_determine`;
- `medical_conditions`: candidate normalized labels and free-text labels;
- `cannabinoids_or_exposures`: candidate normalized labels and free-text labels;
- `intervention_or_exposure_role`: one of `therapeutic_intervention`,
  `recreational_or_nonmedical_exposure`, `endocannabinoid_system_mechanism`,
  `synthetic_or_pharmaceutical_cannabinoid`, `cannabis_use_or_dependence`,
  `cannot_determine`;
- `population_or_model`: short text plus category such as `adult_humans`,
  `pediatric_humans`, `animals`, `cells`, `mixed`, `cannot_determine`;
- `outcome_domains`: list of domains such as `efficacy`, `safety`,
  `adverse_events`, `biomarker`, `mechanism`, `pharmacokinetics`,
  `public_health`, `use_pattern`;
- `overall_direction`: one of `beneficial`, `harmful`, `mixed`, `null`,
  `not_applicable`, `cannot_determine`;
- `classification_confidence`: one of `high`, `medium`, `low`;
- `requires_human_review`: boolean, initially always true;
- `review_state`: initially `needs_review`.

Recommended evidence fields:

- `evidence_spans`: list of source snippets with `section`, `text`,
  `char_start`, `char_end` when available;
- `supporting_sections`;
- `missing_or_uncertain_fields`;
- `warnings`;
- `provenance`.

The first schema should require the model to return `cannot_determine` instead
of guessing when source text is insufficient.

The principal `study_design_category` field should stay aligned to the English
legacy `type_of_study` domain. Interpretive labels such as `narrative_review`,
`mechanistic_review`, `systematic_review`, `animal_in_vivo`, or `in_vitro` must
not replace the principal legacy-compatible category. If those distinctions are
useful later, add a separate subtype field instead of changing the main
comparison axis.

## First POC Sample

The first POC should classify a stratified sample, not the whole corpus.

Recommended size:

- 5 difficult documents for fast provider/schema validation;
- 30 documents for a model-comparison smoke test;
- 100 documents for the next cost, retry, and quality estimate before any
  corpus-scale classification run.

The earlier 120-document target is superseded by the 100-document gate. A
100-document run is large enough to expose enum mistakes, truncation, retry
rates, latency, and per-document token behavior while keeping spend bounded.

Recommended strata:

- condition coverage: pain, addiction/cannabis, epilepsy, anxiety, depression,
  psychosis, cancer, inflammation;
- study-type coverage: meta-analysis, animal study, laboratory study, clinical
  trial, double-blind clinical trial, clinical meta-analysis;
- source strategy coverage: PMC OAI-PMH, Unpaywall PDF, augmented links;
- source quality coverage: strict classification-ready and broader source-ready
  records.

Recommended sample output paths:

```text
data/normalized/classification_runs/<run_id>_classification_sample_records.jsonl
data/normalized/classification_runs/<run_id>_classification_sample_summary.json
data/normalized/classification_runs/<run_id>_classification_errors.jsonl
```

## Evaluation Metrics

The POC should measure:

- valid JSON rate;
- schema validation pass rate;
- `cannot_determine` rate by field;
- evidence span presence rate;
- unsupported evidence or hallucination flags;
- average input tokens and output tokens;
- cost estimate by provider/model;
- latency;
- provider errors and retries;
- classification distribution by condition and study type;
- disagreement with English legacy `type_of_study` and `study_result`, when the
  maintainer-local English legacy context is available.

Use normalized English legacy context as the preferred evaluation baseline.
Portuguese bootstrap fields such as `legacy_study_type` and `legacy_result` may
remain in corpus records for traceability and fallback, but model evaluation,
prompt construction, and reported classification comparisons should use
`data/normalized/legacy_english_context/` fields first when they can be matched
to a document.

The POC should not mutate SQLite or mark records as reviewed.

## Provider And Model Findings

The first provider-backed classification tests used the same source-ready
documents and strict Pydantic validation to compare models. Generated outputs
remain candidate evidence only.

Observed local POC results:

- `gpt-4.1` classified the 30-document smoke sample successfully after retrying
  five records with a larger completion-token budget. The clean 30-document
  estimate was about 168,658 tokens and about USD 0.60 at then-current pricing.
- `gpt-5.4-mini` passed the same five difficult documents with no errors, then
  classified the same 30-document smoke sample successfully after one retry.
  The clean 30-document estimate was about 166,315 tokens and about USD 0.28.
- `gpt-5.4-nano` was much cheaper, but failed two of five difficult documents by
  confusing `study_design_category` and `evidence_context`. It should not be the
  default classifier until prompt/schema hardening proves it can pass the same
  comparison set reliably.

Current default POC choice:

- provider: OpenAI;
- model: `gpt-5.4-mini`;
- `max_source_chars`: `6000`;
- `max_completion_tokens`: `3000`.

The prompt should explicitly reinforce enum discipline. In particular:

- `study_design_category` must use the English legacy study-type domain, not a
  free-form or PubMed-style publication subtype;
- `evidence_context` should use `review_or_synthesis` for review articles;
- `outcome_domains` must use only supported enum values. Unsupported domains
  such as cognition or behavior should be mapped only when the source text
  supports a supported domain, otherwise omitted or treated as uncertainty.

The project is not ready for an unattended full classification run yet. Before
mass classification, run the 100-document gate and summarize:

- valid JSON and strict Pydantic pass rates;
- retry rate and retry reasons;
- token and dollar cost per document;
- latency per document;
- distribution drift versus the 30-document `gpt-4.1` baseline;
- evidence-span presence and obvious grounding failures;
- source-quality and source-sufficiency failure modes.

## Next Sequence

1. Implement a classification corpus rollup command.
2. Add a strict Pydantic schema for candidate classification outputs.
3. Generate the first corpus rollup from current local acquisition artifacts.
4. Produce a 30-document smoke-test sample packet.
5. Run one model/prompt over the smoke test.
6. Compare `gpt-4.1`, `gpt-5.4-mini`, and cheaper alternatives on the same
   documents.
7. Use `gpt-5.4-mini` as the default next POC model and keep `gpt-5.4-nano`
   out of the default path until it passes the difficult comparison set.
8. Run a 100-document stratified classification POC.
9. Summarize quality, cost, latency, retry reasons, and classification
   distributions.
10. Decide whether to run a larger batch or first add PubMed-discovery expansion.
11. Design a read-only MCP surface over source-ready and candidate-classified
    documents after the classification output shape stabilizes.

## Safety Boundary

Candidate classifications are scientific retrieval and curation aids. They are
not medical advice, treatment recommendations, or reviewed clinical conclusions.
