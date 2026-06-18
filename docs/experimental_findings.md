# Experimental Findings

This document preserves durable findings from historical source and model
experiments. The original standalone POC implementations are no longer part of
the supported public interface. Their Git history remains available, and the
maintainer may keep local copies under ignored `temp/project_archive/`.

## Publication Identity And Discovery

- PubMed is the primary publication identity and discovery source.
- A validated sample normalized 790 PubMed records across eight query families.
- DOI and abstract coverage were strong; PMCID coverage was useful but partial.
- Monthly PubMed windows can overlap by PMID, so source-window counts must remain
  separate from unique document counts.
- `cannabinoid_focus` is a better primary prioritization signal than citation
  count or general influence.

## Private Bootstrap

- The maintainer-local legacy bootstrap contains thousands of curated records
  and is a strong validation anchor.
- Direct PMID, PMCID, or DOI identity was available for 6,140 of 7,347 legacy
  publication rows in the initial reconciliation.
- Normalized English legacy context is the preferred baseline for classification
  prompts and evaluation.
- Legacy agreement is informative but not absolute. Source-supported
  disagreements should be retained for review.

## Source Availability

- Metadata availability is not equivalent to classification-ready source text.
- Persisted HTTP success is not proof of valid article content.
- PMC OAI-PMH was the strongest official full-text route in the legacy-core
  acquisition campaign.
- Digital PDF extraction is a valid first-class classification source when the
  text layer passes quality gates.
- OCR is a residual route for scanned or poor-text-layer PDFs.
- NCBI ELink and OpenAlex are access and identity augmentation sources, not
  direct full-text sources.
- The June 2026 legacy-core campaign produced about 3,149 strict
  classification-ready documents and about 3,374 broader source-ready documents
  after deduplication.

## Classification

- Strict Pydantic validation is effective at exposing schema and prompt defects.
- Candidate classifications should preserve evidence spans, source hashes,
  model, prompt, schema, usage, latency, warnings, and uncertainty.
- The principal study-design field should use the English legacy-compatible
  domain. More granular interpretation belongs in separate subtype fields.
- Same-document tests favored `gpt-5.4-mini` over `gpt-4.1` on cost and over
  `gpt-5.4-nano` on schema reliability for the tested prompt.
- A 100-document schema-v2 run on 2026-06-18 produced 100 successful provider
  responses, 97 strict-valid records, and evidence spans for every valid record.
- The three validation failures shared a correctable `outcome_domains` enum
  issue rather than a provider or source failure.
- Cognition appeared consistently enough in the failed records to justify a
  first-class retrieval domain rather than lossy mapping to efficacy, safety, or
  mechanism.
- Among valid records, 90 of 97 principal study-design labels exactly matched
  the normalized English legacy type.
- Declared uncertainty was common, but technical fields were no longer
  incorrectly reported as scientific uncertainty.
- Six valid records still used free-text uncertainty entries and three omitted
  required field-scoped uncertainty markers. Strict schema-v3 field names expose
  these as contract defects instead of silently interpreting them.
- A targeted schema-v3 rerun on 2026-06-18 covered the three prior validation
  failures and seven prior study-design disagreements. It produced 10/10 HTTP
  successes, 10/10 valid JSON responses, 10/10 strict-valid records, no retries,
  and evidence spans for every record.
- All three prior `outcome_domains` failures became valid. Cognition appeared in
  five of the ten records, confirming that it is useful as a first-class
  retrieval domain.
- Among the seven original study-design disagreements, one became an exact
  English legacy match. Five used `other` with source-explicit subtypes
  (`pilot_study`, `observational_study`, `survey`, or
  `case_report_or_series`), and one used `clinical_meta_analysis` where the
  English legacy reference used the broader `Meta-analysis`.
- The targeted run had 3/10 exact principal study-design matches and 8/10
  compatible overall-direction comparisons against English legacy context.
  Exact legacy agreement alone understates source fidelity when the legacy label
  conflicts with explicit document design wording.
- The run produced 40 evidence spans. Seventeen were exact normalized
  substrings; all 40 passed token-bigram grounding with extraction-artifact
  tolerance, leaving no spans for grounding review. Extracted PDFs and page text
  can interleave author names, headers, or journal metadata inside otherwise
  copied sentences, so exact and tolerant grounding must be reported separately.
- All ten records declared `classification_confidence=medium`. This categorical
  self-assessment did not discriminate among the targeted cases and remains
  unsuitable as a calibrated score.
- The targeted run used 48,239 input tokens and 10,819 output tokens. At the
  standard `gpt-5.4-mini` rates used on 2026-06-18, estimated cost was about
  USD 0.0849.

## Product Interpretation

Classification exists to improve retrieval, not to replace scientific judgment.
A declared, evidence-backed uncertainty can remain useful. Known technical
defects should be corrected. Evaluation must therefore separate technical
validity, retrieval utility, and inference quality.

## Decisions Promoted Into The Product

- Supported workflows live under `src/marygenai/` and the `marygenai` CLI.
- Historical experiment code is not a supported public API.
- Generated artifacts remain ignored and auditable.
- AI output remains candidate evidence.
- Retrieval confidence must not be confused with clinical evidence strength.
- Read-only MCP retrieval is the intended first external integration surface.
