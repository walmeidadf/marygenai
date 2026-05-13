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

## Next POC

### POC 6: Small Full-Text And PDF Sample

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

## Parallel Future Track

After POC 6, run a PubMed discovery expansion POC to estimate additional candidate
studies beyond the legacy dataset.

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
