# Data Sources

## Source Policy

MaryGenAI prefers public APIs, official repositories, source-declared access
routes, and auditable local artifacts. Source identity, access permission,
payload quality, and extraction quality are separate concerns.

Private maintainer legacy exports are a local bootstrap and validation anchor,
not a public data source.

## PubMed And NCBI

Role:

- primary publication discovery;
- PMID-centered identity;
- title, abstract, journal, date, authors, publication types, MeSH, chemicals,
  keywords, DOI, and PMCID metadata.

PubMed is not a general full-text crawler. The supported command is:

```bash
uv run marygenai pubmed-discovery run \
  --datetype pdat \
  --mindate 2024/01/01 \
  --maxdate 2024/01/31 \
  --retmax 100
```

Discovery priority should be dominated by cannabinoid focus. Study design,
source access, recency, and citation data are secondary.

## PMC

Role:

- preferred official full-text route when PMCID exists;
- structured or declared source text;
- stable provenance for source acquisition.

PMC source text must still pass quality checks. A fetched HTML challenge page is
not article text.

## Europe PMC

Role:

- identity and access enrichment;
- open-access and full-text discovery;
- structured full-text route when available.

Europe PMC metadata availability does not by itself make a record
classification-ready.

## Unpaywall

Role:

- DOI-based open-access metadata;
- license and best-location discovery;
- lawful PDF or repository link discovery.

Unpaywall is an access resolver, not a guarantee that a linked payload is usable.

## OpenAlex And NCBI LinkOut

Role:

- identity and access augmentation;
- alternate repository or publisher link discovery.

Returned links require filtering. Many are metadata, clinical, commercial, or
non-article surfaces.

## PDF

Digital PDF text is a first-class source for coarse candidate classification when
it has sufficient text quality and scientific-section signal.

OCR is reserved for scanned or poor-text-layer PDFs. Exact table, figure, dosage,
and arm reconstruction remain specialized later work.

## ClinicalTrials.gov

Trial registry records should be modeled separately from publications. They can
provide protocol, phase, status, enrollment, condition, intervention, arm, and
outcome metadata and may link to later publications.

This is a planned source, not yet an official ingestion command.

## Citation And Enrichment Sources

iCite, Semantic Scholar, and similar sources may add secondary audit or influence
signals. They must not outrank direct cannabinoid relevance or be confused with
scientific validity.

No current official command depends on Semantic Scholar.

## Drug Interaction Sources

Drug interaction evidence requires a specialized claim model with substance,
severity, mechanism, clinical note, evidence, and provenance. It should not be
forced into the publication classification schema.

No public drug-interaction ingestion command is supported yet.

## Source Acceptance Criteria

A source adapter or route should document:

- source identity and version;
- credentials and rate limits;
- lawful access assumptions;
- request and retry behavior;
- raw payload path and hash;
- normalized schema;
- content-quality checks;
- error capture;
- run manifest and provenance.
