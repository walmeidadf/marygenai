# Source Availability Ceiling POC

Goal: estimate the realistic ceiling for classification-ready source text among
legacy publication records that already have at least one core identifier
(`PMID`, `PMCID`, or DOI), excluding documents already marked locally as
`usable_for_llm_classification`.

This POC is operational source research, not classification. It does not mutate
SQLite, review queues, review decisions, or reviewed knowledge. Any retrieved
source text is candidate source material for later human-reviewed workflows.

## Commands

Local-only ceiling summary:

```bash
uv run python -m pocs.source_availability_ceiling.assess_ceiling summarize
```

Small network validation probe:

```bash
uv run python -m pocs.source_availability_ceiling.assess_ceiling probe \
  --limit-per-strategy 10 \
  --max-bytes 8000000 \
  --delay-seconds 0.5
```

The `probe` command fetches only a bounded sample. It is intended to estimate
conversion from access hints to usable extracted text, especially for:

- PMCID repair through PMC XML/HTML;
- Europe PMC full-text URLs;
- Unpaywall PDF and landing URLs;
- publisher DOI/canonical landing pages for records with no open full-text
  signal yet.

PDFs are not treated as taboo. If a local PDF text extractor is unavailable, PDF
downloads are counted as retrievable PDF bytes but not as validated
classification-ready text.

The current probe uses PyMuPDF for digital PDF text extraction. OCR is
deliberately separate: PDFs that retrieve successfully but produce too little
text are routed as likely OCR candidates instead of being counted as
classification-ready.

Recommended extraction stack:

1. Prefer structured XML/HTML from PMC, Europe PMC, or publisher OA pages.
2. Use PyMuPDF for digital PDFs and record text length, scientific-section
   signals, cannabinoid-term signals, and OCR need.
3. Evaluate GROBID or Docling after the source ceiling is validated, when
   section structure, references, and tables become more important.
4. Run OCR only on the residual scanned/image-PDF bucket.

## Outputs

Outputs are ignored local artifacts under:

```text
data/normalized/source_availability_ceiling/
```

- `*_summary.json`: aggregate counts and estimated ceilings;
- `*_records.jsonl`: one local candidate record per non-usable legacy-core
  document;
- `*_probe_records.jsonl`: one bounded network probe result per attempted URL.

## Interpretation

Use the summary as a gate:

- if sampled retrieval validates a path to roughly 4,000-6,000 total usable
  texts, proceed to a reenrichment/source-acquisition POC;
- if the realistic ceiling stays below 5,000, pause or reframe the automation
  scope before spending effort on classification.
