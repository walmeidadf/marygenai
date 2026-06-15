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

- `study_design_category`: one of `systematic_review`, `meta_analysis`,
  `randomized_controlled_trial`, `clinical_trial`, `observational_human`,
  `case_report_or_series`, `animal_in_vivo`, `in_vitro`, `mechanistic_review`,
  `narrative_review`, `other`, `cannot_determine`;
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

## First POC Sample

The first POC should classify a stratified sample, not the whole corpus.

Recommended size:

- 120 documents for the first full prompt/schema validation;
- optional 30-document smoke test before the 120-document run.

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
- disagreement with legacy study type, if the field is available.

The POC should not mutate SQLite or mark records as reviewed.

## Next Sequence

1. Implement a classification corpus rollup command.
2. Add a strict Pydantic schema for candidate classification outputs.
3. Generate the first corpus rollup from current local acquisition artifacts.
4. Produce a 30-document smoke-test sample packet.
5. Run one model/prompt over the smoke test.
6. Refine prompts and schema only if validation or evidence grounding fails.
7. Run a 120-document stratified classification POC.
8. Summarize quality, cost, latency, and classification distributions.
9. Decide whether to run a larger batch or first add PubMed-discovery expansion.
10. Design a read-only MCP surface over source-ready and candidate-classified
    documents after the classification output shape stabilizes.

## Safety Boundary

Candidate classifications are scientific retrieval and curation aids. They are
not medical advice, treatment recommendations, or reviewed clinical conclusions.
