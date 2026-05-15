# Data Sources

This document tracks source candidates and what each POC should test.

## PubMed / NCBI E-utilities

Primary candidate for biomedical publication identity and metadata. PubMed should
act as the publication hub for `PMID`, DOI, abstract, MeSH, publication type, and
related biomedical metadata. It should not be treated as the primary full-text or
PDF crawler.

PubMed is also the current primary source for detecting new candidate studies. New
study discovery should prioritize systematic reviews, meta-analyses, randomized or
controlled clinical trials, double-blind trials, and placebo-controlled studies
before lower-evidence publication types.

Current status:

- basic `ESearch` plus `EFetch` mechanics are validated in the PubMed POC;
- POC 1 expanded metadata batch ran on 2026-05-13 across 8 query families and
  normalized 790 records;
- POC 2 legacy reconciliation ran on 2026-05-13 and found 6,140 / 7,347 legacy
  rows with directly extractable `PMID`, `PMCID`, or DOI;
- POC 3 local link resolver ran on 2026-05-13 and classified 1,676 direct PMC
  full-text paths, 3,805 PMID-only records, 659 DOI-only records, and 1,207
  publisher-only records;
- access enrichment ran a 10-record Europe PMC sample on 2026-05-13 and found
  metadata for 7 records, including 5 open-access PDF candidates;
- legacy-anchored PubMed discovery is implemented and can run date-windowed
  discovery against the legacy identity index;
- iCite citation enrichment is implemented but should remain a secondary
  cost-benefit signal, not a primary ranking source;
- DOI, abstract, journal, publication date, publication type, and publication status
  coverage were strong in the fetched sample;
- `PMCID` coverage was useful but partial, so PMC should be the first full-text path
  when available, not the only full-text path.

POC questions:

- How well do cannabinoid queries map to relevant results?
- How many candidate studies exist beyond the reconciled legacy dataset?
- Which records include DOI, PMID, PMCID, abstract, MeSH terms, publication type,
  authors, journal, and date?
- Can publication type improve the legacy `study_type` taxonomy?
- Can PubMed query filters reliably prioritize systematic reviews, meta-analyses,
  randomized trials, controlled trials, and placebo-controlled studies?
- Can query and ranking logic keep `cannabinoid_focus` dominant over citation and
  general publication influence?
- How much parsing effort is required for XML?
- How often can PubMed records be linked to PMC, Europe PMC, Unpaywall, DOI, or
  publisher access paths?

## Europe PMC

Candidate for metadata enrichment and open-access/full-text discovery.

Current status:

- implemented in the access enrichment POC;
- first 10-record sample found 7 records and surfaced 5 open-access PDF candidates;
- should be tested on a larger `PMID` and DOI sample before becoming a standard
  resolver step.

POC questions:

- Does it return useful full-text links or license metadata?
- How does coverage compare with PubMed for the same queries?
- Can it reduce PDF processing needs?

## ClinicalTrials.gov

Clinical trial records are not articles and should be modeled as a separate document type.

POC questions:

- Which cannabinoid trials can be found by intervention and condition?
- Which fields map to protocol, phase, status, outcome, enrollment, and arms?
- How should trial records link to later publications?

## Unpaywall

Candidate for open-access metadata and PDF URL discovery.

Unpaywall should be evaluated after PubMed records have DOI coverage metrics. Its
first role is access classification and license discovery, not bulk PDF download.

Current status:

- implemented in the access enrichment POC;
- first sampled pass with `UNPAYWALL_EMAIL` configured queried 20 DOI lookups,
  found 16 records, marked 11 as open access, and exposed 7 PDF URLs.

POC questions:

- Which DOI records have open-access versions?
- What license metadata is available?
- Can we avoid downloading PDFs until explicitly needed?

## Drug Interaction Sources

Drug interactions should be modeled separately from studies and conditions.

Candidate sources include Drugs.com and more structured alternatives if available.

POC questions:

- Can we extract cannabis, THC, CBD, and cannabinoid interaction claims?
- Are severity, mechanism, and clinical notes available?
- Is scraping allowed and technically stable?
- Are there structured alternatives better suited for reproducible ingestion?

## PDF Samples

PDFs should be tested only on a small sample at first.

PDF and full-text processing should follow the resolver POCs. The project should
classify full-text availability before downloading or parsing files.

POC questions:

- Which PDF types extract cleanly?
- Which require OCR or table extraction?
- Which fields are only available in PDF/full text?
- Is the value worth the operational complexity?
