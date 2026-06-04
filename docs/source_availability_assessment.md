# Source Availability Assessment

This document records what the project currently knows about publication source
availability for automated study classification. It is intentionally blunt:
metadata-only enrichment does not count as classification-ready material.

## Decision Question

The project should not spend substantial effort on downstream classification
unless the enrichment layer can plausibly produce at least 5,000
classification-ready source texts from the maintainer bootstrap and near-term
candidate corpus.

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

## What The Existing POCs Already Showed

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

The next research session should answer these quantitatively for the local
document universe:

1. How many records can be matched to PMC Open Access package XML or text?
2. How many records can be retrieved through Europe PMC `fullTextXML`?
3. How many records are available through PMC OAI-PMH as reusable full-text JATS?
4. How many records have PDF URLs through Unpaywall or Europe PMC?
5. How many publisher OA landing pages expose usable article HTML?
6. How many records appear in external open full-text corpora such as BioC PMC
   OA, S2ORC/Semantic Scholar, CORE, OpenAIRE, or OpenAlex-linked sources?
7. Combining non-overlapping sources, can the project reach 5,000-8,000
   classification-ready texts?

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

Continue the automation-first project only if a credible, legal, and technically
stable path exists to reach at least 5,000 classification-ready source texts.

If the realistic ceiling remains near 1,300-2,500 texts, the project should be
paused, reframed, or narrowed before further LLM classification work.
