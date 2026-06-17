# Roadmap

This roadmap captures the current working plan for the publication-source and
candidate-classification track. It should be updated whenever a POC changes the
next step, source strategy, or classification strategy.

The current source-availability gate is documented in
[Source Availability Assessment](source_availability_assessment.md). Downstream
LLM classification was intentionally deferred until source availability could be
tested. The original target was 5,000+ source texts; after the June 2026
source-acquisition POCs, the legacy-only ceiling appears closer to roughly
3,100-3,400 classification/source-ready texts. The project is therefore pivoting
from a review-first knowledge-base MVP to a source-intelligence and
candidate-classification engine that can grow through PubMed discovery and expose
candidate classifications for later review.

## Current Strategy

MaryGenAI should use PubMed as the primary source for discovering new
publication records and anchoring publication identity. PubMed is not the
crawler for files. The current product step is a local MVP for source
intelligence, classification-ready corpus preparation, and candidate
classification using the validated POC outputs. Semantic Scholar remains useful
as a later enrichment source, but it is not a blocker for the first MVP shape.

The pipeline shape should be:

1. Discover candidate studies in PubMed.
2. Normalize identity and metadata around `PMID`, DOI, and `PMCID`.
3. Prioritize higher-reputation study types for review, especially systematic
   reviews, meta-analyses, randomized/controlled clinical trials, and other
   controlled designs.
4. Enrich access paths through PMC OAI-PMH, NCBI ELink, OpenAlex, Unpaywall,
   DOI, and publisher/repository links.
5. Audit persisted access artifacts before source-unit labeling or LLM
   classification.
6. Acquire source text through official or source-declared routes first, keeping
   PMC OAI-PMH and digital PDF extraction ahead of publisher-page scraping.
7. Build a deduplicated classification corpus rollup with source quality,
   provenance, ontology links, study type, and condition labels.
8. Run stratified AI classification POCs on source-ready documents, using a
   100-document cost and quality gate before any corpus-scale run.
9. Expose candidate-classified scientific documents through read-only retrieval
   surfaces, potentially an MCP server, while keeping human-reviewed knowledge as
   a higher trust layer.

This preserves two separate tracks:

- maintainer bootstrap validation: use the private curated bootstrap as a trusted
  reference for identity, inclusion, study classification, conditions, compounds,
  and any populated field values;
- new discovery: use PubMed queries to find relevant studies outside the legacy
  dataset, then prioritize them for access enrichment and review.

The maintainer's private bootstrap is a high-trust curated reference produced
with physician involvement. It should not be treated as disposable historical
data, but it is also not public repository content. When a bootstrap field is
populated, it can be used as a strong reference value for comparison and review.
When a field is absent, especially dosage or treatment duration, the pipeline
should distinguish between `not_reported`, `not_applicable`, and
`needs_more_evidence` rather than assuming an extraction failure.

The public project should eventually publish source-intelligence snapshots,
candidate classification outputs, and reviewed snapshots as separate trust
levels. Reviewed snapshots remain the highest-trust baseline, but candidate
classification outputs can still be useful for retrieval and triage when clearly
labeled.

The MVP review queue should be dominated by `cannabinoid_focus`. Records with
direct cannabinoid evidence in title or indexed PubMed metadata are the primary
review candidates. Study design, access, recency, and citation metrics are
secondary signals.

## Current Dataset And Classification Direction

The next workstream is defined in
[Classification Dataset Plan](classification_dataset_plan.md). In short:

- freeze a classification corpus rollup from the current legacy-core source
  acquisition outputs;
- use the strict corpus of about 3,149 classification-ready legacy-core
  documents as the first working dataset;
- keep a broader source-ready set of about 3,374 documents as a secondary queue
  for prompt/schema validation and detector tuning;
- use `gpt-5.4-mini` as the current default POC classifier after same-document
  comparisons against `gpt-4.1` and `gpt-5.4-nano`;
- discard `gpt-5.4-nano` from the default path for now because it confused
  nearby schema fields in difficult records;
- run a 100-document stratified cost and quality gate across high-coverage
  condition areas such as pain, addiction/cannabis, epilepsy, anxiety,
  depression, psychosis, cancer, and inflammation before mass classification;
- define candidate classification outputs as reviewable evidence, not final
  knowledge.

## Access Artifact Quality Roadmap

The LLM study reclassification POC showed that grounded classification is no
longer the dominant near-term bottleneck. Source sufficiency, source-unit
quality, and legacy/source mismatch are now the gating risks. The current local
artifact audit found only about 1,300 classification-ready full-text documents,
which is not enough for the original automation goal.

Access enrichment should therefore become a quality-gated workflow:

1. Audit every persisted `access_enrichment_artifact` locally, without network
   fetches or SQLite/review-state mutation.
2. Mark artifact-level operational quality in ignored JSONL outputs:
   `usable_full_text`, `invalid_payload`, `missing_payload`, `metadata_only`, or
   `error`.
3. Build a document-level rollup that preserves the best usable source and
   separates routing states:
   `usable_for_llm_classification`, `needs_reenrichment`,
   `source_triage_needed`, and `not_enriched`.
4. Reprocess only documents with invalid full-text artifacts, using a different
   enrichment strategy rather than blindly retrying the same source.
5. Keep low-cannabinoid-focus and likely source/legacy mismatch cases separate
   from reenrichment. Those belong in identity/focus review, not automatic
   fetch retry.

Operational queues should stay distinct:

- `reenrich_invalid_payload`: Recaptcha/JavaScript pages, HTML saved as XML,
  missing payloads, parser-hostile full-text artifacts.
- `source_triage_needed`: abstract-only, metadata-only, or
  abstract-plus-boilerplate records where a better source may exist but is not
  currently available locally.
- `identity_or_focus_review`: low cannabinoid focus, biomarker-only focus, and
  suspected legacy/source mismatch.

Invalid artifacts should not be deleted. They are evidence of source access
failure and should remain available for audit, while downstream extraction
should ignore them as full-text sources.

Current audit command:

```bash
uv run marygenai access-enrichment audit-artifacts
```

The first artifact-level audit should distinguish Recaptcha/JavaScript blocks
from HTML returned through an XML endpoint. Recaptcha/JavaScript blocks usually
need alternate-source reenrichment. HTML returned through an XML endpoint may be
usable source text but should be repaired or normalized as an HTML artifact so
future routing does not treat it as structured NXML.

## Source Acquisition Roadmap

Status: first official-source fetch router POC implemented and exhausted for the
initial legacy-core acquisition campaign in June 2026.

Current operational path:

1. Build a local route plan for non-usable legacy-core records.
2. Acquire PMC OAI-PMH XML/text for local or Europe PMC-discovered PMCIDs.
3. Acquire Unpaywall PDF URLs and extract digital PDF text with PyMuPDF.
4. Run NCBI ELink and OpenAlex as access/identity augmentation sources.
5. Acquire prioritized augmented links, filtering out non-source link surfaces
   and preferring PMC OAI-PMH, PDF-like links, selected repositories/publishers,
   and DOI landing pages.
6. Treat OCR as a residual route for PDFs that retrieve but produce too little
   text, not as the default PDF strategy.
7. Stop treating additional legacy acquisition as the main unblocker once the
   route queue is exhausted; shift effort to corpus rollup, candidate
   classification, and PubMed discovery expansion.

Current POC commands:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router route
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-pmc-oai --limit 100
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-unpaywall-pdf --limit 50
uv run python -m pocs.official_source_fetch_router.fetch_router augment-ncbi-elink --limit 200
uv run python -m pocs.official_source_fetch_router.fetch_router augment-openalex --limit 200
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-augmented-links --limit 100
```

These commands write ignored local artifacts under `data/`. They do not mutate
SQLite, review queues, review decisions, or reviewed knowledge.

## MVP Implementation Progress

Current operational focus: harden the classification corpus rollup, strict
schema, and provider-backed classifier around a 100-document validation gate.
PubMed discovery remains the main route for growing beyond the legacy-only
ceiling.

### MVP Initial Load

Status: first implementation completed on 2026-05-15.

Implementation:

- adds `uv run marygenai initial-load setup-data` for the ignored local data
  layout;
- adds `uv run marygenai initial-load run` for the legacy import;
- imports legacy studies into canonical publication candidates;
- imports legacy ontology CSVs into normalized ontology entities;
- creates document-to-ontology links from legacy study IDs;
- writes JSONL snapshots and run manifests under ignored `data/` paths;
- prepares SQLite helpers without choosing a final operational database yet.

First local run:

- 7,780 source records;
- 7,347 publication candidates;
- 433 ontology entities;
- 42,061 document-to-ontology links.

The `legacy_identity_review` queue contains about 1,206 weaker-identity records
that lack PMID, PMCID, and DOI. It is not the full useful bootstrap corpus.

### MVP PubMed Candidate Discovery

Status: first implementation completed on 2026-05-18.

Implementation:

- adds `uv run marygenai pubmed-discovery run` for bounded PubMed discovery
  windows;
- writes ignored PubMed source records, normalized candidate enrichments, review
  item snapshots, source-window summaries, and run manifests under `data/`;
- classifies candidates as `in_legacy_exact`, `possible_legacy_match`,
  `needs_manual_identity_review`, or `new_candidate`;
- persists non-exact candidates as `needs_review` publication records;
- opens the `publication_candidate_review` queue;
- exposes candidate listing and provenance through the local API.

Current backfill plan:

```bash
uv run marygenai pubmed-discovery run --datetype pdat --mindate 2024/01/01 --maxdate 2024/01/31 --retmax 100
```

Early January-June 2024 runs showed that PubMed monthly windows can overlap by
PMID. Monthly JSONL counts are therefore audit counts, not unique backlog counts.
The SQLite `publication_candidate_discovery` table and
`publication_candidate_review` queue are the operational source for unique
candidates.

## Completed POCs

### POC 1: Expanded PubMed Metadata

Status: completed first validation pass on 2026-05-13.

Key result:

- 790 PubMed records normalized across 8 query families;
- DOI coverage: 768 / 790;
- `PMCID` coverage: 415 / 790;
- abstract coverage: 778 / 790.

Conclusion: PubMed is strong enough to remain the main publication identity and
metadata hub.

### POC 2: Legacy Reconciliation

Status: completed first local-only pass on 2026-05-13.

Key result:

- 7,347 legacy study rows parsed;
- 6,140 rows, or 83.6%, had directly extractable `PMID`, `PMCID`, or DOI;
- 1,207 rows need resolver or manual review.

Conclusion: the private bootstrap is suitable for validating the process end to
end.

### POC 3: Link Resolver

Status: completed first local-only pass on 2026-05-13.

Key result:

- 1,676 direct PMC full-text paths;
- 3,805 PMID-only records;
- 659 DOI-only records;
- 1,207 publisher-only records.

Conclusion: the resolver should classify access before any file download.

### POC 4: Europe PMC And Unpaywall Enrichment

Status: completed first sampled pass on 2026-05-13.

Key result:

- 20 sampled records enriched;
- Europe PMC found 15 / 20;
- Unpaywall found 16 / 20;
- 10 records had open-access PDF candidates;
- 0 enrichment errors.

Conclusion: Europe PMC and Unpaywall are useful enrichment sources. Europe PMC can
discover DOI/`PMCID` for PMID-only records, and those DOI values can feed Unpaywall
in the same pass.

### POC 7: Legacy-Anchored PubMed Discovery

Status: implemented and validated on 2026-05-14 and 2026-05-15.

Goal: discover strong-evidence PubMed records outside the private bootstrap.

Implementation:

- reads the latest private bootstrap reconciliation records and builds an identity index from
  `PMID`, `PMCID`, DOI, canonical URL, and normalized title;
- runs strong-evidence PubMed queries for systematic reviews, meta-analyses,
  randomized/controlled trials, double-blind and placebo-controlled studies across
  pain, epilepsy, adverse effects, dependence, anxiety, cancer, and inflammation;
- classifies results as exact legacy matches, possible legacy matches, new
  candidates, or manual identity-review records;
- exports scored JSONL and CSV files for review without retrieving full text or
  downloading PDFs.
- ranks study design with the current evidence hierarchy:
  `Case Report < Case Series < Case-Control < Cohort Study <
  Controlled Clinical Trial < Randomized Controlled Trial < Systematic Review <
  Meta-Analysis`.

Expected command:

```bash
uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100
```

### POC 8: NIH iCite Citation Enrichment

Status: completed first recent-window and older-window validation on 2026-05-15.

Goal: evaluate the cost-benefit of enriching PubMed discovery candidates with
citation and influence metrics.

Implementation:

- reads a PubMed discovery records JSONL/CSV, defaulting to the latest
  `*_pubmed_discovery_records.jsonl`;
- queries NIH iCite in PMID batches of up to 200;
- preserves PubMed `priority_score`, `study_design_rank`, `cannabinoid_focus`, and
  `full_text_review_priority`;
- adds separate `icite_*` fields for citation count / cited-by PMID count,
  Relative Citation Ratio, NIH percentile, clinical citation signals,
  human/animal/molecular-cellular orientation, and Approximate Potential to
  Translate when available;
- computes a separate `citation_priority_score` for review queue experiments;
- writes a local `_manifest.json` keyed by input path and file hash so the same
  input is not queried repeatedly by default.

Expected command:

```bash
uv run python -m pocs.icite_enrichment.enrich_icite run \
  --input-path data/normalized/pubmed_discovery/pdat/2026-04/20260514T220709Z_pubmed_discovery_records.jsonl
```

Validation runs:

- April 2026 recent-window discovery was enriched as the initial low-citation
  maturity test.
- April 2025 publication-date discovery produced 67 deduplicated records:
  64 `new_candidate` and 3 `in_legacy_exact`.
- April 2025 iCite enrichment found metrics for 67 / 67 PMIDs in one API batch.
- April 2025 `citation_priority_score` ranged from 5 to 85.

Key result: citation metrics are useful secondary signals, but citation-only
ordering is not safe. In April 2025, the citation sort surfaced some relevant
records, but it also promoted weak cannabinoid-focus false positives with high
citation velocity. It also buried strong recent candidates with low citation
maturity, including systematic reviews and randomized trials that ranked highly
by PubMed discovery score.

Conclusion: make `cannabinoid_focus` the dominant review signal. Use
`priority_score`, `study_design_rank`, and `full_text_review_priority` as
secondary sort inputs, and use iCite fields as optional audit columns, not as
replacements for cannabinoid relevance, evidence design, or human review
requirements.

Next evaluation: defer additional iCite work unless a specific review question
needs citation metrics. The MVP should prioritize legacy validation, incremental
discovery, enrichment, and review workflows first.

## Upcoming Engineering Improvements

- Persist raw PubMed ESearch and EFetch payloads for MVP discovery runs under
  `data/raw/pubmed/`.
- Add a run-audit command that reports per-window counts, duplicate PMIDs across
  windows, unique candidate totals, and queue totals.
- Add optional skip/resume behavior to the monthly backfill helper after the raw
  payload layout is in place.

## LLM Evidence Classification Track

Status: active POC branch as of 2026-05-31.

The LLM study-reclassification work remains audit-only. It must not mutate
SQLite review state, reviewed knowledge, identity decisions, or public snapshots.
Outputs are candidate evidence for human review.

Current preferred pipeline branch:

1. Convert already available source artifacts into literal cleaned document
   units: paragraphs, abstract text, tables, and figure captions.
2. Assign stable `unit_id`s and candidate semantic labels for retrieval.
3. Select units per downstream task family.
4. Classify task families with a robust model using cited `unit_id`s and
   contiguous verbatim `evidence_text`.
5. Compare outputs against the legacy English context as a guardrail, preserving
   conflicts for human review.

The first 4-document OpenAI run suggests this is more promising than free-form
narrative synthesis for the next classification pipeline iteration. It improved
auditability and surfaced likely legacy/source mismatches, especially where the
selected article text did not support cannabinoid claims present in the legacy
context.

Next LLM POC steps:

- expand the same document-unit preparation and task-family classification to a
  larger stratified sample;
- record preparation and classification metrics separately: prompt chars, rough
  token estimates, latency, provider/model, grounding pass rate, unsupported
  evidence counts, errors, and human-review flags;
- evaluate deterministic label/keyword retrieval before adding a retrieval
  store;
- test ChromaDB as the first local vector/hybrid retrieval POC only if larger
  runs show deterministic unit selection failure modes;
- keep Qdrant as a later service candidate if retrieval storage becomes useful;
- keep Groq and Cerebras as candidates for narrower later-stage tasks after
  robust models prepare or select relevant evidence context.

## Recent POCs

### POC 6: Small Full-Text And PDF Sample

Status: completed first small HTML/XML-first pass on 2026-05-13.

Goal: test extraction value and difficulty on a small, mixed sample from the access
resolver outputs.

Sample categories:

- PMC HTML/full text from direct `PMCID` records;
- Europe PMC full-text HTML/PDF candidates;
- Unpaywall PDF candidates;
- a few difficult publisher-only records, if they can be resolved without fragile
  scraping.

Questions:

- Which full-text formats extract cleanly?
- Which records require PDF parsing versus HTML parsing?
- Which records require OCR or should be rejected?
- Which fields are actually improved by full text compared with PubMed metadata
  and abstracts?
- Which extraction outputs require human review before they can enter the
  knowledge base?

Fields to test:

- dosage;
- treatment duration;
- adverse events;
- route of administration;
- protocol/intervention details;
- arms, comparators, and control groups;
- study design;
- population details.

Guardrails:

- do not build a large PDF ingestion pipeline yet;
- do not download bulk PDFs;
- do not treat publisher pages as stable crawling targets until legality and
  operational stability are understood;
- preserve raw payloads, extraction method, source URL, confidence, and review
  state for every extracted field.

First run:

- run id: `20260513T215843Z`;
- command: `uv run python pocs/pdf_samples/sample_full_text.py run`;
- sample records: 10;
- selected HTML sources: 8;
- selected XML sources: 1;
- records without usable text: 1;
- supplemental PDFs downloaded: 1;
- field extraction candidates: 58;
- all extracted fields marked `needs_review`.

Initial interpretation:

- PMC HTML is the best first-choice full-text source when `PMCID` is available.
- Europe PMC rendered article pages are not reliable non-browser fetch targets;
  use Europe PMC XML when available, otherwise fall back to PMC HTML for records
  with `PMCID`.
- Unpaywall PDF URLs are useful candidates, but publisher-hosted PDFs may return
  403 and should not be assumed retrievable.
- Heuristic extraction can surface candidate evidence, but it is too noisy for
  final normalized fields. The next extraction test should compare a small local
  or remote LLM against the saved text samples.
- HITL remains mandatory for dosage, adverse events, arms/comparators, protocol
  details, and any field inferred from full text.

### POC 6b: LLM Evidence Extraction And Schema Normalization

Status: completed first three-record comparison on 2026-05-13.

Goal: test whether LLMs add value after HTML/XML text extraction, without making
the LLM responsible for final truth.

Design:

- use the saved POC 6 text samples as inputs;
- split extraction into two stages:
  1. extract candidate evidence snippets and candidate values from section-scoped
     text;
  2. normalize candidates into strict Pydantic models;
- keep `needs_review=true` for every field candidate;
- compare local Ollama `qwen3:8b` against Groq single-record calls;
- avoid full-manifest LLM runs until rate limits, latency, and output quality are
  understood.

Early LLM observations:

- local `qwen3:8b` can produce useful narrative/evidence output, but did not
  reliably follow strict JSON instructions on long article contexts;
- Groq produced better JSON for a single case report, but back-to-back free-tier
  calls hit `429 Too Many Requests`;
- section selection and smaller prompts are likely more important than trying
  larger models first.

Deliverables:

- Pydantic schemas for field candidate extraction outputs;
- a small comparison report for at least three records: clinical dosage, case
  report, and randomized controlled trial;
- documentation of which fields are suitable for prefill versus manual-only
  review.

First POC 6b run:

- baseline run id: `20260513T225432Z`;
- Ollama run id: `20260513T225437Z`;
- Groq comparison run id: `20260513T230004Z`;
- OpenRouter router run id: `20260513T230053Z`;
- records tested: `340`, `164`, and `43`;
- all normalized output fields retained `needs_review=true`.

Findings:

- the two-stage architecture worked: candidate snippets are accepted only after
  strict Pydantic normalization;
- heuristic extraction is useful as a baseline but too noisy for final values;
- Ollama `qwen3:8b` can help find evidence in smaller contexts, but it failed
  strict JSON parsing on two of the three records;
- Groq produced parseable candidates for all three records with smaller prompts
  and a 12-second delay, but token-per-minute limits reached zero on the third
  call;
- OpenRouter free access worked through `openrouter/free` for record `164`, while
  explicit free model tests showed JSON truncation and `429` risk.

Next step before broader extraction: improve section selection, add
rate-limit-aware retry/backoff, and design a human-review export over the
normalized candidate fields.

## Recently Completed

### POC 6c: Review Export And Better Evidence Selection

Status: completed first local review-export pass on 2026-05-14.

Goal: turn the POC 6b normalized candidates into something a human reviewer can
inspect efficiently, while improving prefill quality before any larger LLM run.

Why this comes next:

- POC 6b proved the two-stage shape, but the heuristic baseline still selects
  neighboring evidence for several fields;
- Groq can produce structured candidates on small prompts, but token budget is a
  practical constraint;
- OpenRouter free models are worth occasional comparison, but are not stable
  enough to anchor the workflow;
- every candidate still needs human review, so the next bottleneck is reviewer
  ergonomics and review provenance rather than more extraction volume.

Scope:

- improve section ranking per field, especially for dosage, arms/comparators,
  adverse events, population, and study design;
- add a small review export under `data/normalized/pdf_samples` that preserves
  reviewer-ready rows with source record id, title, field, candidate value,
  evidence text, source section, provider, model, confidence, ontology version,
  extractor version, and `needs_review`;
- add rate-limit-aware retry/backoff for Groq and OpenRouter using `retry-after`
  and reset headers;
- run the improved flow again on records `340`, `164`, and `43`;
- only after reviewer-export shape looks useful, expand to the remaining saved
  POC 6 text samples.

Success criteria:

- all exported review rows retain enough provenance for a reviewer to approve,
  edit, or reject a candidate;
- field prefill quality improves on the known weak spots from POC 6b;
- remote provider failures are recorded with actionable retry/rate-limit metadata;
- no generated data or raw provider outputs are committed.

First POC 6c run:

- run id: `20260514T110018Z`;
- command: `uv run python pocs/pdf_samples/extract_evidence.py run --source-record-id 340 --source-record-id 164 --source-record-id 43`;
- records tested: `340`, `164`, and `43`;
- providers: heuristic baseline only;
- normalized fields: 20;
- review export rows: 20;
- provider errors: 0.

Implemented changes:

- field-specific section ranking for prompt selection and heuristic candidate
  ordering, with stronger section hints for dosage, adverse events, population,
  study design, and arms/comparators;
- review export rows under `data/normalized/pdf_samples` with source record id,
  title, field, candidate value, evidence text, source section, provider, model,
  confidence, ontology version, extractor version, review placeholders, and
  `needs_review=true`;
- retry/backoff support for Groq and OpenRouter calls using `retry-after` and
  rate-limit reset headers before exponential fallback;
- summaries now include review export path, review row counts, rate-limit
  headers, and retry events.

Next validation:

- run Groq and OpenRouter one provider at a time on the same three records when
  API keys and rate budget are available;
- inspect the review export with a human reviewer before expanding to the
  remaining saved POC 6 text samples.

## Recommended Next Session

### MVP 0.1: PubMed Candidate Backfill And First Enrichment Decisions

Status: current next work.

Goal: run the first operational PubMed discovery backfill month-by-month from
January 2024 through the current date, classify candidates against the
maintainer's private bootstrap, and choose which relevant candidates should enter
access and metadata enrichment.

Reference: [MVP Plan](mvp_plan.md).

Scope:

- run bounded PubMed discovery windows such as
  `--mindate 2024/01/01 --maxdate 2024/01/31`;
- preserve baseline association states from the MVP PubMed discovery command;
- enrich prioritized candidates with PubMed metadata and access classification;
- keep iCite as optional secondary enrichment, not a priority dependency;
- build a review queue where `cannabinoid_focus` is the dominant ranking signal;
- expose a review detail view that supports identity decisions, inclusion
  decisions, field correction, and review notes;
- prepare reviewed knowledge snapshots with field-level provenance so public
  users can eventually start without private legacy files.

Suggested first screens:

- dashboard for import, discovery, enrichment, and review backlog counts;
- publication queue with filters for `cannabinoid_focus`, identity state, study
  design, access class, and review state;
- review detail page with source metadata, baseline reference values, candidate
  evidence, source links, and editable decisions.

Success criteria:

- a reviewer can identify which records are baseline matches, ambiguous matches, or
  new candidates;
- direct cannabinoid-focus records reliably appear ahead of abstract-only or weak
  cannabinoid-signal records;
- citation metrics cannot promote weak cannabinoid-focus records into the primary
  queue;
- every human decision stores reviewer identity, field, original value, reviewed
  value, timestamp, notes, ontology version, extractor version, and provenance;
- reviewed exports can later feed scientific evidence search without presenting
  medical advice.
