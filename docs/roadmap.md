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

- legacy validation: use the legacy dataset to test the full local workflow end to
  end;
- new discovery: use PubMed queries to estimate how many additional candidate
  studies exist beyond the legacy dataset.

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

## Recommended Next Session

### POC 6c: Review Export And Better Evidence Selection

Status: proposed next.

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

After POC 6c, the best next branch is the PubMed discovery expansion POC below.

## Parallel Future Track

After POC 6b, run a PubMed discovery expansion POC to estimate additional
candidate studies beyond the legacy dataset.

Priority queries should focus on higher-reputation evidence:

- cannabinoid systematic reviews;
- cannabinoid meta-analyses;
- randomized controlled trials;
- controlled clinical trials;
- double-blind trials;
- placebo-controlled studies;
- condition-specific high-priority areas such as pain, epilepsy, adverse effects,
  dependence, anxiety, cancer, and inflammation.

This discovery track should answer:

- how many new PubMed records are outside the legacy dataset;
- how many have DOI/`PMCID`;
- how many are systematic reviews, meta-analyses, or controlled trials;
- how much overlap exists with the 7,347 legacy rows;
- whether PubMed queries alone are sufficient as the ongoing study detection
  mechanism.
