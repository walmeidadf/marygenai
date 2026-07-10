# Decision Log

## 2026-07-10: Use Canary Results To Plan First Broad Candidate Base

A maintainer-authorized broad/v3 provider canary ran on 50
`strict_classification_ready` records using `gpt-5.4-mini`, 12,000 source
characters, and a 3,000-token completion ceiling. It produced 50 HTTP 200
responses, 50 valid JSON responses, 49 strict schema-valid candidate records,
and one validation error. No retries or provider errors occurred.

The run used 318,522 prompt tokens and 59,873 completion tokens. At the
standard pricing verified for `gpt-5.4-mini` on 2026-07-10
(USD 0.75 per million input tokens and USD 4.50 per million output tokens), the
estimated canary cost was USD 0.508320, or about USD 0.010166 per input
document and USD 0.010374 per strict-valid record.

Projected from measured canary usage:

- 3,149 strict classification-ready records: about USD 32.01 with standard
  synchronous calls, or about USD 16.01 with Batch pricing;
- 3,374 broader source-ready records: about USD 34.30 with standard synchronous
  calls, or about USD 17.15 with Batch pricing.

Latency was 368.503 seconds total for 50 responses, about 7.37 seconds per
document. A full synchronous strict-corpus run would therefore take about
6.45 hours if latency remains similar. Before a full run, the pipeline should
support a resumable execution plan or Batch-compatible artifact preparation.

The canary is strong enough to continue toward a first candidate-classified
base and read-only MCP prototype. It does not justify treating candidate output
as reviewed knowledge. The one schema error and the 10 evaluator-selected rerun
documents should feed targeted prompt/schema hardening and human review, not a
return to broad architecture exploration.

Before spending additional provider credit on the full corpus, MaryGenAI should
prepare and validate a small OpenAI Batch-compatible input file locally using
the same broad/v3 prompt payload. This tests the operational format intended for
the full dataset while preserving the review boundary. Local batch preparation
does not upload files, create a remote batch, call a provider, mutate SQLite, or
create reviewed knowledge.

The first local Batch preparation created 50 `strict_classification_ready`
requests with zero preparation errors, `url=/v1/chat/completions`, and unique
`custom_id` values mapped back to MaryGenAI document identity, packet identity,
source hashes, model, and provenance through a local manifest. This is the
correct next operational artifact to submit only after explicit maintainer
authorization.

Batch submission and retrieval must preserve a local audit chain:

1. prepared input JSONL;
2. MaryGenAI manifest keyed by `custom_id`;
3. remote file and batch submission record;
4. status snapshots;
5. downloaded output and error files;
6. converted candidate-classification records, raw responses, errors, and
   summary.

The converted records must use the same candidate schema and evaluator contract
as synchronous runs so Batch and non-Batch quality can be compared directly.

## 2026-07-10: Ship A First Broad Candidate Base And Read-Only MCP Before More V4 Optimization

The next product milestone is a demonstrable read-only retrieval surface for the
medical team, not another classification-architecture refinement cycle.

MaryGenAI will use the existing broad `candidate_study_classification.v3`
contract as the first operational candidate-classification path for a
maintainer-authorized provider canary and then a first local candidate base. The
v4 selective field-family architecture remains a documented finding and future
optimization path, but it is no longer a blocker for the MVP.

This changes the near-term priority order:

1. run a bounded provider-backed canary of 50 to 100 strict
   classification-ready documents under the maintainer's available API balance;
2. evaluate real usage, strict schema validity, retry behavior, latency,
   grounding, and projected full-dataset cost from that canary;
3. after maintainer approval and additional credit if needed, classify the
   strict source-ready corpus as candidate evidence;
4. expose the candidate base through a read-only MCP surface for medical-team
   demonstration and reviewer recruitment;
5. use human review to improve trusted field-level knowledge rather than
   continuing to optimize prompt architecture in isolation.

The maintainer-reported initial API balance is USD 5.90. That balance is an
execution guardrail for the canary, not a durable pricing assumption. Provider
pricing must be checked immediately before paid execution, and the canary must
record real usage and cost artifacts.

Provider-backed output remains `ai_classified_candidate` evidence with
`review_state=needs_review`. It must not mutate SQLite review queues, review
decisions, or reviewed knowledge. The future MCP must be read-only and must
return source identity, evidence, uncertainty, provenance, and trust-level
language so candidate retrieval cannot be mistaken for medical advice.

## 2026-06-23: Freeze A Contrast-Aware Manifest Before Provider Comparison

Broad and selective comparisons must use an explicit frozen manifest rather
than the first N rows of a sample file. File ordering can hide contrast records
and make family-suppression metrics meaningless.

The current eight-document manifest contains six direct-signal records, one
metadata-label-only contrast, and one no-signal contrast with source-strategy
diversity. The emitted manifest can be supplied to later local or explicitly
authorized provider execution through `--manifest-path`.

Metadata slots do not establish scientific entity type. A value such as
`Phycocyanin` must not activate the cannabinoid semantic family merely because a
legacy export placed it in a cannabinoid-label field. Metadata-only candidates
must pass a cannabinoid identity guardrail and have source-backed identity
evidence. Route or formulation phrases alone cannot activate the family.

With these constraints, two cannabinoid-family calls were suppressed and the
eight-document selective projection used 30 calls rather than 32. No provider
call is authorized by this decision.

## 2026-06-23: Route V4 At Field Level And Assemble Identity Deterministically

Selective v4 packets request only fields with bounded, field-relevant evidence.
Every semantic field receives one of four routing states:
`deterministically_resolved`, `semantic_resolution_required`,
`insufficient_evidence`, or `not_applicable`.

The semantic provider contract is intentionally small. It returns field names,
selected values, evidence IDs, categorical confidence, and structured
uncertainty. Document identity, source hashes, versions, timestamps, trust and
review boundaries, and final broad-record assembly remain deterministic Python
responsibilities.

Evidence locators may find source sentences for conditions, cannabinoid
mentions, and outcomes, but they do not choose the final relation or direction.
The assembler rejects unknown evidence IDs, unexpected fields, duplicate field
decisions, and missing requested decisions.

On the same eight-document frozen sample, this design avoided 72 of 248
potential field requests and reduced the selective maximum-cost projection from
the broad USD 0.150251 to USD 0.103974 under the configured token-price
assumption. All four semantic families were still required for each of these
direct-signal documents, so call count did not decrease. No provider call is
authorized by this decision.

## 2026-06-23: Version V4 By Semantic Family And Measure Call Overhead Explicitly

The first v4 preparation contract uses one broad candidate schema and four
independently versioned semantic-family schemas:

1. clinical topic, anatomy, and organ system;
2. cannabinoid identity and scientific role;
3. population, sample, geography, and study structure;
4. outcomes and overall direction.

Prompt packets preserve source identity and hash, parser evidence IDs and
offsets, requested fields, response schema and prompt versions, completion
limits, target model configuration, uncertainty, and preparation provenance.
Strict deterministic mocks validate every response schema without representing
semantic truth.

The first eight-document projection found that four selective calls per document
were more expensive at the configured maximum-token ceiling than one broad call.
This is an architecture measurement, not a reason to collapse field provenance.
Selective execution should suppress families that have no unresolved fields or
no adequate evidence and should test smaller response contracts before a
provider run.

The current parser does not provide direct outcome evidence. Missing family
evidence must remain visible and lead to abstention or improved evidence routing;
unrelated sample, route, or population snippets must not be presented as outcome
support. No provider call is authorized by this decision.

## 2026-06-23: Compare Compact Semantic Packets Before Any Broader V4 Run

The next v4 experiment will not send full source text and every retrieval field
through an unbounded broad prompt. It will first build local, inspectable prompt
packets from deterministic metadata and parser candidates.

The first comparison will use the same 5 to 10 documents for both strategies:

1. one broad v4 candidate-record prompt;
2. selective field-family prompts over compact evidence candidates.

Before a provider call, the implementation must report packet character and
token estimates, fields requested, evidence candidates included, and projected
cost inputs. The provider, model, source-character limits, completion limits,
and documents must be identical where comparison requires them.

No provider call is authorized by this decision alone. Prompt packets, schemas,
local evaluation, and cost projections should be validated first. AI outputs
remain candidate evidence and must not mutate SQLite or reviewed knowledge.

## 2026-06-23: Use Parsers To Generate Field Evidence, Not Silent Final Values

The first 12-document v4 metadata/parser baseline produced candidate evidence
for sample size, route, country mentions, population/species, and study-design
signals without calling an LLM. Candidate recall was useful: five of six
available legacy sample-size references and four of six route references
appeared in the extracted candidate sets.

The same documents also exposed why regex matches are not final classifications.
Articles contain arm sizes, screening counts, analyzed samples, cited animal
models, background routes, reference study designs, and author affiliations.
Choosing the principal value and scope is a semantic task.

Deterministic extractors should therefore preserve all bounded candidate values,
evidence, source hash, method, and confidence. They may finalize only
unambiguous metadata under an explicit field rule. Otherwise they should route a
compact evidence packet to selective semantic resolution or abstain. Silent
normalization that discards ambiguity is not allowed.

## 2026-06-22: Let The Downloaded Corpus Define Classification Scale

The deduplicated downloaded corpus, after source-quality and classification
eligibility checks, defines the classification queue, provider-call volume,
throughput, and cost projection. The normalized English legacy dataset is not a
batch input by default.

The legacy dataset remains a valuable normative bootstrap and guardrail. It
defines candidate vocabularies, supplies comparison metadata, helps stratify
development and holdout samples, and exposes likely error families. It must not
silently override explicit source evidence or be treated as reviewed clinical
truth.

Efficiency reports should therefore follow downloaded, source-ready,
classification-ready, deterministically enriched, LLM-required, provider-valid,
and evidence-supported counts. Projecting cost from the number of legacy records
is not valid.

## 2026-06-22: Plan V4 Around Patient-Oriented Retrieval Fields

The current v3 contract is insufficient for the intended physician journey
because it does not preserve several essential MCP dimensions. Organ-system
labels enter prompt metadata but have no structured output field. Study
geography, sample size, study period, age group, sex, comparator, and route are
also absent or insufficiently structured.

V4 should separate clinical conditions, pathology or disease family, symptoms,
anatomical entities, organ systems, cannabinoid entities and roles, population,
sample scope, study structure, and outcomes. Publication year remains canonical
bibliographic metadata; study and enrollment dates are separate fields.

The contract should be evaluated by field family. A correct study-design label
must not conceal incorrect condition, organ, cannabinoid, population, or outcome
metadata.

## 2026-06-22: Prefer Deterministic Enrichment Before Selective LLM Calls

V4 experiments should compare one broad LLM call with deterministic assembly and
selective field-family calls. Canonical metadata, structured sources, parsers,
and ontology matching should run before an LLM. The LLM should be reserved for
semantic relations and unresolved ambiguity.

Every field-level value should preserve extraction method, evidence, source
hash, component version, uncertainty, and model provenance when applicable.
Required efficiency metrics include LLM invocation rate, deterministic coverage,
tokens and cost per invoked document, cost per valid candidate, cost per correct
evidence-backed field, and incremental quality gained per provider dollar.

The first validation sequence is local-only: profile the downloaded corpus,
compare available legacy guardrails, and freeze a small retrieval-field sample.
Provider-backed comparison requires an explicit later authorization.

## 2026-06-19: Promote Explicit Source Signals Into Study-Design Rule V2

`study_design_rules.v2` refines title-rule candidates using only explicit,
hash-verified source-text signals. It recognizes source-declared double-blind
trials, distinguishes interventional from observational pilots, and separates
ecological analyses from studies whose primary method is a participant survey.

The rule remains conservative. Placebo control or randomization alone does not
imply double blinding, and normalized English legacy labels do not silently
override missing source evidence. Original labels and every applied rule remain
in provenance.

On the 21-record conflict-enriched development benchmark, exact
category-plus-subtype accuracy increased from 13/21 (0.6190) to 20/21 (0.9524).
Category accuracy increased from 14/21 (0.6667) to 20/21 (0.9524), category
macro-F1 from 0.3011 to 0.9048, and subtype accuracy from 20/21 (0.9524) to
21/21 (1.0000).

The remaining miss is a double-blind refinement supported by external PubMed
indexing but not by the locally persisted source artifact. Rule v2 does not use
the reviewed label or legacy label to manufacture that source signal.

The rule was then applied to the frozen 40-record holdout without inspecting
holdout labels. It changed three candidate categories, all through explicit
double-blind source signals. Holdout quality metrics remain unavailable until
the rule version is frozen and the holdout is reviewed.

## 2026-06-19: Separate Study-Design Development And Holdout Sets

The 21 source-reviewed legacy-disagreement records are the development benchmark.
They may guide deterministic rule changes and expose error patterns, but their
metrics are not corpus-wide accuracy estimates because the records were selected
for disagreement.

`marygenai classification evaluate-validation-benchmark` is the official local
evaluator for append-only reviewed decisions. It validates identity, source
hashes, `confirmed` versus `corrected` semantics, reviewer provenance, and
reports category, subtype, pair, per-label, legacy-reference, and error-pattern
metrics without calling an LLM or mutating SQLite.

A separate 40-record holdout is frozen before rule v2 development. It excludes
all reviewed development records and contains 20 exact rule/legacy agreements,
10 new disagreements, five records without normalized English legacy reference,
and five multi-rule titles. The holdout remains unreviewed until rule v2 is
frozen. This prevents review knowledge from leaking into implementation choices.

The five available no-reference candidates are all canine studies. This is a
documented corpus limitation, not evidence that the no-reference population is
generally canine.

## 2026-06-19: Identify Assisted Benchmark Review Explicitly

Maintainer-confirmed study-design decisions use
`reviewer=marygenai:maintainer` with
`review_method=human_confirmed_with_ai_assistance`. The reviewer value identifies
the platform workflow; the method states that a human confirmed the semantic
decision. It must not be interpreted as autonomous model review.

## 2026-06-18: Build Review-First Study-Design Benchmark Candidates

`marygenai classification build-validation-benchmark` is the supported
deterministic builder for a small study-design validation worklist. It uses
explicit title phrases, source-ready corpus records, source hashes, normalized
English legacy context, and round-robin design stratification. It does not call
an LLM or mutate SQLite.

The output is deliberately a candidate benchmark with
`review_state=needs_review`, empty reviewer fields, and explicit provenance. It
must not be described as source-reviewed truth until a human reviews the source
and records a label, rationale, identity, and timestamp.

Rule precedence is part of the versioned candidate contract: reviews dominate
mentions of included trials; animal and laboratory context dominate trial
wording; and pilot wording refines an explicit trial as a subtype. Legacy
comparison separates exact matches, compatible
`meta_analysis`/`clinical_meta_analysis` refinements, true disagreements, and
missing references.

## 2026-06-18: Treat Auxiliary Classifiers As Experimental Signals

Classical TF-IDF or embedding classifiers trained on current legacy labels are
legacy-consistency models, not source-truth validators. They may contribute a
low-weight agreement or margin signal, but they must not override explicit
source evidence. A source-reviewed training set with `other` and subtype examples
is required before promoting them into classification validation.

Small NLI models may contribute a semantic-support signal when applied to short,
selected evidence spans and versioned atomic hypotheses. They must not act as a
binary gate: neutral is not contradiction, hypothesis wording is material, and
generic NLI training does not guarantee scientific study-design reliability.

Both signal families remain outside `retrieval_confidence.v1` until evaluated
against a source-reviewed benchmark. Deterministic schema, provenance,
grounding, and consistency checks remain the production baseline.

## 2026-06-18: Start Retrieval Confidence As A Deterministic Evaluator Signal

`retrieval_confidence.v1` is computed deterministically in Python from technical
integrity, source quality, evidence grounding, metadata consistency, retrieval
completeness, and declared uncertainty. Model-declared
`classification_confidence` is not an input.

The v1 score remains an ignored evaluator artifact rather than a field in the
candidate-classification schema. It exposes component values, weights, reasons,
a base band, a broad-recall score, and a high-precision score. This permits
weight and threshold experiments before making the signal a public retrieval
contract.

The score is not a calibrated probability, clinical evidence strength, or human
review status. Source-supported overrides are not penalized as model errors,
while unresolved disagreements and source-explicit structured contradictions
receive material penalties.

## 2026-06-18: Separate Descriptive Outcomes From Null Effects

Classification prompt v4 reserves `null` for a tested effect or association with
no meaningful difference or association. Descriptive surveys, prevalence or rate
estimates, knowledge or perception studies, methodological reports, and other
records without a beneficial/harmful effect question use `not_applicable`.

The evaluator also distinguishes study-design disagreements as
`source_supported_override`, `compatible_refinement`, or
`unresolved_disagreement`. Only unresolved disagreements automatically enter the
targeted rerun input. Legacy disagreement remains visible, but an explicit
source-supported subtype is not treated as a model failure merely to increase
exact agreement.

Legacy `study_result` comparison is retained only as a named proxy. Values such
as `Positive` and `Negative` are not assumed to be equivalent to
`beneficial` and `harmful`; descriptive surveys, rates, and evidence findings
demonstrate that the semantics differ.

Prompt v5 also requires an explicitly named source subtype to control
`study_design_subtype`. A source titled as a scoping review must use
`scoping_review`, even when its principal retrieval category remains
`clinical_meta_analysis`. Warnings must not contradict structured fields.

## 2026-06-18: Advance Candidate Classification To Schema V3

`candidate_study_classification.v3` makes `cognition` an official outcome domain
for memory, attention, executive function, neurocognitive performance, and
cognitive impairment. This preserves a useful retrieval dimension that could
not be represented faithfully in schema v2.

List fields never accept `cannot_determine`. An unsupported list is empty and
its canonical field name is required in `missing_or_uncertain_fields`.
Uncertainty entries are now a strict field-name enum; explanatory text belongs
in `warnings`. This prevents free-text normalization from hiding model contract
errors.

The principal English legacy-compatible study-design domain remains unchanged.
Schema v3 adds `study_design_subtype` for systematic, scoping, narrative, and
mechanistic reviews; surveys; case reports or series; observational studies; and
pilot studies. Surveys, case reports or series, and observational studies that
do not fit a principal legacy category use `study_design_category=other`.

## 2026-06-18: Make Classification Evaluation An Official Local Workflow

`marygenai classification evaluate` is the supported reproducible evaluator. It
reads ignored candidate artifacts, normalized English legacy context, and source
text without calling a model or mutating SQLite. Reports separate technical
validity, retrieval utility, and inference quality and preserve disagreement as
an evaluation signal rather than automatically treating the legacy label as
truth.

The evaluator writes ignored reports, study-design disagreements, source
grounding checks, documents requiring rerun, and a targeted rerun input under
`data/normalized/classification_evaluations/`.

Evidence grounding reports two separate measurements. Exact normalized
substring grounding is the strict signal. Token-bigram grounding is a secondary
signal that tolerates source-extraction artifacts such as interleaved author
names, headers, and journal metadata. A tolerant match does not rewrite or
normalize the stored evidence span, and spans below the threshold remain visible
for inspection.

## 2026-06-18: Define MaryGenAI As A Retrieval-Oriented Source-Intelligence Product

MaryGenAI's primary value is to make cannabinoid medical literature easier to
discover, filter, inspect, and verify. Candidate classifications are structured
retrieval metadata for physicians, researchers, and downstream AI assistants.
They are not clinical truth or treatment recommendations.

Classification quality must be evaluated in three separate groups: technical
validity, retrieval utility, and inference quality. Declared scientific or
source-related uncertainty can remain useful when it is evidence-backed and
visible. Known schema, prompt, source-routing, or pipeline defects should be
corrected rather than accepted as unavoidable uncertainty.

Current model confidence is categorical self-assessment, not a calibrated
probability. A future retrieval confidence score must be computed separately and
must remain distinct from clinical evidence strength and human review status.

## 2026-06-18: Keep Only Supported Package Workflows In The Public Surface

The public repository should expose supported workflows through
`src/marygenai/` and the `marygenai` CLI. Historical standalone POC
implementations, POC-only tests, and local batch runners are no longer supported
public APIs. They may be preserved locally under ignored
`temp/project_archive/`, while durable findings remain public in
`docs/experimental_findings.md` and this decision log.

This is an archival boundary, not a rejection of the experiments. Git history
preserves their implementation, and validated capabilities should be promoted
into package modules with focused tests and official command documentation.

## 2026-06-18: Interpret The 100-Document Schema-V2 Gate By Metric Type

The second 100-document `gpt-5.4-mini` gate produced 100 successful provider
responses without retries, 97 strict-valid records, and evidence spans for every
valid record. Among valid records, 90 of 97 principal study-design labels
exactly matched normalized English legacy context. The three validation failures
shared a correctable `outcome_domains` enum issue.

These results should not be collapsed into one accuracy number. Provider success
and Pydantic validity are technical metrics. Evidence-span and filter-field
coverage are retrieval-utility metrics. Legacy agreement, source-supported
disagreement, and uncertainty quality are inference metrics.

## 2026-06-17: Use GPT-5.4 Mini For The Next Classification POC Gate

Same-document provider tests showed that `gpt-5.4-mini` is the best current
cost-quality default for candidate study classification POCs. On the difficult
5-document set, `gpt-5.4-mini` produced 5/5 strict Pydantic-valid records, while
`gpt-5.4-nano` produced only 3/5 valid records and confused
`study_design_category` with `evidence_context`. On the 30-document comparison
set, `gpt-5.4-mini` reached 30/30 valid records after one retry, with an
estimated clean cost of about USD 0.28 versus about USD 0.60 for the prior
`gpt-4.1` baseline.

The default POC settings should therefore be OpenAI `gpt-5.4-mini`,
`max_source_chars=6000`, and `max_completion_tokens=3000`. The prompt should
reinforce strict enum discipline, especially for `study_design_category`,
`evidence_context`, and `outcome_domains`.

The project is not ready for an unattended full-corpus classification run yet.
Before mass classification, run a 100-document stratified gate and evaluate
valid JSON rate, strict schema pass rate, retry reasons, cost per document,
latency, evidence-span quality, and classification distribution drift. The
evaluation baseline should be the normalized English legacy context when it is
available, especially `type_of_study`, `study_result`, `key_findings`, and
English list fields. Portuguese bootstrap fields remain traceability/fallback
fields, not the preferred analytic baseline. Outputs remain candidate evidence
for human review and must not mutate SQLite review state or reviewed knowledge.

## 2026-06-17: Align Study Design Classification To English Legacy Domain

The 100-document `gpt-5.4-mini` gate exposed a schema problem: the original
candidate classification schema allowed interpretive study-design values such as
`narrative_review` and `mechanistic_review`, while the trusted human-curated
legacy baseline uses the English `type_of_study` domain: `Meta-analysis`,
`Clinical Meta-analysis`, `Clinical Trial`, `Double Blind Clinical Trial`,
`Animal Study`, and `Laboratory Study`. This made model outputs look discordant
even when the model was selecting a permitted but non-comparable category.

The classification contract is therefore advanced to
`candidate_study_classification.v2`. Its principal `study_design_category` field
must use the legacy-compatible enum values `meta_analysis`,
`clinical_meta_analysis`, `clinical_trial`, `double_blind_clinical_trial`,
`animal_study`, `laboratory_study`, `other`, or `cannot_determine`. More granular
interpretive distinctions such as mechanistic or narrative review may be added
later only as separate subtype fields, not as replacements for the principal
legacy-comparable category.

## 2026-05-10: Use English Throughout The Project

All code, variables, filenames, comments, schemas, documentation, and CLI output should be written in English.

## 2026-05-10: Use Python 3.13+ And `uv`

The project uses Python 3.13+ and `uv` for virtual environment and dependency management.

## 2026-05-10: Start As A POC Lab

The project will start with source-specific POCs before committing to a production crawler, final database, or review interface.

## 2026-05-10: Keep Legacy Files Local

Legacy exports are useful for analysis but should not be committed. They are stored in `temp/legacy/`, and `temp/` is ignored by Git.

## 2026-05-10: Defer Database Choice

PostgreSQL, NoSQL, graph databases, and file-based approaches remain open options. The decision should follow source POC results and ontology modeling needs.

## 2026-05-10: Defer Review Interface Choice

Human review is required, but Label Studio is not yet a fixed decision. Any review workflow must preserve field-level review provenance.

## 2026-05-13: Treat PubMed As Metadata Hub Before Full-Text Crawling

PubMed/NLM is the primary publication identity and metadata source for the next
publication POCs. The project will first expand PubMed metadata testing, reconcile
legacy PubMed/NLM links, and classify full-text availability through PMC, Europe
PMC, Unpaywall, DOI, and publisher links before designing any continuous crawler or
bulk PDF workflow.

## 2026-05-13: Use PubMed As The Primary Study Discovery Source

For the publication-source track, PubMed is the current primary source for detecting
new candidate studies. It should be used to discover and prioritize records, while
PMC, Europe PMC, Unpaywall, DOI, and publisher links should be used later for
access enrichment. PubMed should not be treated as a direct file crawler.

## 2026-05-13: Prefer HTML/XML Before PDF For Full-Text Extraction

The first POC 6 sample showed that direct PMC HTML and structured full-text XML are
better first-choice extraction inputs than PDF. Europe PMC rendered article pages
should not be treated as stable static HTML fetch targets because they can return
JavaScript-dependent placeholder content. When a `PMCID` is available, the
pipeline should prefer PMC HTML and use Europe PMC full-text XML when available.
PDF retrieval should remain a narrow fallback or supplemental artifact until a PDF
parser is justified by extraction gaps.

All full-text extraction outputs remain candidate evidence until human review.

## 2026-05-13: Normalize LLM Evidence Through Strict Review-First Schemas

POC 6b keeps LLM extraction out of the final-truth role. LLMs and heuristics may
generate candidate evidence snippets and candidate values from section-scoped
text, but normalized POC outputs must pass strict Pydantic models and every field
must remain `needs_review=true` with `review_state=needs_review`.

Provider behavior should be recorded as provenance and operational evidence.
Local models may be useful for candidate discovery, while hosted models can be
used for structured comparison. Rate-limit headers, provider errors, and rejected
JSON are part of the POC result, not incidental noise.

## 2026-05-14: Use Review-Ready JSONL Rows Before Choosing A Review Tool

POC 6c uses field-level JSONL rows as the first human-review interchange format.
Each row preserves the source record id, field, candidate value, evidence text,
section, provider, model, confidence, ontology version, extractor version, and
empty review placeholders for reviewer identity, reviewed value, timestamp, and
notes.

This keeps the review contract explicit while deferring the final interface choice
between Label Studio, spreadsheet review, or a custom review UI.

## 2026-05-14: Treat Legacy As A Trusted Curated Reference

The maintainer's private legacy dataset should be used as a high-trust curated
reference, not merely as historical data. Populated bootstrap values can anchor
validation and comparison for identity, inclusion, study classification,
conditions, compounds, and extracted field values.

Missing legacy values should remain interpretable. For sparse or context-dependent
fields such as dosage and treatment duration, absence may mean `not_applicable` or
`not_reported`, especially for simpler studies or records without intervention,
control group, placebo, or protocol details.

## 2026-05-14: Separate Discovery From Full-Text Extraction

New-publication discovery should first associate PubMed results against the legacy
identity index and classify records as exact matches, possible matches, new
candidates, or manual identity-review items. Full-text access enrichment and
field extraction should run only after records are prioritized for inclusion.

## 2026-05-15: Use Citation Metrics As A Secondary Ranking Signal

The April 2025 PubMed discovery plus iCite validation showed that citation
metrics are useful for review-queue experiments but unsafe as the primary sort.
The window produced 67 deduplicated records, with iCite coverage for all PMIDs,
but citation-only ranking promoted several weak cannabinoid-focus records and
buried some strong recent RCTs and reviews with low citation maturity.

Review prioritization should therefore keep cannabinoid focus, PubMed discovery
score, study design, and full-text review priority as the baseline. Citation
count, Relative Citation Ratio, and related iCite fields should be used as
secondary signals and audit columns, not replacements for cannabinoid relevance,
evidence design, or human review.

## 2026-05-15: Start MVP Design Around Review And Curation

The source POCs are sufficient to start designing an MVP for internal evidence
review and knowledge-base curation while Semantic Scholar access remains pending.
The MVP should use the validated PubMed, legacy reconciliation, access enrichment,
iCite enrichment, and review-row flows already available.

The MVP should not be framed as a medical advice product. Its first product
surface should help human reviewers inspect candidate studies, compare provenance,
resolve inclusion and identity decisions, and preserve field-level review
metadata. Semantic Scholar can be added later as an enrichment source rather than
a blocker for the first MVP design.

## 2026-05-15: Make Cannabinoid Focus The Dominant MVP Ranking Signal

The MVP review queue should be dominated by `cannabinoid_focus`. Direct evidence
in title or indexed PubMed metadata should place a record in the primary review
queue. Abstract-only records should be handled cautiously, and records without a
cannabinoid signal should not be promoted automatically by recency, study design,
or citation metrics.

iCite remains a cost-benefit evaluation and optional secondary enrichment source,
not a priority for the first MVP. Citation metrics must not outrank cannabinoid
relevance.

## 2026-05-15: Use Local-First Hybrid Persistence For MVP Architecture

The first MVP should use a local-first hybrid persistence model: immutable raw
payloads and snapshots in ignored local files, review application state in
SQLite, and JSONL or Parquet exports for audit and interchange. Local `data/`
paths should mirror future S3-compatible object keys so raw payloads, staging
outputs, normalized records, reviewed snapshots, and run manifests can later move
to object storage without changing source adapter contracts.

Docker Compose should be introduced around concrete API, worker, UI, and database
roles, not before the review data model is clear. PostgreSQL, search indexes,
graph storage, and vector indexes remain future options to add when multi-user
concurrency, search, relationship traversal, or semantic retrieval requirements
are demonstrated.

## 2026-05-15: Keep GenAI Retrieval And Ontology Storage Options Open

MaryGenAI should explicitly preserve a GenAI architecture path. The future
platform should support agentic evidence search, hybrid lexical/vector retrieval,
ontology-aware filters, and RAG over reviewed evidence while keeping generated
answers grounded in reviewed fields, evidence text, and provenance.

PostgreSQL should not be assumed as the only next database. PostgreSQL remains a
strong option for relational review workflow state, while MongoDB or another
document database may fit ontology-enriched entities and semi-structured metadata
if those access patterns dominate. Qdrant should be considered a rebuildable
retrieval layer for embeddings and hybrid search, not the source of truth.

The legacy ontology CSVs for cannabinoids, medical conditions, organ systems,
terpenes, and glossary terms should become normalized ontology entities with
provenance and review state, then later accept vetted enrichments from sources
such as Wikipedia, PubMed, MeSH, ICD, DrugBank, or Wikidata.

## 2026-05-15: Start Initial Load With JSONL Snapshots And Run Manifests

The MVP initial load should start with Pydantic contracts, ignored local JSONL
snapshots, and run manifests before populating an operational database. This keeps
legacy studies, source records, publication candidates, ontology entities, and
document-to-ontology links auditable while preserving the option to add SQLite as
the first review persistence layer once queue and review workflows are clearer.

The local `data/` layout should be created by setup code and mirror the future
object-storage layout from the MVP architecture requirements. Legacy CSV exports
remain in `temp/legacy/` and are read in place without renaming Unicode filenames.

## 2026-05-15: Use SQLite As Local Operational State For MVP Review Queues

SQLite is now the first operational persistence layer for the MVP review workflow.
Initial Load JSONL snapshots and run manifests remain the audit and interchange
source, while `data/db/marygenai.sqlite` stores current local application state.

The first schema is intentionally narrow and idempotent. It creates
`run_manifest`, `source_record`, `document`, `document_identity`, `publication`,
`ontology_entity`, `document_ontology_link`, and `review_item`. The initial queue
is `legacy_identity_review`, populated from legacy publication candidates that
lack PMID, PMCID, and DOI and therefore need human identity review before they
can be treated as strongly resolved.

This does not choose the final database architecture. PostgreSQL, document
stores, search indexes, graph stores, and vector indexes remain future options
based on demonstrated review, ontology, collaboration, and GenAI retrieval access
patterns.

## 2026-05-28: Compare LLM Providers On Fixed Evidence Spans

The LLM study reclassification POC should compare providers on the same
deterministic evidence summary packets before drawing conclusions about model
quality. For complex extraction tasks, provider/model comparisons must preserve
the document sample, selected spans, selected chunks, prompt version, source
artifact provenance, and legacy English context id.

Comparison outputs remain candidate evidence for human review. They must not
validate identity, mutate SQLite review state, update reviewed knowledge, or
download new full text. Local metrics such as grounding pass rate, unsupported
evidence text count, not-found/insufficient-evidence counts, latency, and errors
are operational audit signals, not acceptance criteria for automatic knowledge
updates.

## 2026-06-11: Use Official-First Source Acquisition Before Publisher Fetching

The source-acquisition path should prefer official or source-declared routes
before generic publisher fetching. For PMC records, PMC OAI-PMH is the first
production-like route because it produced source-ready text reliably and avoids
fragile page scraping. NCBI ELink and OpenAlex are access/identity augmentation
sources rather than full-text sources; their URLs must be filtered before
acquisition because many LinkOut targets are metadata, clinical, commercial, or
non-article surfaces.

Source acquisition POC outputs remain ignored local artifacts. They must not
mutate SQLite, review queues, review decisions, or reviewed knowledge.

## 2026-06-11: Treat Digital PDF Extraction As First-Class, OCR As Residual

PDF text is valid source material for study classification when digital text can
be extracted with sufficient scientific-section signal. The project uses PyMuPDF
as the near-term digital PDF extractor and separates poor-text-layer or scanned
PDFs into a later OCR route. OCR should not be the default PDF path, and table,
figure, dosage, and arm reconstruction remain later enrichment problems.

## 2026-06-11: Start Classification Work Around A Practical 4,000-Text Corpus

Superseded by the 2026-06-15 pivot decision below.

The original source-availability gate targeted 5,000+ classification-ready
texts. The June 2026 acquisition POCs showed a credible path toward roughly
4,000 high-quality source texts when PMC OAI-PMH, Unpaywall PDFs, augmented
links, and later PubMed discovery are combined. A roughly 4,000-text corpus is
therefore sufficient to begin the first classification workflow, while continued
source acquisition and PubMed discovery should keep expanding coverage.

## 2026-06-15: Pivot To Source Intelligence And Candidate Classification

The exhausted June 2026 legacy-core acquisition campaign showed that the
legacy-only corpus is likely below the original 5,000+ target and below a strict
4,000 classification-ready threshold. The local maintainer workspace currently
has about 3,149 strict classification-ready legacy-core documents and about 3,374
broader source-ready legacy-core documents.

MaryGenAI should therefore continue as a cannabinoid scientific
source-intelligence and candidate-classification engine rather than pause for
large-scale human curation. The next workstream is to freeze a deduplicated
classification corpus rollup, define a strict candidate classification schema,
run a small stratified AI-classification POC, and later expose discovered,
enriched, source-ready, and candidate-classified scientific documents through
read-only retrieval surfaces such as an MCP server.

## 2026-06-15: Define Candidate Study Classification Schema V1

Superseded for new runs by
`candidate_study_classification.v2`, which aligns the principal study-design
field to the English legacy domain.

The first AI classification contract was `candidate_study_classification.v1`.
It is a strict Pydantic schema for candidate evidence only, not reviewed
knowledge. It requires run/model/prompt/source-text provenance, a SHA-256 hash
for the source text, coarse study-design and evidence-context classifications,
condition and cannabinoid candidate labels, population/model, outcome domains,
overall direction, confidence, evidence spans, warnings, and uncertainty notes.

The schema keeps `requires_human_review=true` and `review_state=needs_review`.
Outputs that use `cannot_determine` must explain the uncertainty in
`missing_or_uncertain_fields`. This keeps the first LLM POC focused on
structured, reviewable scientific triage while preventing automated promotion to
reviewed knowledge.

AI classification outputs are candidate evidence only. They must preserve
source, model, prompt, schema, confidence, and evidence-span provenance, and must
not be described as human-reviewed knowledge unless a human review workflow has
explicitly promoted them.

## 2026-05-15: Put Review Queue Access Behind Reusable DTOs Before UI

The first review workflow implementation should expose SQLite review state
through a small Pydantic access layer before adding FastAPI or a review UI. Queue
items, publication summaries, publication detail records, ontology links, legacy
reference values, and simple status updates are DTOs that can be reused by CLI,
API endpoints, and later UI screens.

The CLI is the first consumer of that layer. It can list queues, list open
`legacy_identity_review` items, show publication details, and update review item
status with an optional note. These operations mutate only operational SQLite
review state and do not alter Initial Load JSONL snapshots or run manifests.

## 2026-05-15: Use FastAPI As The First Local Review API Layer

The first web-facing review layer uses FastAPI and Uvicorn as a thin local API
over the existing `marygenai.review` DTOs and SQLite repository. It reads
`data/db/marygenai.sqlite` by default, returns clear service errors when the
operational database is missing or uninitialized, and exposes health, queue,
review item, publication detail, and review status update endpoints.

This keeps the future review UI decoupled from the CLI while preserving the same
local-first persistence boundary: status updates mutate only operational SQLite
review state, optional notes are stored in review item metadata history, and
Initial Load JSONL snapshots remain immutable audit artifacts.

## 2026-05-16: Serve The First Review UI As Static FastAPI Assets

The first visual review surface is a small static HTML/CSS/JavaScript UI mounted
on the existing FastAPI review app at `/ui`, with assets under
`marygenai.review_ui`. It consumes the existing health, queue, detail, and status
update endpoints for the `legacy_identity_review` queue.

This avoids adding a separate Node or React build system before the review
workflow is better understood, while still preserving an explicit `review-ui`
CLI boundary for future containerization or frontend replacement. The UI remains
local-first, internal, and focused on review and curation rather than clinical or
public product behavior.

## 2026-05-16: Separate Identity Decisions From Review Item Status

Legacy identity review now stores structured curation decisions in a dedicated
SQLite `review_decision` table instead of overloading `review_item.status`.
Review item status remains operational workflow state, while identity decisions
are append-only records that preserve reviewer identity, reviewed PMID, PMCID,
DOI, canonical URL, rationale, original identity signals, timestamp, software
version, and decision schema provenance.

This keeps the local UI useful for real curation without making JSONL snapshots
mutable or treating a workflow transition as reviewed knowledge. The same shape
can later generalize to field-level ontology, extraction, inclusion, and evidence
review decisions.

## 2026-05-16: Apply Identity Decisions To Workflow Explicitly

Saving a structured legacy identity decision does not automatically close a
review item. Workflow advancement is a separate explicit operation that applies
the latest saved legacy identity decision to the local SQLite review item.

`confirmed_identity` and `corrected_identity` mark the item `resolved` because
the publication identity has enough reviewer-confirmed information to leave the
identity queue. `not_same_publication` marks the item `dismissed` because the
queued legacy association should not continue as the same publication identity.
`unresolved` remains a saved curation decision but cannot close the workflow
item.

The application writes provenance into `review_item.metadata_json`, including
`status_history` and `last_identity_decision_application`, and leaves Initial
Load JSONL snapshots unchanged.

## 2026-05-18: Open Post-Legacy Enrichment With PubMed Candidate Staging

The first enrichment loop beyond the private bootstrap uses PubMed as the primary
source for publication discovery and metadata. Discovery is anchored to the
latest baseline publication year available in local SQLite and starts with a
small default overlap window so records near the boundary can be classified
instead of silently skipped.

The MVP reuses the validated PubMed POC parser and scoring logic, but writes
MVP-shaped snapshots under ignored `data/` paths and persists only operational
state to SQLite. PubMed results are classified against the legacy index as
`in_legacy_exact`, `possible_legacy_match`,
`needs_manual_identity_review`, or `new_candidate`. Exact legacy matches remain
audit outputs only. Non-exact candidates are stored as `needs_review`
publication records, receive a `publication_candidate_discovery` provenance row,
and enter the `publication_candidate_review` queue.

This deliberately does not mutate Initial Load JSONL snapshots and does not
treat discovered PubMed candidates as reviewed knowledge. `cannabinoid_focus`
continues to dominate review priority; citation metrics and other influence
signals remain secondary enrichments.

## 2026-05-18: Keep Private Legacy Data Out Of The Public Repository

MaryGenAI is now documented as a public project, but the maintainer's original
legacy exports remain private and must not be committed. They are high-trust
bootstrap inputs for the maintainer's local workflow, not public fixtures or
project dependencies.

Public users should eventually start from reviewed snapshots exported by
MaryGenAI. Until those snapshots exist, public contributors can run tests, inspect
source adapters, and work on reproducible PubMed/source workflows, but they
should not expect the private legacy CSVs or local SQLite database to be present.

Documentation should distinguish private maintainer bootstrap state from public
capabilities. The `legacy_identity_review` queue is only the weaker-identity
subset of the private bootstrap, not the full set of useful legacy records.

## 2026-05-18: Backfill PubMed Candidates Month By Month From January 2024

The immediate enrichment workflow is to run PubMed discovery in explicit monthly
publication-date windows from `2024/01/01` through the current date. This gives
the maintainer small, auditable batches to classify for relevance and identity
before access enrichment or field extraction.

The January 2024 start date intentionally overlaps with the private bootstrap,
which includes records through 2024. Overlap is useful because PubMed results can
be classified as `in_legacy_exact`, `possible_legacy_match`,
`needs_manual_identity_review`, or `new_candidate` instead of assuming every
2024+ record is new.

## 2026-05-18: Treat Monthly PubMed Windows As Audit Batches, Not Unique Backlog Counts

The first January-June 2024 PubMed discovery runs showed duplicate PMIDs across
different monthly publication-date windows. The PubMed query translation included
the requested `Date - Publication` bounds, so this appears to be a source
metadata behavior rather than a local command error.

Monthly JSONL candidate and review-item counts should therefore be read as audit
counts for that source window. SQLite remains the operational source of truth for
unique candidates because `publication_candidate_discovery` and
`publication_candidate_review` are keyed by canonical publication document id.

Future PubMed discovery should also persist raw ESearch and EFetch payloads under
`data/raw/pubmed/`, not only source request metadata and normalized snapshots, so
date-window behavior and parser decisions can be audited more directly.

## 2026-05-19: Keep Review Status Vocabulary Explicit For Onboarding

MaryGenAI now documents review status semantics in
`docs/review_status_guide.md` because the MVP has multiple related state layers:
queue workflow status, document review state, PubMed candidate identity status,
and structured identity decisions.

The project should keep these layers separate in UI, API, CLI, and documentation.
For example, `review_item.status='resolved'` closes a local workflow item, while
`publication_candidate_discovery.identity_status='new_candidate'` describes the
candidate's relationship to the baseline. Neither status alone makes a PubMed
candidate reviewed knowledge.

## 2026-05-20: Allow Parallel Access Enrichment Without Reviewed-Knowledge Promotion

Human review of PubMed candidates will be slower than discovery and access
classification. The MVP should therefore allow targeted access/full-text
enrichment to run in parallel with review for prioritized candidates, while
keeping all retrieved files, parsed text, and extracted fields as candidate
evidence.

This does not change the review boundary. `needs_manual_identity_review`
candidates should be identity-reviewed before file retrieval or downstream
extraction, and no PubMed discovery or downloaded artifact becomes reviewed
knowledge automatically. The preferred retrieval order remains HTML/XML first:
PMC HTML/NXML when `PMCID` exists, Europe PMC XML/full-text metadata next,
Unpaywall open-access locations for DOI-backed records, and narrow PDF fallback
only for selected records.

All raw payloads, downloaded files, and parsed text outputs should stay under
ignored `data/` paths and preserve source, method, timestamp, access/license
metadata, file hash, and errors.

## 2026-05-24: Evaluate ScienceDirect PII As A Legacy Identity Signal

Many `legacy_identity_review` items have ScienceDirect URLs whose `/pii/...`
segment contains a Publisher Item Identifier. The MVP should evaluate that PII
as an identity-resolution signal before asking a human reviewer to search by
hand.

The first POC path is intentionally audit-only: extract PII from review-queue
URLs, query Crossref/OpenAlex and optional Elsevier for DOI candidates, then
query PubMed by DOI for PMID/PMCID. Outputs remain under ignored `data/` paths
and do not update review state or create structured identity decisions
automatically. In a local 3-item ScienceDirect sample, Crossref matched the PII
as an `alternative-id`, recovered DOI, and PubMed recovered PMID for all 3
items; PMCID was not present in that sample.

## 2026-05-25: Treat Strong Legacy Identity Resolution As An Audited Transition

ScienceDirect PII recovery should become the first audited transition from
legacy identity review toward stronger bibliographic identity, not a one-off
queue cleanup. The first local full ScienceDirect run recovered DOI for all
resolved ScienceDirect PII records and PMID for most of them, which makes it a
good pilot for applying conservative identity decisions.

The next command should read POC JSONL records, classify each item into
`gold_identity_seed`, `auto_identity_resolved`, `ambiguous_identity`, or
`needs_manual_identity_review`, and support `--dry-run` before writing any
SQLite updates. Automatic identity resolution should require auditable evidence
such as a ScienceDirect PII, a Crossref candidate whose `alternative-id` matches
that PII, high title similarity, compatible publication year, and a recovered
DOI. PubMed PMID/PMCID evidence should strengthen the classification but should
not be required for every legacy record to leave identity review.

Applying a resolution must preserve provenance and should not erase history:
write recovered identifiers and structured review evidence, then close the local
identity-review workflow item only when the confidence rule passes. This same
identity-confidence layer should later validate legacy records that already have
apparently strong identifiers, while PubMed-discovered records can start with
high bibliographic identity confidence because PMID is source-native evidence.

## 2026-05-25: Use English Legacy Export As LLM Triage Context

The maintainer-local English legacy HTML export should be normalized as an
additional context layer for LLM triage, not as a replacement for the current
Portuguese Cannadocs bootstrap. The English export contains fields such as
`Key Findings`, `Type of Study`, `Study Result`, cannabinoid fields, dosing
fields, clinical relevance, and adverse events in English, which reduces
translation noise when prompting hosted or local LLMs.

The export is page-oriented and contains repeated studies across condition,
cannabinoid, and organ-system pages. The normalization step should deduplicate
by strong identifiers first, then URL/title keys, aggregate repeated filenames
and curated English fields, and link the resulting records back to local SQLite
documents by PMID, PMCID, DOI, canonical URL, or normalized title/year. Outputs
remain under ignored `data/normalized/legacy_english_context/` and are
audit-only.

This English context should become the default input for the first large-scale
Groq triage runner. Full text remains useful for later evidence extraction, but
LLM triage should be allowed to start from curated English legacy metadata so
thousands of records can be prioritized without waiting for all downloads.

## 2026-05-25: Separate Local Identity Validation From LLM Scientific Triage

Identity validation and scientific/medical triage should use different model
paths. Identity validation should be primarily deterministic and local:
identifier equality for PMID, PMCID, DOI, PII, and canonical URLs; publication
year compatibility; title normalization; fuzzy title comparison; and local
embedding similarity with a small sentence-transformer model such as
`all-MiniLM-L6-v2`. This should be fast, cheap, repeatable, and suitable for the
full legacy set.

Hosted LLMs such as Groq should be reserved for tasks that require semantic
interpretation: study-design triage, human/animal/in-vitro classification,
cannabinoid relevance, condition/pathology grouping, evidence-priority buckets,
and concise reviewer-facing rationales. Groq can also be used as a fallback for
ambiguous identity cases, but not as the default identity linker.

The recommended workflow is therefore:

1. Build deduplicated English legacy context.
2. Link/validate identity locally with identifiers, rules, and embeddings.
3. Split records into exact, strong, ambiguous, and no-match identity buckets.
4. Run Groq triage first on exact/strong records with checkpointed batch output.
5. Keep ambiguous identity records out of downstream LLM medical triage until
   their identity is resolved or explicitly reviewed.

## 2026-05-28: Test Evidence Synthesis Before Broad Structured Extraction

The first Groq study-reclassification batches showed that broad structured
extraction can over-infer fields such as condition, organ system, cannabinoid
role, route, dosage, and comparator when the task and context packet are too
generic. The next POC layer should therefore test a narrower evidence-synthesis
step before downstream extraction.

For long studies, the pipeline should first retrieve task-relevant chunks, then
compress those chunks into short verbatim spans with stable `span_id` and
`chunk_id` provenance. An LLM may then create a concise task-specific synthesis,
but every claim must cite source spans and mark missing or conflicting evidence.
The legacy English context remains a guardrail and comparison baseline, not
absolute truth.

The evaluation baseline remains direct narrow-task chunk extraction. Synthesis is
useful only if it improves faithfulness and schema discipline while preserving
auditability for human review. High-tier models should be considered for
adjudication and hard conflict resolution after the task and evidence packet
shape are stable, not as a substitute for a well-scoped extraction task.

## 2026-05-31: Prefer Semantic Document Units Over Narrative Synthesis For The Next LLM Classification POC

The current LLM reclassification POC should advance through semantic document
units rather than free-form article synthesis. Source artifacts are converted
into literal cleaned units with stable ids, including paragraphs, abstract text,
tables, and figure captions. These units can be labeled as candidate retrieval
metadata, then selected per downstream task family:
`condition_classification`, `cannabinoid_classification`, and
`study_classification`.

The 4-document OpenAI test showed that this structure is promising for
auditability and for detecting legacy/source mismatches. It also exposed two
prompt requirements that should remain in the contract: `evidence_text` must be
one contiguous verbatim substring from cited units, and legacy alignment must be
`conflicts` when source units and legacy context describe different studies,
conditions, interventions, or populations.

The next experiment should expand the same pipeline to a larger stratified
sample, add cost/throughput metrics for preparation and classification, and only
then test whether a local hybrid retrieval store such as ChromaDB, or later a
Qdrant-style service, improves unit selection. Groq and Cerebras remain better
candidates for narrower later-stage tasks after robust models have prepared or
selected the relevant evidence context.

## 2026-06-01: Test Segment-Specific Unit Contracts Before Agentic Retrieval

Before adding an agentic retrieval loop or a vector store to classification, the
POC should test whether segment-specific output contracts reduce hallucination,
evidence stitching, and review burden using the same literal document units.
The first segment contracts are `clinical_intervention`,
`preclinical_mechanistic`, and `evidence_synthesis`, with the legacy English
study type used as a routing hint rather than reviewed truth.

The legacy English context remains a guardrail and alignment baseline. It must
not be cited as source evidence in local grounding audits. Source support should
come from selected document units only; `legacy_alignment` may reference
selected source units through `source_unit_ids`, while quote-bearing fields use
`cited_unit_ids` plus short contiguous `evidence_text`.

A first OpenAI run over 15 selected documents produced no API or parsing errors
and showed that the segmented approach is worth continuing, but the evidence
quote contract still needs a narrow repair pass. The main remaining grounding
failure pattern is overlong quote text rather than unsupported source claims.
This suggests improving quote-length discipline and repair/adjudication before
increasing sample size or adopting ChromaDB/hybrid retrieval as part of the
pipeline.

The follow-up segmented repair pass fixed all four grounding failures from the
15-document run without API or parsing errors. This supports a two-step
classification shape for the next larger sample: first run one segment-specific
contract per document, then run a narrow repair/adjudication command only for
records that fail local grounding. The observed failures do not yet justify a
more agentic retrieval loop; the cheaper next test is to expand the segmented
sample and compare final post-repair grounding, review burden, and token cost by
pipeline.

A broader balanced 30-document run produced no API/parsing errors and reached
30/30 local grounding after repairing three records. The main quality signal
shifted from quote grounding to source sufficiency: 16/30 final records still
needed human review, often because selected source units did not contain
scientific article content, did not match the legacy context, or did not support
the legacy study-type claim. This supports continuing with a larger segmented
sample, but the next analysis should separate true model behavior from upstream
source/unit extraction quality before adding vector retrieval or agentic
retrieval tools.

## 2026-06-03: Audit Source Unit Quality Before LLM Classification

The next POC should add a source/unit quality audit after access enrichment and
source unit extraction, before semantic labeling, retrieval, or segmented LLM
classification. This should remain a POC command until thresholds are validated
against manual review; it should write ignored JSONL outputs only and must not
mutate SQLite review state or reviewed knowledge.

Manual review of representative segmented records showed distinct upstream
quality and routing cases:

- `PMC2011510`: effectively abstract-only plus license/reference boilerplate;
  the abstract supports basic clinical classification, but full methods/results
  would require OCR or another text source.
- `PMC2228252`: rich full-text NXML with enough scientific units for direct
  classification.
- `PMC2294085`: source text supports a narrative review mention of
  cannabinoids, but not the legacy `Meta-analysis` classification or a strong
  positive evidence-synthesis conclusion.
- `PMC10466388`: source text is good, but cannabinoid relevance is indirect;
  Tai Chi is the intervention and endocannabinoids are biomarkers.
- `publication:url:0c4ab371df7dff5b`: selected source and legacy context
  describe different studies; the source is a BUP/SAM randomized trial, not the
  legacy clinical meta-analysis.
- `PMC8039032`: persisted source text is Recaptcha/JavaScript boilerplate and
  should be blocked before LLM classification.

The POC should produce candidate provenance fields such as `quality_bucket`,
`routing_recommendation`, `unit_count`, `scientific_unit_count`,
`boilerplate_unit_count`, `has_abstract`, `has_methods`, `has_results`,
`has_discussion`, `recaptcha_or_js_detected`, `needs_ocr`,
`needs_source_repair`, and `cannabinoid_focus_score`. Initial buckets to test
are `full_text_rich`, `abstract_only`, `abstract_plus_boilerplate`,
`boilerplate_heavy`, `recaptcha_or_js`, `image_pdf_or_scan`, `metadata_only`,
`low_cannabinoid_focus`, and `biomarker_only`.

## 2026-05-20: Persist Access Artifacts As Candidate Evidence

The first operational access enrichment command now selects prioritized PubMed
candidates from `publication_candidate_discovery` and writes both file snapshots
and SQLite artifact rows. The SQLite table is intentionally named
`access_enrichment_artifact` and stores source, artifact type, access class, URL,
license, payload path, payload hash, raw payload JSON when applicable, errors,
provenance, document id, and run id.

This is operational provenance, not reviewed knowledge. Access enrichment
manifests are loaded into `run_manifest`, but candidate documents remain
`review_state='needs_review'`, prior Initial Load JSONL snapshots are not
rewritten, and downstream extraction still requires a separate review boundary
before any field can enter reviewed exports.
