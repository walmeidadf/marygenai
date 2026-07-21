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

## Read-Only Candidate Retrieval

- The implemented identity projection and two additional 150-record Batch runs
  first expanded the ignored index to 1,400 unique candidates across ten runs.
  After offsets 1,400 and 1,550 plus the targeted retry, the index contains
  1,700 candidates across thirteen classification runs. PMID is projected for
  1,687 documents, PMCID for 1,590, and DOI for 1,668. The combinations are
  1,555 documents with all three identifiers, 135 with two, and 10 with one;
  conservative parsing reports zero conflicts.
- The offset-1,100 and offset-1,250 Batches completed 300/300 requests with zero
  remote failures. Local conversion produced 300 strict-valid records and
  evidence spans for all 300. Provider expiry did not affect either run because
  both output files were retrieved and converted locally after completion.

- The isolated DuckDB index was rebuilt from eight completed broad/v3 Batch
  runs, the classification corpus, and the latest evaluation report for each
  run. It contains 1,100 unique candidate documents and retrieval-confidence
  records for all 1,100.
- The structured identity columns in the 1,100-record index contain 378 DOI
  values, no PMID values, 722 PMCID values, 1,100 canonical URLs, and 1,100
  source URLs. SQLite and the classification corpus contain the same sparse
  identity values, so the index did not drop fields that were already present
  there.
- The zero structured-PMID count is a selection and projection artifact. Batch
  offsets consumed a corpus ordered by `document_id`, producing 378
  `publication:doi` records followed by 722 `publication:pmcid` records before
  any `publication:pmid` records. Access routing still used richer identifiers
  found in local metadata without projecting them back into corpus identity.
- A read-only reconciliation of primary HTML/NXML article metadata, source
  URLs, cached Europe PMC metadata, and cached OpenAlex metadata recovered PMID
  for 1,087 documents, PMCID for 990, and DOI for 1,071. The resulting identity
  combinations were 958 documents with all three identifiers, 132 with two,
  and 10 with one. No conflicts remained after known URL-route normalization.
- Ninety-eight of the 378 structured DOI strings incorrectly include a trailing
  Frontiers `/full` route segment. This is a deterministic DOI extraction defect
  and should be normalized with provenance rather than represented as
  scientific uncertainty.
- Canonical and source URL coverage is 1,100/1,100. Canonical URLs are unique;
  1,098 use HTTPS and two use HTTP. All source URLs use HTTPS, but 483 are PMC
  OAI machine endpoints. Physician-facing responses should expose labeled
  PubMed, PMC full-text, DOI, and canonical links instead of treating an
  acquisition endpoint as the preferred access page. No live URL health check
  was part of this local audit.
- The four 150-record continuation runs contributed 600/600 strict-valid
  records with evidence spans. Their local evaluations selected 477 spans for
  grounding review. A record or span not selected for a worklist is not
  described as human reviewed or proven grounded.
- Candidate condition and exposure labels require a conservative alias layer.
  Case and trailing-abbreviation variants such as `Cannabidiol`,
  `Cannabidiol (CBD)`, and `cannabidiol` can share one retrieval key while their
  original values remain visible in detail and provenance.
- Strict clinical-question probes against the initial 500-record index returned
  four pediatric Dravet/CBD records with both efficacy and safety outcome domains,
  eight exact-Pain human therapeutic records, and ten obesity records with a
  mechanism or biomarker domain. These are retrieval checks, not inference
  quality judgments or evidence-strength assessments.
- Exact facet matching intentionally does not expand `Pain` to `Pain - Chronic`
  or other narrower labels. Ontology expansion must be versioned, visible in the
  effective query, and evaluated for false exclusion before it becomes a
  default.
- Realistic physician questions confirm that v3 supports broad condition,
  exposure, evidence-context, study-type, population-category, outcome-domain,
  and uncertainty retrieval. Dose, route, formulation, comparator, duration,
  detailed age, comorbidity, and outcome entities remain visible schema gaps.
- Effective-query trace, unsupported-dimension reporting, deterministic match
  explanations, and empty-result diagnostics are more important for the first
  clinical demo than an opaque semantic score.
- MCP references over PubMed, Europe PMC, and Semantic Scholar commonly separate
  search, paper detail, full text, citations, references, terminology, and
  identifier conversion. Related studies and citations are valuable future
  MaryGenAI tools, but the first server remains a closed local index with no
  network or provider calls.

## Classification

- A 150-request continuation Batch at offset 1,400 completed only 117 requests;
  33 requests returned provider HTTP 500 `server_error` responses. The 117
  successful responses converted to strict-valid candidate records, so the safe
  recovery is a targeted retry of the 33 failed custom IDs rather than repeating
  the full offset and duplicating successful inference cost.
- The targeted retry completed 33/33 requests with zero errors. Combined with
  the 117 original successes, offset 1,400 reached 150/150 strict-valid records.
  Offset 1,550 separately reached 150/150, allowing the read-only retrieval
  index to expand from 1,400 to 1,700 unique candidate documents.
- The offset-650, limit-150 Batch run (`20260717T111520Z`) completed 150/150
  remote requests with HTTP 200 and `finish_reason=stop`, zero failed requests,
  and no Batch error file. It used 1,045,488 input tokens and 163,595 output
  tokens, for 1,209,083 total tokens. Under the standing half-price Batch cost
  assumption, estimated cost was about USD 0.760, or USD 0.00507 per document.
- Local conversion produced 150/150 strict schema-valid candidate records,
  150/150 records with evidence spans, 586 evidence spans total, and 97/150
  records with declared uncertainty. Fifty-three records carried 54 recorded
  technical repairs: 52 uncertainty-marker deduplications and two
  required-marker additions. The run exposed no unsupported enum or new repair
  family and did not require a targeted rerun.
- The offset-500, limit-150 Batch run (`20260716T191943Z`) completed 150/150
  remote requests with HTTP 200 and `finish_reason=stop`, zero failed requests,
  and no Batch error file. It used 1,048,914 input tokens and 161,024 output
  tokens, for 1,209,938 total tokens. Under the standing half-price Batch cost
  assumption, estimated cost was about USD 0.756, or USD 0.00504 per document.
- Local conversion produced 150/150 strict schema-valid candidate records,
  150/150 records with evidence spans, 559 evidence spans total, and 122/150
  records with declared uncertainty. Eighty-six records carried 92 recorded
  technical repairs: 84 uncertainty-marker deduplications, five required-marker
  additions, and three removals of unsupported `outcome_domains=behavior`.
  These were existing deterministic repair families; the run exposed no new
  schema-repair case and did not require a targeted rerun.
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
- The first local v4 packet design confirmed that four field-family calls are
  not inherently cheaper: repeated schemas and broad family requests made the
  initial selective projection more expensive than one broad call.
- V2 added bounded label and sentence evidence locators, field-specific routing,
  a minimal semantic response schema, and deterministic candidate assembly.
  Evidence candidates remain retrieval aids, not final classifications.
- The original first-eight comparison was ordering-dependent and contained only
  direct-signal records. It was retained as historical packet-cost evidence but
  rejected as the next provider-comparison manifest because it could not test
  family suppression.
- The revised frozen manifest contains six direct-signal records, one
  metadata-label-only contrast, and one no-signal contrast across augmented
  links, PMC HTML, PMC OAI, and PDF source strategies.
- On this manifest, v2 generated eight broad packets, 30 selective packets, 38
  schema-valid mocks, eight assembled mock records, and no provider calls.
- Field routing avoided 87 of 248 possible selective field requests. The
  remaining 161 field instances had bounded candidate evidence; absent fields
  remained explicit instead of being sent speculatively.
- The broad strategy used about 52,383 estimated input tokens and a 24,000-token
  aggregate completion ceiling. Selective used about 41,658 estimated input
  tokens and a 14,400-token aggregate completion ceiling.
- Under the configurable USD 0.75 input and USD 4.50 output per-million-token
  assumption, maximum projected cost was USD 0.147287 for broad and USD
  0.096044 for selective. Selective was about 34.8% cheaper, or approximately
  USD 0.012005 per document at the ceiling.
- The assembler rejects unexpected fields, duplicate decisions, missing
  decisions, and evidence IDs that were not supplied in the packet. Identity,
  hashes, versions, and review boundaries remain deterministic.
- The no-signal contrast suppresses its cannabinoid family as not applicable.
  The metadata-label-only contrast suppresses the same family because no
  source-backed cannabinoid identity evidence exists.
- One audit exposed `Phycocyanin` being treated as cannabinoid evidence solely
  because it appeared in a legacy cannabinoid-label slot. That behavior was a
  correctable entity-routing defect. Metadata-only labels now require a known
  cannabinoid identity pattern before they can activate cannabinoid evidence.
- The selective-v4 work is useful architecture evidence, but it should not
  block the first product demonstration. The measured savings on an
  eight-document packet projection were not yet tied to inference-quality gains
  or reviewer adoption.
- The next product learning should come from a read-only MCP prototype over
  candidate evidence, using the 500-document broad/v3 Batch tranche as the
  initial demo base. This better tests whether physicians and prospective human
  reviewers find the retrieval surface valuable.
- A 50-document broad/v3 provider canary ran on 2026-07-10 using only
  `strict_classification_ready` records. It produced 50 HTTP 200 responses,
  50 valid JSON responses, 49 strict schema-valid records, no provider errors,
  no retries, and evidence spans for every valid record.
- The single strict validation error was a contract issue: the model returned a
  `cannot_determine` or empty population field without including
  `population_or_model` in `missing_or_uncertain_fields`. This is a targeted
  prompt/schema-hardening issue, not a provider-availability issue.
- The canary generated 217 evidence spans. Exact normalized grounding found
  174/217 spans; extraction-tolerant token-bigram grounding found 213/217,
  leaving four spans for grounding review.
- Filter coverage among the 49 valid records was complete for study design,
  evidence context, population/model, outcome domain, and overall direction;
  coverage was 47/49 for cannabinoids or exposures and 46/49 for medical
  conditions and intervention/exposure role.
- The canary used 318,522 prompt tokens and 59,873 completion tokens. At the
  standard `gpt-5.4-mini` rates verified on 2026-07-10, estimated cost was
  about USD 0.5083, or about USD 0.0102 per input document.
- Extrapolated from measured usage, the 3,149-record strict classification-ready
  corpus would cost about USD 32.01 with synchronous standard calls and about
  USD 16.01 with Batch pricing. The 3,374-record broader source-ready corpus
  would cost about USD 34.30 standard or USD 17.15 with Batch pricing.
- Synchronous latency was about 7.37 seconds per document. A full strict-corpus
  synchronous run would take roughly 6.45 hours if latency remains similar,
  making resumability or Batch preparation more important than further
  broad-versus-selective prompt research.
- The first local OpenAI Batch preparation produced 50 Batch-compatible
  requests and zero preparation errors without uploading files or calling a
  provider. Each JSONL line contains `custom_id`, `method`, `url`, and `body`,
  and the local manifest maps `custom_id` back to document identity, source
  hash, packet identity, model, and provenance.
- The first remote Batch submission attempt was blocked before batch creation:
  the configured restricted project API key lacked `api.files.write`, which is
  required to upload Batch input JSONL through the Files API. No remote Batch was
  created, no classification output was produced, and SQLite remained
  unchanged.
- After enabling the required file-write permission, the same 50-document
  mini-Batch completed successfully: 50 completed requests, zero failed
  requests, and no Batch error file.
- The completed Batch used 318,522 input tokens and 60,343 output tokens. The
  Batch-cost estimate was about USD 0.2552 for 50 records, or about USD 0.0051
  per input document. This projects the 3,149-record strict corpus at about
  USD 16.07 and the 3,374-record broader source-ready corpus at about USD 17.22
  under the same pricing assumption.
- Batch wall time was about 688 seconds from creation to completion: 62 seconds
  validating and 626 seconds in progress. For the full corpus, use polling or a
  scheduled monitor rather than keeping an interactive terminal session open.
- The supported Batch workflow now includes chunking with `--limit` and
  `--offset`, plus `classification watch-batch` for unattended polling,
  immediate local retrieval/conversion on terminal status, and a local watch log.
  This lowers the risk of duplicate corpus slices and missed output retrieval
  during the provider-side retention window.
- A 500-document Batch attempt on 2026-07-10 failed during provider validation
  with `token_limit_exceeded` before any request execution. The observed
  `gpt-5.4-mini` organization limit was 2,000,000 enqueued tokens; the prepared
  500-document file estimated about 3.59M input tokens and a 1.5M-token
  completion ceiling. This produced zero remote usage and confirms that
  MaryGenAI must size Batch chunks by estimated enqueued tokens, not only by
  request count.
- A 150-document sub-batch stayed below the local 1.8M estimated enqueued-token
  guard and completed successfully with 150/150 remote requests completed. Usage
  was 951,165 input tokens and 179,473 output tokens. Initial local conversion
  had two enum validation errors; deterministic conservative repairs for
  unsupported `study_design_subtype=in_vitro_or_cellular` and
  `overall_direction=negative` converted the same downloaded output to 150/150
  strict-valid candidate records. The direction repair maps to
  `cannot_determine`, not `harmful`, to avoid silently changing clinical
  meaning.
- A second 150-document sub-batch completed with 150/150 remote requests and
  converted to 150/150 strict-valid records after conservative local repairs for
  two new unsupported schema values: `outcome_domains=mental_health` and
  `population_or_model.category=plants`. Unsupported outcome-domain labels are
  removed while valid sibling domains are preserved and the field is marked
  uncertain; plant model categories are mapped to `cannot_determine` because the
  current population/model schema does not encode plant studies.
- A third 150-document sub-batch completed with 150/150 remote requests and
  converted to 150/150 strict-valid records after conservative local repairs for
  invalid uncertainty marker `biomarker` and misplaced
  `study_design_subtype=meta_analysis`. The run also surfaced raw unsupported
  outcome-domain values `behavior` and `pain`; they are removed from candidate
  records and retained by evaluation as schema-evolution signals.
- The first 500-document strict classification-ready tranche completed as four
  sequential Batch sub-batches: 150 + 150 + 150 + 50. Remote status reported
  500 completed requests and zero failed requests. After deterministic
  provenance-recorded technical repairs, local conversion produced 500/500
  strict-valid candidate records and 500/500 records with evidence spans.
  Measured usage was 3,251,515 input tokens and 578,801 output tokens. The
  Batch-cost estimate is about USD 2.52, or about USD 0.00504 per document,
  projecting the 3,149-record strict corpus at about USD 15.88 and the remaining
  2,649 strict records at about USD 13.36.
- The first conversion surfaced three schema validation errors caused by missing
  uncertainty markers for empty or `cannot_determine` retrieval fields. A local
  deterministic repair that only adds required `missing_or_uncertain_fields`
  markers or deduplicates repeated markers converted the same output to 50/50
  strict-valid records. Repairs are recorded in provenance and do not change
  scientific field values.
- Final Batch evaluation reported 223 evidence spans, 220 grounded with
  extraction tolerance, three spans requiring grounding review, 50/50 records
  with source traceability, and eight documents selected for targeted rerun or
  review.

## Decisions Promoted Into The Product

- Supported workflows live under `src/marygenai/` and the `marygenai` CLI.
- Historical experiment code is not a supported public API.
- Generated artifacts remain ignored and auditable.
- AI output remains candidate evidence.
- Retrieval confidence must not be confused with clinical evidence strength.
- Read-only MCP retrieval is the intended first external integration surface.
