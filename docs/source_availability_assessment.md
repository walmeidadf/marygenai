# Source Availability Assessment

This document records what the project currently knows about publication source
availability for automated study classification. It is intentionally blunt:
metadata-only enrichment does not count as classification-ready material.

## Decision Question

The original question was whether the enrichment layer could plausibly produce at
least 5,000 classification-ready source texts from the maintainer bootstrap and
near-term candidate corpus. The June 2026 source-acquisition campaign answered
that the legacy-only ceiling is probably below that target.

The project has therefore pivoted: MaryGenAI should continue as a
source-intelligence and candidate-classification engine, starting from the
classification-ready corpus that exists and expanding through PubMed discovery
rather than pausing until a 5,000+ reviewed corpus exists.

Classification-ready means enough article text exists to classify study type,
cannabinoid role, target condition, population/model, intervention/exposure,
and basic outcomes. Perfect table extraction is not required for this gate.

## Known Local Coverage

Current local SQLite state as of 2026-06-04:

- `document` rows: 8,705.
- Documents with at least one `access_enrichment_artifact`: 7,843.
- Publication rows with a non-empty abstract: 1,350.
- Persisted access artifacts: 16,816.

Latest local artifact-quality audit:

```bash
uv run marygenai access-enrichment audit-artifacts
```

Run: `20260603T171550Z`.

Artifact-level counts:

- total artifacts: 16,816;
- metadata-only artifacts: 12,202;
- usable full-text artifacts: 1,307;
- invalid payload artifacts: 3,227;
- access error artifacts: 80.

Document-level rollup:

- `usable_for_llm_classification`: 1,307 documents;
- `needs_reenrichment`: 1,283 documents;
- `source_triage_needed`: 5,253 documents.

Important interpretation:

- The 12,202 metadata-only artifacts are useful for access discovery and audit,
  but they are not classification-ready source text.
- The current local corpus is therefore not yet sufficient for the intended
  automation goal.
- The immediate project question is source availability, not LLM classification
  quality.

## June 2026 Final Legacy-Core Acquisition Result

After PMC OAI-PMH, Unpaywall PDF extraction, NCBI ELink/OpenAlex augmentation,
and filtered augmented-link acquisition were exhausted for the initial
legacy-core campaign, the operational local result was:

- legacy-core operational documents: 6,491;
- baseline usable legacy-core documents before new acquisition: 977;
- official-source acquisition attempted documents: 5,322;
- additional strict classification-ready documents: 2,172;
- additional broader source-ready documents: 2,397;
- total strict classification-ready legacy-core documents: 3,149;
- total broader source-ready legacy-core documents: 3,374.

Strict classification-ready means real extracted source text with enough length,
scientific-section signal, and a simple cannabinoid term signal. Broader
source-ready means the article text appears long and scientific enough for
classification, but the simple cannabinoid term detector did not necessarily
fire.

By strategy:

| source strategy | attempted documents | source-ready texts | strict classification-ready texts |
| --- | ---: | ---: | ---: |
| PMC OAI-PMH | 1,940 | 1,510 | 1,380 |
| Unpaywall PDF | 1,172 | 427 | 378 |
| Filtered augmented links | 3,501 | 719 | 638 |

Main failure classes across acquisition records:

| failure class | records |
| --- | ---: |
| access blocked | 3,340 |
| retrieved but not enough text | 1,955 |
| HTTP non-success | 492 |
| PDF likely needs OCR or has bad text layer | 81 |
| request error | 72 |
| not found | 65 |

Operational conclusion:

- The legacy-only corpus is good enough to start classification POCs, especially
  for high-coverage condition areas.
- It is probably not enough to reach 4,000 strict classification-ready documents
  without new PubMed discovery or a materially different source strategy.
- OCR can recover some residual PDFs, but it is too small to close the gap by
  itself.
- PubMed discovery is the preferred growth path beyond the legacy-only ceiling.

## What The Existing POCs Already Showed

### Source Availability Ceiling And Official Fetch Router

The June 2026 source-availability POCs narrowed the gate to legacy publication
records with a core identifier and then tested real retrieval routes. These
outputs are local operational artifacts under ignored `data/` paths; they are not
reviewed knowledge and do not mutate SQLite or review state.

Local ceiling summary:

- legacy publication records with `PMID`, `PMCID`, or DOI: 6,491;
- already usable legacy-core records before the new source acquisition work: 977;
- non-usable legacy-core records needing source acquisition: 5,514;
- local or Europe PMC-discovered PMCID route candidates: 1,940;
- Unpaywall PDF URL candidates: 1,172;
- NCBI ELink candidates: 4,151;
- OpenAlex identity/access candidates: 5,514.

Validated acquisition results during the campaign:

| source strategy | attempted documents | source-ready texts | source-ready with cannabinoid signal |
| --- | ---: | ---: | ---: |
| PMC OAI-PMH | 1,940 | 1,510 | 1,380 |
| Unpaywall PDF | 1,172 | 427 | 378 |
| Filtered augmented links | 3,501 | 719 | 638 |

The deduplicated legacy-core total after all three acquisition strategies is
3,374 broader source-ready documents, or 3,149 strict classification-ready
documents.

Operational interpretation:

- PMC OAI-PMH is the strongest first acquisition route for local or discovered
  PMCIDs and avoids fragile PMC page scraping.
- Digital PDF extraction with PyMuPDF is validated enough to keep PDFs as a
  first-class classification source. OCR remains a separate residual route for
  scanned or poor-text-layer PDFs.
- NCBI ELink and OpenAlex are best treated as access/identity augmentation
  sources. They discover many links, but the project must filter non-source
  surfaces before fetching article text.
- The plausible near-term target is now around 4,000 source-ready texts with
  continued augmented-link acquisition and future PubMed-discovery expansion,
  rather than relying only on the private legacy-core universe.

### Link Resolver

The local-only link resolver classified 7,347 legacy rows:

- 1,676 direct PMC full-text paths;
- 3,805 PMID-only records;
- 659 DOI landing-page records;
- 1,207 publisher-only records.

This POC classified identifiers and candidate access paths. It did not prove
that enough classification-ready text could be retrieved.

### Europe PMC And Unpaywall Sample

The first sampled access enrichment POC queried 20 records:

- Europe PMC found 15 / 20;
- Unpaywall found 16 / 20;
- Unpaywall marked 11 as open access;
- 10 records had open-access PDF candidates;
- 7 Unpaywall PDF URLs were exposed.

This suggested that PDF and publisher-hosted access may be an important path.
The sample was too small to estimate whether the project can reach 5,000+
classification-ready texts.

### PDF Samples

The PDF/full-text sample POC used only 10 records:

- 8 selected HTML sources;
- 1 selected XML source;
- 1 record without usable text;
- 1 supplemental PDF downloaded;
- 58 field extraction candidates.

The prior conclusion over-preferred HTML/XML and deferred PDF processing. That
was too conservative for the current decision gate. For study classification,
plain extracted PDF text may be sufficient even when table extraction is weak.

### LLM Source-Unit Quality Audit

A 500-document stratified source-artifact audit found:

- `full_text_rich`: 229;
- `recaptcha_or_js`: 144;
- `abstract_only`: 54;
- `low_cannabinoid_focus`: 52;
- `abstract_plus_boilerplate`: 9;
- `metadata_only`: 6;
- `biomarker_only`: 5;
- `image_pdf_or_scan`: 1.

This confirmed that the bottleneck is source sufficiency and source quality,
not grounding in the LLM classifier.

## What Did Not Work Well

- Treating metadata availability as equivalent to source availability.
- Treating a successful HTTP payload as valid full text without content
  validation.
- Saving Recaptcha/JavaScript blocks as `pmc_nxml` or `pmc_html`.
- Treating HTML returned from an XML endpoint as structured NXML.
- Assuming the small PDF POC was enough to defer PDF processing.
- Spending classification effort on the current ~1,300 usable texts before
  proving that source enrichment can scale to at least 5,000 texts.

## Current Failure Classes

Current artifact-quality audit categories:

- `blocked_recaptcha_or_javascript_payload`: 1,391 artifacts.
- `expected_xml_received_html`: 1,836 artifacts.
- `error_artifact`: 80 artifacts.
- `metadata_only`: 12,202 artifacts.

Recommended interpretation:

- Recaptcha/JavaScript blocks need alternate source strategies, not blind retry.
- HTML returned through an XML endpoint may be usable text, but should be
  normalized as HTML rather than treated as JATS/NXML.
- Metadata-only records need a real source availability search across PMC OA,
  Europe PMC, Unpaywall, publisher OA, PDF, and possibly external corpora.
- Low-cannabinoid-focus and source/legacy mismatch cases belong in identity or
  focus review, not source reenrichment.

## PDF Position

PDF should no longer be treated as an exceptional last resort for the source
availability decision. For classification, the project needs article text, not
perfect table reconstruction.

Near-term PDF extraction should test:

- text extraction coverage;
- text length and scientific-section signal;
- boilerplate and reference removal;
- OCR need rate;
- whether extracted text supports coarse classification tasks.

Table extraction, figure interpretation, and exact dosage/arm reconstruction can
remain later enrichment problems.

## Source Availability Research Questions

The June 2026 campaign answered the immediate legacy-core availability question.
Future expansion should continue to answer these quantitatively for PubMed
discovery candidates and any new document universe:

1. How many records can be matched to PMC Open Access package XML or text?
2. How many records can be retrieved through Europe PMC `fullTextXML`?
3. How many records are available through PMC OAI-PMH as reusable full-text JATS?
4. How many records have PDF URLs through Unpaywall or Europe PMC?
5. How many publisher OA landing pages expose usable article HTML?
6. How many records appear in external open full-text corpora such as BioC PMC
   OA, S2ORC/Semantic Scholar, CORE, OpenAIRE, or OpenAlex-linked sources?
7. Combining non-overlapping sources and new PubMed discovery records, how far
   can the project grow beyond the current 3,149-3,374 legacy-core
   classification/source-ready corpus?

The output should be a coverage table with at least:

- source strategy;
- input ID type required;
- local candidate count;
- retrievable source-text count;
- estimated classification-ready count;
- legal/terms risk;
- engineering complexity;
- confidence;
- sample evidence paths.

## Stop/Continue Gate

The original automation-first gate is not met by the legacy-only corpus. The
project should not claim a 5,000+ reviewed or classification-ready legacy corpus.

The project should continue in a reframed form:

- use the current 3,149 strict classification-ready legacy-core documents as the
  first candidate-classification substrate;
- keep the 3,374 broader source-ready documents as a secondary substrate for
  detector tuning and prompt testing;
- expand beyond the legacy ceiling through PubMed discovery;
- clearly label AI outputs as candidate evidence until human review is available.
