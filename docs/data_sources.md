# Data Sources

This document tracks source candidates and what each POC should test.

## PubMed / NCBI E-utilities

Primary candidate for biomedical publication metadata. It should be tested first because the legacy dataset is heavily PubMed/NLM-oriented.

POC questions:

- How well do cannabinoid queries map to relevant results?
- Which records include DOI, PMID, abstract, MeSH terms, publication type, authors, journal, and date?
- Can publication type improve the legacy `study_type` taxonomy?
- How much parsing effort is required for XML?

## Europe PMC

Candidate for metadata enrichment and open-access/full-text discovery.

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

POC questions:

- Which PDF types extract cleanly?
- Which require OCR or table extraction?
- Which fields are only available in PDF/full text?
- Is the value worth the operational complexity?
