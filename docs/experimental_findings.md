# Experimental Findings

This document preserves durable findings from historical source and model
experiments. The original standalone POC implementations are no longer part of
the supported public interface. Their Git history remains available, and the
maintainer may keep local copies under ignored `temp/project_archive/`.

## Publication Identity And Discovery

- PubMed is the primary publication identity and discovery source.
- A validated sample normalized 790 PubMed records across eight query families.
- DOI and abstract coverage were strong; PMCID coverage was useful but partial.
- Monthly PubMed windows can overlap by PMID, so source-window counts must remain
  separate from unique document counts.
- `cannabinoid_focus` is a better primary prioritization signal than citation
  count or general influence.

## Private Bootstrap

- The maintainer-local legacy bootstrap contains thousands of curated records
  and is a strong validation anchor.
- Direct PMID, PMCID, or DOI identity was available for 6,140 of 7,347 legacy
  publication rows in the initial reconciliation.
- Normalized English legacy context is the preferred baseline for classification
  prompts and evaluation.
- Legacy agreement is informative but not absolute. Source-supported
  disagreements should be retained for review.

## Source Availability

- Metadata availability is not equivalent to classification-ready source text.
- Persisted HTTP success is not proof of valid article content.
- PMC OAI-PMH was the strongest official full-text route in the legacy-core
  acquisition campaign.
- Digital PDF extraction is a valid first-class classification source when the
  text layer passes quality gates.
- OCR is a residual route for scanned or poor-text-layer PDFs.
- NCBI ELink and OpenAlex are access and identity augmentation sources, not
  direct full-text sources.
- The June 2026 legacy-core campaign produced about 3,149 strict
  classification-ready documents and about 3,374 broader source-ready documents
  after deduplication.

## Classification

- Strict Pydantic validation is effective at exposing schema and prompt defects.
- Candidate classifications should preserve evidence spans, source hashes,
  model, prompt, schema, usage, latency, warnings, and uncertainty.
- The principal study-design field should use the English legacy-compatible
  domain. More granular interpretation belongs in separate subtype fields.
- Same-document tests favored `gpt-5.4-mini` over `gpt-4.1` on cost and over
  `gpt-5.4-nano` on schema reliability for the tested prompt.
- A 100-document schema-v2 run on 2026-06-18 produced 100 successful provider
  responses, 97 strict-valid records, and evidence spans for every valid record.
- The three validation failures shared a correctable `outcome_domains` enum
  issue rather than a provider or source failure.
- Cognition appeared consistently enough in the failed records to justify a
  first-class retrieval domain rather than lossy mapping to efficacy, safety, or
  mechanism.
- Among valid records, 90 of 97 principal study-design labels exactly matched
  the normalized English legacy type.
- Declared uncertainty was common, but technical fields were no longer
  incorrectly reported as scientific uncertainty.
- Six valid records still used free-text uncertainty entries and three omitted
  required field-scoped uncertainty markers. Strict schema-v3 field names expose
  these as contract defects instead of silently interpreting them.
- A targeted schema-v3 rerun on 2026-06-18 covered the three prior validation
  failures and seven prior study-design disagreements. It produced 10/10 HTTP
  successes, 10/10 valid JSON responses, 10/10 strict-valid records, no retries,
  and evidence spans for every record.
- All three prior `outcome_domains` failures became valid. Cognition appeared in
  five of the ten records, confirming that it is useful as a first-class
  retrieval domain.
- Among the seven original study-design disagreements, one became an exact
  English legacy match. Five used `other` with source-explicit subtypes
  (`pilot_study`, `observational_study`, `survey`, or
  `case_report_or_series`), and one used `clinical_meta_analysis` where the
  English legacy reference used the broader `Meta-analysis`.
- The targeted run had 3/10 exact principal study-design matches and 8/10
  matches under a legacy-result direction proxy.
  Exact legacy agreement alone understates source fidelity when the legacy label
  conflicts with explicit document design wording.
- Deterministic inspection classified the seven study-design disagreements as
  six source-supported overrides and one compatible refinement. None remained an
  unresolved design disagreement requiring another run solely for study-design
  agreement.
- Two direction disagreements exposed a semantic ambiguity: `null` had been used
  for a dropout-rate meta-analysis and a veterinarian perception survey even
  though neither main question represented a null treatment effect. Prompt v4
  reserves `null` for evaluated effects or associations and uses
  `not_applicable` for descriptive outcomes.
- The legacy-result direction proxy is not a trusted direction ground truth.
  English legacy `Positive`, `Negative`, and `Inconclusive` values do not
  consistently mean beneficial, harmful, null, or not applicable.
- Prompt v4 was tested on the seven inspected design disagreements. It produced
  7/7 strict-valid records and corrected the veterinarian survey from `null` to
  `not_applicable`. The dropout-rate meta-analysis retained `null` because the
  source explicitly reported tested moderator associations with no effect.
- The prompt-v4 run required two retries for one survey record after a connection
  reset and read timeout. All seven records ultimately succeeded. Total latency
  was about 234 seconds, dominated by the retried record, and estimated cost was
  about USD 0.0603.
- Prompt v4 introduced one structured inconsistency: a source-explicit scoping
  review was labeled `systematic_review` while its warning said scoping review.
  Prompt v5 requires explicit source subtype wording to control the subtype and
  forbids warnings from contradicting structured fields.
- The one-document prompt-v5 validation produced
  `clinical_meta_analysis + scoping_review`, `overall_direction=mixed`, no
  retries, and no unresolved disagreement. Estimated cost was about USD 0.0091.
- The final seven-record interpretation therefore contains two exact principal
  legacy-compatible design matches, five source-supported overrides with
  explicit subtypes, and no unresolved study-design disagreements. All 31
  evidence spans passed extraction-tolerant grounding.
- Model-declared confidence showed limited but non-zero variation in the final
  set: six `medium` records and one `high` survey record. A computed retrieval
  confidence remains necessary.
- `retrieval_confidence.v1` was tested without new provider calls on the
  10-record targeted run, the 7-record prompt-v4 run, the one-record prompt-v5
  correction, and synthetic contrast cases.
- On the 10-record run, model confidence was uniformly `medium`, while computed
  confidence produced four `high` and six `medium` records with scores from
  0.8630 to 1.0000. This supports independence from model self-assessment.
- Declared uncertainty produced lower high-precision scores than broad-recall
  scores, preserving uncertain records for recall while lowering narrow-query
  rank.
- The inconsistent prompt-v4 scoping-review record scored 0.8340 (`medium`);
  its coherent prompt-v5 replacement scored 0.9700 (`high`). This supports the
  metadata-consistency penalty.
- Synthetic contrasts confirmed that strict source readiness outranks broader
  source readiness when other signals are held constant, and that grounded,
  consistent records outrank records with weak grounding, incomplete filters,
  retries, and unresolved contradictions.
- The 100-document historical run contained one real broader-source-ready valid
  record. After removing a schema-v2 subtype penalty that did not apply to that
  historical contract, it scored 0.8875 (`medium`), versus a run median of
  0.9000. Its broad-recall score was 0.9325 and high-precision score was 0.8425.
  This supports a modest source-readiness penalty rather than excluding useful
  broader-source records.
- A direct invariance test confirmed that changing model-declared confidence
  from `low` to `high` does not change the computed score.
- One initial contradiction heuristic was rejected: scanning all evidence text
  confused a systematic review of observational studies with an observational
  study. The corrected rule uses explicit document-title design phrases with
  precedence.
- The first band threshold was also rejected as too permissive: a `high`
  threshold of 0.85 labeled nine of ten targeted records high. V1 now requires
  0.95 for `high` and 0.75 for `medium`.
- The run produced 40 evidence spans. Seventeen were exact normalized
  substrings; all 40 passed token-bigram grounding with extraction-artifact
  tolerance, leaving no spans for grounding review. Extracted PDFs and page text
  can interleave author names, headers, or journal metadata inside otherwise
  copied sentences, so exact and tolerant grounding must be reported separately.
- All ten records declared `classification_confidence=medium`. This categorical
  self-assessment did not discriminate among the targeted cases and remains
  unsuitable as a calibrated score.
- The targeted run used 48,239 input tokens and 10,819 output tokens. At the
  standard `gpt-5.4-mini` rates used on 2026-06-18, estimated cost was about
  USD 0.0849.

## Product Interpretation

Classification exists to improve retrieval, not to replace scientific judgment.
A declared, evidence-backed uncertainty can remain useful. Known technical
defects should be corrected. Evaluation must therefore separate technical
validity, retrieval utility, and inference quality.

## Decisions Promoted Into The Product

- Supported workflows live under `src/marygenai/` and the `marygenai` CLI.
- Historical experiment code is not a supported public API.
- Generated artifacts remain ignored and auditable.
- AI output remains candidate evidence.
- Retrieval confidence must not be confused with clinical evidence strength.
- Read-only MCP retrieval is the intended first external integration surface.
