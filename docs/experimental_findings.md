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
- The normalized English reference contains 7,360 deduplicated records, but this
  count does not define classification scale. The downloaded source-ready corpus
  defines provider volume and cost.
- Reference coverage is strong for publication year (100.0%), study location
  (99.7%), condition/pathology page association (96.6%), cannabinoids (88.4%),
  and organ-system page association (80.6%). Sample size is available for 35.1%,
  route for 43.0%, and structured adverse events for 2.4%.
- Publication year agreed in 6,488 of 6,490 canonical corpus/reference
  comparisons in the reproducible field profile. It is a strong metadata field,
  while study period remains a separate extraction problem.
- Condition and organ labels derived from page membership are useful bootstrap
  signals but may describe a page association rather than the document's
  principal question. They require field-scoped validation.

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
- A local TF-IDF classification experiment used 4,665 source-text documents
  after excluding the seven known source-versus-legacy conflicts. Logistic
  Regression reached 0.7856 accuracy and 0.7208 macro-F1 against normalized
  English legacy study type. Linear SVM reached 0.7792 accuracy and 0.6934
  macro-F1.
- The legacy-trained classical models failed as semantic validators on the
  conflict set. They confidently repeated `meta_analysis` for source-explicit
  pilot, case-report, observational, and survey records. The training domain also
  lacked a reliable `other` class. These models may be useful as a low-weight
  legacy-consistency signal, but they require a source-reviewed training set
  before they can validate study design.
- A local `cross-encoder/nli-deberta-v3-small` experiment tested atomic
  study-design hypotheses against selected title and design evidence spans. With
  short premises, it strongly supported pilot study, scoping review,
  meta-analysis, and survey hypotheses and contradicted several incorrect
  meta-analysis hypotheses.
- The same NLI model was not reliable as a gate. Case-report support was weaker
  than neutral, observational-study judgments were incorrect or neutral, and
  small hypothesis wording changes materially changed the result. NLI may
  contribute a calibrated semantic-support feature after template versioning
  and source-reviewed benchmarking; lack of entailment must not be interpreted
  automatically as contradiction.
- The first deterministic benchmark-candidate build found 663 title-explicit
  records but exposed substring-precedence errors, including a systematic review
  of randomized trials selected as a clinical trial. That rule set was rejected.
- The corrected builder found 771 title-explicit candidates and selected 48
  records across 11 design strata. The sample contained 22 exact normalized
  English legacy matches, five compatible
  `meta_analysis`/`clinical_meta_analysis` refinements, and 21 disagreements.
- The disagreements concentrate useful review cases: surveys, case reports,
  observational studies, pilot studies, and clinical-trial granularity. These
  remain candidate labels, not benchmark truth, until source review is recorded.
- Human-confirmed review closed all 21 selected legacy-disagreement records:
  13 deterministic title-rule candidates were confirmed and eight were
  corrected.
- On this conflict-enriched development set, title-rule category accuracy was
  14/21 (0.6667), subtype accuracy was 20/21 (0.9524), and exact
  category-plus-subtype accuracy was 13/21 (0.6190). Normalized English legacy
  category accuracy was 7/21 (0.3333).
- These values are diagnostic benchmark metrics, not corpus-wide accuracy. The
  dominant title-rule errors were four missed double-blind refinements, three
  intervention pilots mapped to `other`, and one ecological observational
  analysis mapped to `survey`.
- A 40-record holdout was frozen before rule-v2 implementation, excluding all
  21 development records. It contains 20 exact rule/legacy agreements, 10 new
  disagreements, five no-reference records, and five multi-rule titles. The
  no-reference stratum is limited to the five eligible canine records.
- Deterministic `study_design_rules.v2` improved exact category-plus-subtype
  accuracy on the 21-record development benchmark from 0.6190 to 0.9524.
  Category accuracy improved from 0.6667 to 0.9524, category macro-F1 from
  0.3011 to 0.9048, and subtype accuracy from 0.9524 to 1.0000.
- Rule v2 corrected all reviewed interventional-pilot and ecological-analysis
  errors and three of four reviewed double-blind refinements. The remaining
  double-blind label was supported by PubMed indexing but not by explicit text
  in the locally persisted source artifact.
- Applying rule v2 to the frozen 40-record holdout changed three categories,
  all through explicit source-level double-blind signals. No holdout labels were
  inspected during implementation or application.
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

Study-design work revealed useful architecture and evaluation patterns, but it
does not establish the quality of conditions, anatomy, cannabinoid roles,
population, geography, sample context, or outcomes. Those domains require
separate benchmarks before a patient-oriented MCP retrieval surface is ready.

- The first v4 metadata/parser baseline ran locally on 12 source-ready
  documents. It produced valid candidate artifacts for all 12 without an LLM.
- Source candidates were found for sample size in 8/12 records, route in 8/12,
  country mentions in 9/12, population in 12/12, and explicit design signals in
  9/12.
- The candidate set contained the legacy-reference sample size in 5/6 available
  cases and an overlapping route in 4/6 available cases.
- High candidate recall did not imply final-field precision. Primary studies and
  reviews contain multiple sample counts, cited species, background routes, and
  design phrases. Country mentions were frequently affiliations rather than
  explicit study geography.
- Deterministic parsing is therefore best used to locate compact field evidence
  and reduce LLM context. Semantic selection, relation classification, or
  explicit abstention remains necessary for ambiguous fields.
- The next controlled experiment is broad-record versus selective field-family
  semantic classification on the same 5 to 10 documents. Prompt packets, local
  schemas, token estimates, and projected cost inputs must be inspected before
  a provider call.
- The first local v4 packet comparison used the same eight frozen documents for
  both strategies and generated 40 schema-valid mocks without a provider call:
  eight broad packets and 32 selective family packets.
- The broad strategy requested 248 field instances with about 40,282 estimated
  input tokens and a 24,000-token aggregate completion ceiling. The selective
  strategy requested the same field instances with about 57,683 estimated input
  tokens and a 29,600-token aggregate completion ceiling.
- Under the configurable USD 0.75 input and USD 4.50 output per-million-token
  assumption, the maximum projected cost was USD 0.138211 for broad packets and
  USD 0.176462 for selective packets. These are ceiling estimates from a
  character heuristic, not provider usage.
- Repeated schemas and four calls per document outweighed selective context
  reduction in this first packet design. Selective-LLM is not inherently
  lower-cost; it needs call suppression or materially smaller response
  contracts.
- Three selective packets had no parser evidence candidates. The parser baseline
  does not yet produce direct clinical-topic or outcome evidence spans, so those
  families must abstain, use a new deterministic evidence locator, or receive an
  explicitly approved bounded source excerpt before provider execution.

## Decisions Promoted Into The Product

- Supported workflows live under `src/marygenai/` and the `marygenai` CLI.
- Historical experiment code is not a supported public API.
- Generated artifacts remain ignored and auditable.
- AI output remains candidate evidence.
- Retrieval confidence must not be confused with clinical evidence strength.
- Read-only MCP retrieval is the intended first external integration surface.
