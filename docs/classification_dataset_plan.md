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

## PubMed 2024+ Canary Preparation

The provider-free command is:

```bash
uv run marygenai classification-corpus prepare-pubmed-canary \
  --target-size 100 \
  --corpus-version pubmed_2024plus_canary.v1 \
  --max-source-chars 12000 \
  --target-model-provider openai \
  --target-model-name gpt-5.4-mini
```

It opens SQLite in read-only/query-only mode, audits every locally persisted
open XML/HTML artifact, deduplicates by `document_id`, selects deterministically
by priority, study-design rank, year, and document ID, freezes a content-stable
manifest and classification corpus, writes per-document exclusions, extracts
hash-bound local source text, and builds prompt packets. It makes no network or
provider call.

The source gate requires:

- a 2024+ direct-title-or-indexed cannabinoid candidate;
- `needs_review` state and no unresolved manual identity requirement;
- a local open XML/HTML artifact whose stored SHA-256 matches the file;
- exact normalized title identity plus matching PMID or DOI in the artifact;
- at least 4,000 extracted characters, two scientific-section signals, and one
  cannabinoid-term signal.

The ignored outputs are written under
`data/normalized/pubmed_canary/`,
`data/processed/pubmed_canary/`, and
`data/normalized/classification_runs/`. Frozen manifest or corpus content cannot
be silently overwritten under the same corpus version. Selected inputs remain
`source_text_available`; future provider output must remain
`ai_classified_candidate`, `needs_review`, and human-review-required.

The first local v1 run selected eight records from a target of 100. It reported
the shortfall and identity/source exclusions rather than weakening the gate.

The authorized v1 provider smoke test produced 8/8 strict-valid candidate
records and 28/28 extraction-tolerant grounded evidence spans, with zero errors,
retries, or rerun documents. It used 42,930 prompt tokens and 7,380 completion
tokens. No legacy English reference matched these new records, so independent
inference agreement remains unmeasured.

Build a read-only identity-repair overlay for the highest-priority source
failures:

```bash
uv run marygenai classification-corpus repair-pubmed-source-identities \
  --target-size 150 \
  --no-apply
```

The command selects direct-focus, 2024+ candidates with a local open artifact
that failed artifact identity verification. It queries PubMed only by the
existing candidate PMID, stores hash-bound raw EFetch XML, compares official
title, year, PMCID, DOI, and canonical URL, and writes ignored repair records
and a PMC reenrichment worklist. `--apply` is deliberately rejected. The command
does not call an LLM or mutate SQLite, review queues, review decisions, or
reviewed knowledge.

The first 150-record repair run resolved 150/150 PubMed records with zero
errors. Titles and DOIs agreed throughout, all persisted PMCIDs changed, and 149
records received a corrected official PMCID suitable for bounded reenrichment.

## Candidate Classification Schema

Current schema:

```text
candidate_study_classification.v3
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
- `study_design_subtype`;
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

The current schema remains supported for existing experiments, but it is not the
complete target MCP contract. The planned v4 contract and field definitions are
documented in [Candidate Classification V4 Plan](classification_v4_plan.md) and
[Classification Data Dictionary](classification_data_dictionary.md).

The principal known gaps are structured pathology, symptoms, anatomy and organ
systems, study geography, study period, demographics, sample size and scope,
route, comparator, and entity-level cannabinoid role.

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
belong in `study_design_subtype` instead of replacing the principal comparison
axis. Surveys, case reports or series, and observational studies that do not fit
the legacy-compatible principal categories use `study_design_category=other`.

## Outcome Domain

`cognition` is an official retrieval domain for memory, attention, executive
function, neurocognitive performance, and cognitive impairment. Behavioral
outcomes are not automatically cognition and should map only when the source
supports that interpretation.

`cannot_determine` is not valid inside `outcome_domains` or another list enum.
When no defensible list value is available, the list is empty and its canonical
field name appears in `missing_or_uncertain_fields`.

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

The first evaluator-only implementation is `retrieval_confidence.v1`. It does
not change the candidate-classification schema. It combines deterministic,
auditable components:

- technical integrity: required provenance and final provider execution;
- source quality: strict readiness, source length, and scientific-section
  signal;
- evidence grounding: exact spans and extraction-tolerant spans;
- metadata consistency: exact match, compatible refinement, source-supported
  override, or unresolved disagreement;
- retrieval completeness: populated filter fields.

Weights are versioned in code. Model-declared `classification_confidence` is
reported alongside the computed score but is not an input.

The evaluator writes one record per document with:

- a base heuristic score and `high`, `medium`, or `low` band;
- a less punitive `broad_recall_score`;
- a more uncertainty-sensitive `high_precision_score`;
- component values, weights, uncertainty fields, and machine-readable reasons.

These scores are experimental ranking signals, not calibrated probabilities.
They remain outside reviewed knowledge and must not be interpreted as clinical
evidence strength.

## Overall Direction

`overall_direction` describes a source-supported effect or association relevant
to the study question:

- `beneficial`, `harmful`, or `mixed` require a directional effect or
  association;
- `null` means that an effect or association was evaluated and no meaningful
  difference or association was found;
- `not_applicable` is used for descriptive surveys, prevalence or rate
  estimates, knowledge or perception studies, methodological reports, and other
  records without a beneficial/harmful effect question;
- `cannot_determine` means a directional question exists but the available
  source is insufficient.

`null` must not be used as a generic neutral label for descriptive findings.

## Uncertainty Semantics

`missing_or_uncertain_fields` is a strict enum of canonical classification field
names. Detailed rationale belongs in `warnings`.

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

The downloaded corpus defines evaluation scale and provider cost. Legacy context
is a reference and guardrail, not a queue of documents to classify.

Field-scoped evaluation must expand beyond study design. Required v4 benchmark
families are:

- condition, pathology, symptom, anatomy, and organ system;
- cannabinoid identity and scientific role;
- population, demographics, species, and sample scope;
- publication and study time, geography, route, and comparator;
- study structure;
- outcomes, adverse events, and overall direction.

Efficiency must report deterministic coverage, LLM invocation rate, cost per
valid record, and cost per correct evidence-backed field.

## Study-Design Validation Benchmark

The official local candidate builder is:

```bash
uv run marygenai classification build-validation-benchmark --sample-size 48
```

It selects source-ready records using explicit title phrases and round-robin
stratification across review, trial, animal, laboratory, survey, case,
observational, and pilot designs. Rule precedence prevents a systematic review
of trials from being selected as a trial. Animal or laboratory context takes
precedence over trial wording, while `pilot_study` may refine an explicit
clinical-trial category as a subtype.

Each candidate preserves source identity and hash, title evidence, normalized
English legacy context, exact or compatible comparison, and empty human-review
fields. The artifacts remain ignored files with `review_state=needs_review`.
They are a review worklist, not reviewed knowledge, and the command does not
call an LLM or mutate SQLite.

Human-reviewed labels are required before this set can be used to train or
calibrate auxiliary classifiers. Until then, title rules and legacy agreement
are candidate signals only.

### Development And Holdout Separation

The first development benchmark contains 21 reviewed records selected from
rule-versus-legacy disagreements. Its purpose is diagnosis and rule development,
not unbiased corpus-wide accuracy estimation.

Review decisions use `study_design_benchmark_review_decision.v1`. Each
append-only record preserves:

- the candidate and reviewed category/subtype;
- `confirmed` or `corrected` decision semantics;
- short source evidence;
- source path and hash;
- reviewer, review method, timestamp, and rationale;
- identity warnings and provenance.

For maintainer-assisted review, the current convention is:

```text
reviewer=marygenai:maintainer
review_method=human_confirmed_with_ai_assistance
```

This identifies the platform-assisted workflow without misrepresenting the
decision as autonomous model review.

The frozen holdout contains 40 non-overlapping candidates:

- 20 exact rule/legacy agreements;
- 10 new rule/legacy disagreements;
- five records without normalized English legacy reference;
- five titles matching multiple deterministic rules.

The no-reference pool currently contains only five eligible records, all in
canine contexts. That limitation must remain visible in interpretation. Holdout
labels are not inspected until the next deterministic rule version is frozen.

### Deterministic Study-Design Rule V2

`study_design_rules.v2` starts with the title-rule candidate and reads a
hash-verified source prefix. It changes a label only when explicit deterministic
signals are present:

- a clinical trial becomes `double_blind_clinical_trial` when the source
  explicitly states double-blind or double-masked design;
- a pilot becomes `clinical_trial + pilot_study` when the source explicitly
  describes randomized assignment, an interventional trial, or an open-label
  treatment study;
- an explicitly observational, non-randomized pilot remains
  `other + pilot_study`;
- a title containing `survey` becomes `other + observational_study` when the
  primary method is explicitly an ecological state-level analysis joining
  datasets and running regressions.

The rule does not infer missing blinding from placebo control alone. It preserves
the original candidate, applied rules, source-character limit, source-hash
verification, and run ID in provenance.

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

Schema v3 and the official evaluator address the localized contract defects:

1. cognition is an official outcome domain;
2. `cannot_determine` remains outside list enums;
3. `other` works with subtype handling for surveys, case reports, and
   observational designs;
4. uncertainty entries are strict canonical field names;
5. evaluation is repeatable rather than ad hoc.

The official local evaluator is:

```bash
uv run marygenai classification evaluate
```

It writes ignored reports under
`data/normalized/classification_evaluations/`, including metrics grouped by
technical validity, retrieval utility, and inference quality; study-design
disagreements; exact and extraction-tolerant evidence grounding checks; documents
requiring rerun; and a targeted rerun input.

## Targeted Schema-V3 Validation

The 2026-06-18 targeted rerun used the three schema-v2 failures and seven
study-design disagreements:

- 10/10 provider responses and valid JSON;
- 10/10 strict-valid schema-v3 records;
- no retries;
- 10/10 records with evidence spans;
- 40/40 evidence spans grounded after extraction-artifact tolerance;
- 3/10 exact principal study-design matches with English legacy context;
- 8/10 matches under the legacy-result direction proxy;
- all three prior outcome-domain failures corrected;
- estimated cost about USD 0.0849.

The remaining seven study-design disagreements should not be treated as seven
automatic model errors. Six are source-supported overrides with explicit
subtypes, and one is a compatible refinement from `meta_analysis` to
`clinical_meta_analysis`. These records remain candidate evidence for
inspection.

The legacy-result direction comparison is a heuristic proxy only.
`Positive`, `Negative`, and `Inconclusive` do not consistently encode
beneficial, harmful, null, or not-applicable clinical direction. It must not be
used as a calibrated inference-quality score.

Prompt-v4 and prompt-v5 follow-up reduced the seven inspected conflicts to:

- two exact principal legacy-compatible design matches;
- five source-supported overrides with explicit subtypes;
- zero unresolved study-design disagreements.

The final seven-record interpretation has 31/31 evidence spans grounded with
extraction tolerance. The two follow-up runs cost about USD 0.0694 combined.

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
