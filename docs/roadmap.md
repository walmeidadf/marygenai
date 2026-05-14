# Roadmap

This roadmap captures the current working plan for the publication-source track.
It should be updated whenever a POC changes the next step or the source strategy.

## Current Strategy

MaryGenAI should use PubMed as the primary source for discovering new publication
records and anchoring publication identity. PubMed is not the crawler for files.

The pipeline shape should be:

1. Discover candidate studies in PubMed.
2. Normalize identity and metadata around `PMID`, DOI, and `PMCID`.
3. Prioritize higher-reputation study types for review, especially systematic
   reviews, meta-analyses, randomized/controlled clinical trials, and other
   controlled designs.
4. Enrich access paths through PMC, Europe PMC, Unpaywall, DOI, and publisher
   links.
5. Sample full text and PDFs only after access has been classified.
6. Extract high-value fields with provenance and human review, especially fields
   that abstracts rarely provide reliably.

This preserves two separate tracks:

- legacy-anchored validation: use the curated legacy dataset as a trusted
  reference for identity, inclusion, study classification, conditions, compounds,
  and any populated field values;
- new discovery: use PubMed queries to find relevant studies outside the legacy
  dataset, then prioritize them for access enrichment and review.

The legacy dataset is a high-trust curated reference produced with physician
involvement. It should not be treated as disposable historical data. When a legacy
field is populated, it can be used as a strong reference value for comparison and
review. When a field is absent, especially dosage or treatment duration, the
pipeline should distinguish between `not_reported`, `not_applicable`, and
`needs_more_evidence` rather than assuming an extraction failure.

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

Conclusion: the legacy dataset is suitable for validating the process end to end.

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

Status: implemented on 2026-05-14; first network run pending.

Goal: discover strong-evidence PubMed records outside the curated legacy dataset.

Implementation:

- reads the latest legacy reconciliation records and builds an identity index from
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

Status: implemented on 2026-05-14; first network run pending.

Goal: enrich PubMed discovery candidates with citation and influence metrics for
review prioritization.

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

Citation metrics remain prioritization signals, not evidence quality. Missing
iCite metrics are not errors, and citation data must not override study design or
human review requirements.

Next evaluation: run POC 7 and POC 8 over older publication-date windows to test
whether citation metrics improve candidate ordering once records have had time to
accumulate citations. Compare the original PubMed discovery order against
`citation_priority_score`, and explicitly watch for citation-only ranking
under-prioritizing recent but important studies.

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

### POC 7: Legacy-Anchored PubMed Discovery

Status: proposed next.

Goal: find relevant PubMed records outside the curated legacy dataset while
preserving the legacy dataset as the trusted reference for identity and inclusion.

Why this comes next:

- the project needs a repeatable way to detect new scientific publications beyond
  the 7,347 legacy study rows;
- POC 1 proved PubMed can provide strong publication identity and metadata;
- POC 2 proved most legacy rows can be anchored to `PMID`, `PMCID`, DOI, or URL;
- the missing piece is the association layer between fresh PubMed query results
  and the existing curated legacy base.

Scope:

- create a legacy identity index from the latest legacy reconciliation output,
  keyed by `PMID`, `PMCID`, DOI, canonical URL, and normalized title;
- run a small set of PubMed query families focused on high-reputation evidence:
  systematic reviews, meta-analyses, randomized trials, controlled trials,
  double-blind trials, placebo-controlled studies, and priority condition areas;
- compare every fetched PubMed record against the legacy index;
- classify each result as `in_legacy_exact`, `possible_legacy_match`,
  `new_candidate`, or `needs_manual_identity_review`;
- calculate a simple prioritization score using publication type, study design
  hints, human/animal/in-vitro signal, priority condition terms, DOI/`PMCID`
  availability, abstract availability, and full-text access hints when available;
- export review rows for new candidates and ambiguous identity matches.

Priority query areas:

- cannabinoid systematic reviews;
- cannabinoid meta-analyses;
- randomized controlled trials;
- controlled clinical trials;
- double-blind trials;
- placebo-controlled studies;
- condition-specific high-priority areas such as pain, epilepsy, adverse effects,
  dependence, anxiety, cancer, and inflammation.

Suggested outputs:

- `data/normalized/pubmed_discovery/*_records.jsonl`;
- `data/normalized/pubmed_discovery/*_legacy_matches.jsonl`;
- `data/normalized/pubmed_discovery/*_new_candidates.jsonl`;
- `data/normalized/pubmed_discovery/*_review_export.csv`;
- `data/normalized/pubmed_discovery/*_summary.json`.

Success criteria:

- every PubMed result is assigned a transparent legacy association state;
- exact matches cite the identifier or title rule that matched;
- possible matches preserve enough evidence for manual identity review;
- new candidates are prioritized by scientific relevance and available metadata;
- generated outputs remain ignored under `data/`;
- no full-text extraction or broad PDF retrieval is added in this POC.

### POC 8: HITL Review Package And Tool Evaluation

Status: proposed after POC 7.

Goal: turn candidate evidence, legacy references, and new-publication inclusion
decisions into a human-review workflow that can be tested before choosing a final
review tool.

Why this follows POC 7:

- POC 6c created field-level review rows for extracted evidence;
- POC 7 will create inclusion and identity-review rows for records outside the
  legacy base;
- the project needs one review contract that can handle both field review and
  publication inclusion review;
- Label Studio may be useful, but the contract should be validated before the
  interface choice becomes a commitment.

Review principles:

- treat populated legacy values as trusted curated reference values;
- preserve side-by-side comparison between extracted candidates and legacy
  reference values;
- distinguish `not_reported`, `not_applicable`, and `needs_more_evidence`,
  especially for dosage and treatment duration;
- keep review state field-aware, because a record can have reviewed identity or
  conditions while dosing, adverse events, or protocol details remain unreviewed.

Scope:

- read POC 6c review exports and POC 7 discovery review exports;
- enrich review rows with legacy reference values when an identity match exists;
- add comparison state such as `legacy_match`, `legacy_conflict`,
  `legacy_missing`, `legacy_not_applicable`, and `new_candidate`;
- generate a low-friction CSV review sheet for immediate reviewer testing;
- generate Label Studio task JSON for a small tool evaluation, without making
  Label Studio the fixed review system yet;
- document the minimum fields required for reviewed output: reviewer identity,
  reviewed field, original value, reviewed value, decision, timestamp, notes,
  ontology version, and extractor version.

Suggested review decisions:

- `approve`;
- `edit`;
- `reject`;
- `not_applicable`;
- `not_reported`;
- `needs_more_evidence`.

Suggested outputs:

- `data/normalized/hitl_review/*_review_sheet.csv`;
- `data/normalized/hitl_review/*_label_studio_tasks.json`;
- `data/normalized/hitl_review/*_review_contract.json`;
- `data/normalized/hitl_review/*_summary.json`.

Success criteria:

- a reviewer can inspect candidate value, evidence text, source section, provider,
  model, confidence, and legacy reference side by side;
- the workflow supports both field-level extraction review and new-publication
  inclusion review;
- the export is usable in a spreadsheet immediately;
- the same review contract can be imported into Label Studio for comparison;
- the project can decide whether Label Studio, spreadsheet review, or a custom UI
  is the next best review interface.
