# PubMed Source Plan

This document records the current action plan for PubMed/NLM as a source family.
It should be updated after each POC so the project does not keep stale roadmap notes.

## Current Position

PubMed should be treated as the primary identity and metadata hub for publications,
not as the primary full-text or PDF crawler.

PubMed is also the current primary source for detecting new candidate studies. The
working assumption is that PubMed discovers records, while PMC, Europe PMC,
Unpaywall, DOI, and publisher links enrich access and content. This keeps study
discovery separate from file retrieval and reduces legal and operational risk.

The PubMed POC now validates the basic `ESearch` plus `EFetch` flow, XML parsing,
normalized metadata output, and an expanded named-query batch runner. The first
expanded batch confirms that PubMed metadata is strong enough to remain the primary
publication identity and metadata hub, while full-text discovery still needs a
resolver step.

The legacy dataset is strongly PubMed/NLM-oriented. Initial profiling found 7,347
legacy study rows, with many URLs already pointing to PubMed or PMC pages:

- 2,820 `pubmed.ncbi.nlm.nih.gov` URLs;
- 991 old-style `www.ncbi.nlm.nih.gov/pubmed` record URLs;
- 1,676 `www.ncbi.nlm.nih.gov/pmc/articles` full-text pages;
- additional publisher URLs from ScienceDirect, MDPI, Wiley, Frontiers, Springer,
  Nature, and other domains.

This means the next useful work is to learn how much of the legacy dataset and new
search results can be anchored to stable identifiers such as `PMID`, `PMCID`, and
`DOI`, then classify full-text availability before downloading or parsing files.

The current PubMed-specific track has validated legacy-anchored discovery and
iCite citation enrichment. The next step is to shape an internal review and
curation MVP from those outputs, then use additional sources such as Semantic
Scholar as enrichment layers rather than prerequisites.

## Source Roles

### PubMed

Use PubMed for canonical publication identity and biomedical metadata:

- `PMID`;
- `DOI`;
- `PMCID` when available in the PubMed payload;
- title, abstract, journal, date, authors, language;
- MeSH headings, chemicals, keywords, and publication types;
- source provenance for query, fetch time, and E-utilities method.

### PMC

Use PMC as the first-choice full-text source when a `PMCID` is available. PMC pages
and files should be classified before any broad download strategy is considered.

### Europe PMC

Use Europe PMC as an enrichment source for full-text and open-access discovery,
especially when PubMed has `PMID` or `DOI` but no immediately obvious full-text path.

### Unpaywall

Use Unpaywall only for DOI-backed records. Its first role is to classify open-access
status, license metadata, and possible PDF locations without bulk-downloading PDFs.

### Publisher Pages

Use publisher links as a later fallback after PubMed, PMC, Europe PMC, and Unpaywall
have been evaluated. Publisher crawling has higher legal, operational, and parsing
variation risks.

## Action Plan

### POC 1: Expanded PubMed Metadata

Goal: measure PubMed metadata coverage across several small cannabinoid-focused
queries before designing a continuous crawler.

Status: completed for the first validation pass on 2026-05-13.

Run batches of 100-200 records per query family:

- broad cannabinoid query;
- cannabidiol plus epilepsy;
- THC plus pain;
- cannabis plus adverse effects;
- human, animal, in vitro, and review-focused filters where useful.

Measure availability for:

- `PMID`, `DOI`, `PMCID`;
- title, abstract, journal, publication date, authors, language;
- MeSH headings, chemicals, keywords;
- publication types and publication status;
- source-level total count and fetched count.

Deliverables:

- raw PubMed payloads under `data/raw/pubmed/`;
- normalized records under `data/normalized/pubmed/`;
- summary reports with comparable field availability metrics;
- notes on query quality, noisy result patterns, and parsing gaps.

First run:

- run id: `20260513T154941Z`;
- command: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`;
- query families: 8;
- records fetched and normalized: 790;
- summed PubMed total count across query families: 157,514.

Aggregate availability in the fetched sample:

- DOI: 768 / 790, 97.2%;
- `PMCID`: 415 / 790, 52.5%;
- abstract: 778 / 790, 98.5%;
- MeSH headings: 683 / 790, 86.5%;
- chemicals: 664 / 790, 84.1%;
- keywords: 574 / 790, 72.7%;
- publication type: 790 / 790, 100.0%;
- publication status: 790 / 790, 100.0%;
- authors: 784 / 790, 99.2%;
- journal: 790 / 790, 100.0%;
- publication date: 790 / 790, 100.0%.

Query-level counts:

| Query family | PubMed total | Records fetched | DOI | `PMCID` | Abstract |
| --- | ---: | ---: | ---: | ---: | ---: |
| `broad_cannabinoids` | 60,000 | 98 | 97 | 63 | 97 |
| `cannabidiol_epilepsy` | 1,120 | 98 | 96 | 40 | 95 |
| `thc_pain` | 1,372 | 98 | 98 | 61 | 98 |
| `cannabis_adverse_effects` | 1,610 | 99 | 94 | 43 | 93 |
| `human_cannabinoids` | 34,433 | 100 | 95 | 43 | 99 |
| `animal_cannabinoids` | 46,219 | 100 | 94 | 45 | 99 |
| `in_vitro_cannabinoids` | 3,455 | 100 | 100 | 67 | 100 |
| `review_cannabinoids` | 9,305 | 97 | 94 | 53 | 97 |

Initial interpretation:

- PubMed is highly reliable for DOI, abstract, publication metadata, journal, date,
  and authors in these relevance-sorted samples.
- `PMCID` appears in about half of the fetched records, which is enough to justify
  PMC as the first full-text path but not enough to replace Europe PMC or
  Unpaywall.
- MeSH and chemical coverage are useful but not universal, especially for records
  that are newer, not fully indexed, or outside classic biomedical indexing
  patterns.
- Some query families fetched fewer parsed articles than `retmax=100`. This should
  be investigated before productionizing any paging or incremental crawler logic.

### POC 2: Legacy Reconciliation

Goal: determine how much of the legacy study table can be anchored to stable
publication identifiers.

Status: completed for the first local-only validation pass on 2026-05-13.

Tasks:

- parse legacy study URLs into canonical URL, domain, `PMID`, `PMCID`, and possible
  DOI candidates;
- deduplicate by `PMID`, `PMCID`, DOI, and normalized title;
- measure how many legacy records resolve to PubMed, PMC, DOI, or publisher-only
  records;
- identify rows that need manual review because their title or URL does not resolve
  cleanly.

Deliverables:

- local ignored reconciliation outputs under `data/`;
- summary counts by identifier type and source domain;
- examples of strong, weak, duplicate, and unresolved matches.

First run:

- run id: `20260513T155614Z`;
- command: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`;
- input rows: 7,347;
- records with directly extracted `PMID`: 3,805;
- records with directly extracted `PMCID`: 1,676;
- records with directly extracted DOI: 659;
- records with `PMID`, `PMCID`, or DOI: 6,140 / 7,347, 83.6%;
- records left with only canonical URL and requiring resolver/manual review: 1,207.

Source class counts:

| Source class | Records |
| --- | ---: |
| `pubmed_record_page` | 3,805 |
| `publisher_or_other_url` | 1,855 |
| `pmc_full_text_page` | 1,676 |
| `ncbi_other` | 10 |
| `doi_url` | 1 |

Top hosts:

| Host | Records |
| --- | ---: |
| `pubmed.ncbi.nlm.nih.gov` | 2,820 |
| `ncbi.nlm.nih.gov` | 2,670 |
| `sciencedirect.com` | 379 |
| `mdpi.com` | 129 |
| `onlinelibrary.wiley.com` | 116 |
| `frontiersin.org` | 103 |
| `link.springer.com` | 89 |
| `researchgate.net` | 78 |
| `nature.com` | 73 |
| `academic.oup.com` | 58 |

Duplicate signals:

- duplicate `PMID` examples: 2 groups;
- duplicate `PMCID` examples: 0 groups;
- duplicate DOI examples: 0 groups;
- duplicate normalized title examples surfaced in the summary for review.

Initial interpretation:

- The legacy dataset is highly reconcilable without network access: most rows
  already expose `PMID`, `PMCID`, or DOI in the URL.
- PMC full-text URLs are common enough to justify a direct PMC resolver path.
- The 1,207 publisher/other URL records should be the priority for POC 3 because
  they need DOI, PubMed, Europe PMC, or publisher resolution.
- Duplicate `PMID` groups are rare but real, so downstream normalized publication
  records should not assume one legacy row equals one publication.

### POC 7: Legacy-Anchored PubMed Discovery

Goal: identify strong-evidence PubMed records outside the curated legacy dataset.

Status: implemented on 2026-05-14; first network run pending.

The discovery POC:

- builds an identity index from the latest
  `data/normalized/legacy_reconciliation/*_records.jsonl` output;
- indexes `PMID`, `PMCID`, DOI, canonical URL, and normalized title;
- runs strong-evidence cannabinoid PubMed queries across systematic reviews,
  meta-analyses, randomized trials, controlled trials, double-blind trials,
  placebo-controlled studies, and priority areas including pain, epilepsy,
  adverse effects, dependence, anxiety, cancer, and inflammation;
- classifies each PubMed record as `in_legacy_exact`, `possible_legacy_match`,
  `new_candidate`, or `needs_manual_identity_review`;
- computes a transparent `priority_score` from publication type/design hints,
  human/animal/in vitro signals, priority condition terms, DOI/`PMCID`, abstract
  availability, and recency.
- keeps fuzzy title matching conservative: newer PubMed records are not linked to
  older legacy records unless a stable identifier or exact normalized title agrees.
- marks `cannabinoid_focus` and `full_text_review_priority` in review exports so
  HITL can prioritize high-value records that need manual full-text/PDF access.
- exports `study_design` and `study_design_rank` using this hierarchy:
  `Case Report < Case Series < Case-Control < Cohort Study <
  Controlled Clinical Trial < Randomized Controlled Trial < Systematic Review <
  Meta-Analysis`.

Run:

```bash
uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100
```

Outputs are local and ignored under `data/normalized/pubmed_discovery/`:

- `*_records.jsonl`;
- `*_legacy_matches.jsonl`;
- `*_new_candidates.jsonl`;
- `*_review_export.csv`;
- `*_summary.json`.

Date-window runs are organized under paths such as
`data/normalized/pubmed_discovery/pdat/2026-04/`. The POC also writes a local
`_manifest.json` and skips matching completed windows by default, so monthly
backfills do not need to hit PubMed again.

### POC 8: NIH iCite Citation Enrichment

Goal: evaluate whether citation and influence metrics improve review
prioritization for PubMed discovery candidates.

Status: implemented on 2026-05-14; first network run pending.

NIH iCite exposes an API for PMID batches and fields such as citation count,
Relative Citation Ratio, and translational indicators. The first POC should enrich
the PubMed discovery candidate PMIDs rather than search independently, then compare
whether citation metrics change the review queue in a useful way.

Initial fields to evaluate:

- total citations / `citedByPmidCount`;
- Relative Citation Ratio;
- cited-by clinical articles, when available;
- human, animal, and molecular/cellular orientation;
- Approximate Potential to Translate.

Guardrails:

- treat citation metrics as a prioritization signal, not as evidence quality;
- account for recency bias, because newer studies have had less time to accrue
  citations;
- preserve the PubMed POC score and iCite score as separate columns;
- do not let citation metrics overwrite `study_design_rank`, `cannabinoid_focus`,
  or `full_text_review_priority`;
- do not retrieve full text or download PDFs in this enrichment step.

Run:

```bash
uv run python -m pocs.icite_enrichment.enrich_icite run \
  --input-path data/normalized/pubmed_discovery/pdat/2026-04/20260514T220709Z_pubmed_discovery_records.jsonl
```

Outputs are local and ignored under `data/normalized/icite_enrichment/`:

- `*_records.jsonl`;
- `*_review_export.csv`;
- `*_summary.json`.

A local `_manifest.json` records the input path and file hash so the same
discovery file is not queried again unless `--no-skip-existing` is used.

Older-window validation:

- April 2025 PubMed discovery command:
  `uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100 --datetype pdat --mindate 2025/04/01 --maxdate 2025/04/30`;
- discovery run id: `20260515T112139Z`;
- discovery output:
  `data/normalized/pubmed_discovery/pdat/2025-04/20260515T112139Z_pubmed_discovery_records.jsonl`;
- records after dedupe: 67;
- identity status counts: 64 `new_candidate`, 3 `in_legacy_exact`;
- iCite command:
  `uv run python -m pocs.icite_enrichment.enrich_icite run --input-path data/normalized/pubmed_discovery/pdat/2025-04/20260515T112139Z_pubmed_discovery_records.jsonl`;
- iCite run id: `20260515T112334Z`;
- iCite found metrics for 67 / 67 PMIDs;
- `citation_priority_score` range: 5 to 85.

Result: citation metrics improved visibility into influence, but citation-only
sorting promoted weak cannabinoid-focus records and buried some high-priority
recent RCTs and reviews. The review queue should therefore preserve PubMed
`priority_score` as the baseline and use citation metrics as secondary signals
with explicit recency-bias guardrails.

Next step: begin MVP design for the human-reviewed evidence curation workflow
using PubMed discovery, legacy association, access enrichment, iCite enrichment,
and review-row provenance. Semantic Scholar access can still improve enrichment
later, but the API key is not required to define the first MVP.

### POC 3: Full-Text Availability Resolver

Goal: classify access paths before downloading or parsing full-text documents.

Status: completed for the first local-only validation pass on 2026-05-13.

For each record with a stable identifier, classify:

- PubMed metadata only;
- PMC full text available;
- Europe PMC full text or open-access metadata available;
- Unpaywall open-access location available;
- DOI or publisher page available;
- not automatically recoverable.

Deliverables:

- resolver output with one access classification per publication;
- provenance for each classification source;
- a recommendation on whether a continuous resolver is worth promoting to an
  adapter.

First run:

- run id: `20260513T162415Z`;
- command: `uv run python pocs/link_resolver/resolve_links.py run`;
- input: `data/normalized/legacy_reconciliation/20260513T155614Z_legacy_reconciliation_records.jsonl`;
- records classified: 7,347.

Access class counts:

| Access class | Records | Interpretation |
| --- | ---: | --- |
| `pmc_full_text_available` | 1,676 | Direct PMC path from `PMCID`; good first sample for full-text extraction. |
| `pubmed_metadata_only` | 3,805 | `PMID` exists, but local input needs PubMed/Europe PMC enrichment for DOI or `PMCID`. |
| `doi_landing_page_available` | 659 | DOI exists; needs Unpaywall and Europe PMC open-access classification. |
| `publisher_landing_page_only` | 1,207 | Only canonical publisher/other URL is known; needs identifier extraction or title search. |

Next resolver step counts:

- `query_pubmed_for_pmcid_and_doi`: 3,805;
- `query_europe_pmc_by_pmid`: 3,805;
- `verify_pmc_license`: 1,676;
- `sample_pmc_full_text_extraction`: 1,676;
- `extract_identifier_from_publisher_page`: 1,207;
- `title_search_in_pubmed_or_crossref`: 1,207;
- `query_unpaywall`: 659;
- `query_europe_pmc`: 659;
- `verify_doi_landing_page`: 659.

Initial interpretation:

- There is an immediately usable PMC full-text sample of 1,676 records, but license
  and extraction behavior still need verification before any broad use.
- The largest opportunity is enriching 3,805 PMID-only records with PubMed or Europe
  PMC to find missing DOI/`PMCID` links.
- DOI-only records should go through Unpaywall and Europe PMC before touching
  publisher pages.
- Publisher-only records are the hardest set and should be handled after identifier
  enrichment, not as the first crawling target.

### POC 4: Europe PMC And Unpaywall Enrichment

Goal: enrich resolver outputs with Europe PMC and Unpaywall metadata without
downloading PDFs.

Status: completed for the first Europe PMC plus Unpaywall sample on 2026-05-13.

Deliverables:

- coverage comparison by `PMID`, DOI, and title;
- available full-text and license metadata counts;
- recommendation on whether Europe PMC should become a standard enrichment step.

Current run:

- run id: `20260513T170323Z`;
- command: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 10`;
- input: `data/normalized/link_resolver/20260513T162415Z_link_resolver_records.jsonl`;
- sampled records: 20, with 10 `pubmed_metadata_only` and 10
  `doi_landing_page_available`.

Results:

| Metric | Count |
| --- | ---: |
| Europe PMC queried | 20 |
| Europe PMC found | 15 |
| Unpaywall queried | 20 |
| Unpaywall found | 16 |
| Unpaywall open access | 11 |
| Unpaywall PDF URLs | 7 |
| Open-access PDF candidates | 10 |
| Open-access landing candidates | 1 |
| Metadata enriched without full text | 4 |
| Unpaywall metadata without open access | 1 |
| Not enriched | 4 |
| Records with errors | 0 |

Initial interpretation:

- Europe PMC is useful as a resolver/enrichment source. In this sample it found
  metadata for 15 / 20 records and supplied DOI/`PMCID` enrichment for several
  PMID-only records.
- Unpaywall should be part of the DOI resolver path. It found 16 / 20 sampled DOI
  lookups, marked 11 as open access, and exposed 7 PDF URLs.
- The combined strategy is better than either source alone: Europe PMC can discover
  DOI values for PMID-only records, and those DOI values can immediately feed
  Unpaywall.
- The enrichment layer should record candidate URLs and license/access metadata,
  but still avoid downloading PDFs until the PDF sample POC.

### POC 5: Unpaywall DOI Enrichment

Goal: evaluate DOI-based open-access metadata and PDF URL discovery.

Status: completed for the first sampled pass as part of POC 4 on 2026-05-13.

Deliverables:

- DOI coverage rate from PubMed and legacy records;
- open-access status and license distribution;
- count of PDF URLs discovered without downloading the files;
- recommendation on whether Unpaywall should be part of the resolver pipeline.

### POC 6: Small Full-Text And PDF Sample

Goal: test extraction value and difficulty on a small, selected sample only.

Status: completed first small HTML/XML-first pass on 2026-05-13.

Sample categories:

- PMC full text;
- publisher open-access HTML;
- Unpaywall-discovered PDFs;
- difficult or ambiguous records.

Measure whether full text adds fields that abstracts usually miss:

- dose;
- treatment duration;
- adverse events;
- protocol details;
- study arms and interventions;
- population details.

Current run:

- run id: `20260513T215843Z`;
- command: `uv run python pocs/pdf_samples/sample_full_text.py run`;
- sample records: 10;
- selected HTML sources: 8;
- selected XML sources: 1;
- records without usable text: 1;
- supplemental PDFs downloaded: 1;
- field extraction candidates: 58;
- human review state: 58 / 58 marked `needs_review`.

Results:

| Metric | Count |
| --- | ---: |
| HTML sources selected | 8 |
| XML sources selected | 1 |
| Unusable records | 1 |
| Supplemental PDFs downloaded | 1 |
| Records with fallbacks or errors | 5 |
| Field extraction candidates | 58 |

Field evidence coverage:

| Field | Records with candidate evidence |
| --- | ---: |
| route of administration | 9 |
| adverse events | 8 |
| population details | 8 |
| dosage | 7 |
| study design | 7 |
| treatment duration | 6 |
| protocol/intervention details | 5 |
| arms/comparators/control groups | 2 |

Initial interpretation:

- HTML/XML-first is the right technical shape. Direct PMC HTML extracted cleanly
  enough for a first pass.
- Europe PMC rendered article pages should not be treated as stable HTML fetch
  targets. In this run they returned JavaScript-dependent placeholder text.
  Europe PMC full-text XML is useful when available; PMC HTML is the practical
  fallback when `PMCID` is known.
- PDF should remain a fallback or supplemental path. One Unpaywall PDF candidate
  was downloaded successfully, while a Wiley candidate returned 403.
- Keyword extraction is useful as a baseline candidate finder, but it should not
  be promoted as a production extractor. It sometimes selects adjacent or
  contextually related sentences rather than the exact normalized value.
- LLM extraction is implemented as an optional test path for Ollama and Groq, but
  it was not executed in the first run because no local Ollama server or
  `GROQ_API_KEY` was available in that session.
- A follow-up spot test found that local `qwen3:8b` can produce useful evidence
  summaries but does not reliably obey strict JSON on long article contexts. Groq
  produced better JSON on a single case report, but back-to-back free-tier calls
  hit `429 Too Many Requests`.
- The next LLM iteration should use a two-stage design: evidence extraction first,
  then Pydantic normalization.
- HITL should be considered part of the extraction architecture, not a later
  cleanup step. Every field candidate from this run remains `needs_review`.

### POC 7: Legacy-Anchored PubMed Discovery

Goal: find relevant PubMed publications outside the curated legacy dataset.

Status: proposed next.

Tasks:

- build a legacy identity index from the latest legacy reconciliation records;
- run high-reputation PubMed query families for systematic reviews,
  meta-analyses, randomized/controlled trials, double-blind trials,
  placebo-controlled studies, and priority condition areas;
- classify every PubMed result as an exact legacy match, possible legacy match,
  new candidate, or manual identity-review item;
- score new candidates by evidence reputation, human/animal/in-vitro signal,
  priority condition terms, DOI/`PMCID`, abstract availability, and publication
  date;
- export ambiguous matches and new candidates for human review.

This POC should not perform full-text extraction. Its job is publication discovery
and association against the trusted legacy base.

## Continuous Crawler Gate

Do not design a continuous crawler until the project has evidence from POCs 1-8.

A crawler design should only follow after the team can answer:

- which sources populate which ontology fields reliably;
- which identifiers are stable enough for deduplication;
- how often full text is actually needed;
- which access paths are lawful and operationally stable;
- which fields require human review;
- what should be stored as raw source payload versus normalized record.

## Next Work

POC 6b has now tested saved text samples with a strict candidate-evidence then
Pydantic-normalization flow. The first comparison used records `340`, `164`, and
`43`.

POC 6b observations:

- all normalized fields remain `needs_review=true`;
- Groq generated parseable structured candidates for all three records when using
  section-selected prompts, `--prompt-max-chars 3500`, and `--delay-seconds 12`;
- Groq rate-limit headers showed token budget, not request count, as the practical
  constraint in the three-record run;
- Ollama `qwen3:8b` was useful for candidate evidence on the case report, but not
  reliable enough for final JSON output;
- OpenRouter `openrouter/free` worked for one case-report record, while explicit
  free model tests showed truncation and `429` risks.

POC 6c improved section ranking, added review export rows, and added
rate-limit-aware retry/backoff. The next PubMed source-track implementation is
POC 7: legacy-anchored discovery to estimate how many additional
higher-reputation studies exist beyond the curated legacy dataset.

Prioritize systematic reviews, meta-analyses, randomized controlled trials,
controlled clinical trials, double-blind trials, placebo-controlled studies, and
priority condition areas such as pain, epilepsy, adverse effects, dependence,
anxiety, cancer, and inflammation.
