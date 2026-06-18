# Classification Dataset And Contract

## Purpose

Classification adds structured retrieval metadata to source-ready scientific
documents. It helps downstream users and AI assistants filter, rank, and inspect
studies. It does not determine clinical truth.

## Corpus Rollup

The official command is:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
```

It reads ignored local artifacts, deduplicates by `document_id`, and must not
mutate SQLite, review queues, decisions, or reviewed knowledge.

Outputs:

```text
data/normalized/classification_corpus/<run_id>_classification_corpus_records.jsonl
data/normalized/classification_corpus/<run_id>_classification_corpus_summary.json
data/normalized/classification_runs/<run_id>_classification_sample_records.jsonl
data/normalized/classification_runs/<run_id>_classification_sample_summary.json
```

Each corpus record should preserve:

- document identity, title, year, PMID, PMCID, DOI, and canonical URL;
- legacy traceability and normalized English legacy context when available;
- condition, organ-system, and cannabinoid labels;
- source strategy, URL, text path, raw payload path, and content quality;
- source-ready and classification-ready state;
- dataset split, trust level, and provenance.

## Candidate Classification Schema

Current schema:

```text
candidate_study_classification.v2
```

Required identity and provenance:

- `classification_id`;
- `document_id`;
- `classification_run_id`;
- `schema_version`;
- `extractor_name` and `extractor_version`;
- `model_provider` and `model_name`;
- `prompt_version`;
- `source_text_path` and `source_text_sha256`;
- `created_at`;
- run and source provenance.

Retrieval fields:

- `study_design_category`;
- `evidence_context`;
- `medical_conditions`;
- `cannabinoids_or_exposures`;
- `intervention_or_exposure_role`;
- `population_or_model`;
- `outcome_domains`;
- `overall_direction`;
- `classification_confidence`.

Evidence and uncertainty:

- `evidence_spans`;
- `supporting_sections`;
- `missing_or_uncertain_fields`;
- `warnings`;
- `requires_human_review=true`;
- `review_state=needs_review`.

## Study Design Domain

The principal field uses the normalized English legacy-compatible domain:

- `meta_analysis`;
- `clinical_meta_analysis`;
- `clinical_trial`;
- `double_blind_clinical_trial`;
- `animal_study`;
- `laboratory_study`;
- `other`;
- `cannot_determine`.

This field is primarily a retrieval filter. More specific labels such as case
report, survey, observational study, narrative review, or mechanistic review
should become separate subtype metadata instead of replacing the principal
comparison axis.

## Confidence Semantics

`classification_confidence` is currently a model-declared categorical assessment:

- `high`;
- `medium`;
- `low`.

It is not a calibrated probability and must not be described as one.

Future retrieval confidence should be a separately computed field combining
source and pipeline signals. It must remain distinct from:

- the model's self-assessment;
- scientific evidence hierarchy;
- clinical effect certainty;
- human review status.

## Uncertainty Semantics

`missing_or_uncertain_fields` should contain canonical field names only. Detailed
rationale belongs in warnings or a future structured uncertainty object.

For list fields, absence of a defensible label should produce an empty list and
the field name in uncertainty. `cannot_determine` should not be inserted into a
list enum unless the schema explicitly supports it.

Declared uncertainty is acceptable when it reflects science or source
limitations. Invalid enum values, inconsistent field usage, or avoidable prompt
ambiguity are correctable defects.

## Evaluation

### Technical Validity

- provider success;
- valid JSON;
- strict Pydantic pass rate;
- retries and errors;
- token use, cost, and latency;
- output and provenance completeness.

### Retrieval Utility

- evidence-span presence;
- coverage of filterable fields;
- broad-recall behavior under uncertainty;
- high-confidence ranking behavior;
- source traceability;
- condition, cannabinoid, study-type, and outcome coverage.

### Inference Quality

- exact and compatible agreement with normalized English legacy context;
- source-supported disagreements;
- unsupported evidence or labels;
- systematic errors by source, type, or condition;
- uncertainty precision;
- confidence calibration.

Legacy comparison uses normalized English context first. Portuguese fields remain
fallback and traceability only.

## Provider Validation Results

Current bounded tests favor OpenAI `gpt-5.4-mini` with:

- `max_source_chars=6000`;
- `max_completion_tokens=3000`.

The 2026-06-18 100-document schema-v2 run produced:

- 100/100 successful HTTP responses;
- no retries;
- 97/100 strict-valid classification records;
- evidence spans for 97/97 valid records;
- 90/97 exact principal study-design matches with English legacy context;
- no result-direction opposites under the current broad comparison;
- three validation failures caused by unsupported `outcome_domains` values.

Estimated cost was about USD 0.92, or USD 0.0092 per input document at the pricing
used for the estimate.

The run supports further development but exposes known work before mass
classification:

1. define or map cognition-related outcomes;
2. keep `cannot_determine` out of unsupported list enums;
3. improve `other` and future subtype handling for surveys, case reports, and
   observational designs;
4. enforce field-only uncertainty entries;
5. add repeatable evaluation instead of ad hoc analysis.

## Scaling Sequence

1. Correct known schema and prompt defects.
2. Re-run affected failures and disagreement records.
3. Add an official evaluation command.
4. Test retrieval behavior with representative physician questions.
5. Run a larger stratified batch.
6. Add resumable batch execution before full-corpus classification.

## Safety Boundary

Classification artifacts are candidate evidence. They are retrieval and curation
aids, not medical advice, reviewed knowledge, or treatment recommendations.
