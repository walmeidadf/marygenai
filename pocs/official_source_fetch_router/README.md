# Official Source Fetch Router POC

Goal: validate a legal, reproducible source-acquisition route for legacy
publication records with core identifiers, using official or source-declared
access paths before generic publisher fetching.

This POC is not classification. It does not mutate SQLite, review queues, review
decisions, or reviewed knowledge. Outputs are ignored local operational
artifacts.

## Commands

Build a local route plan:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router route
```

Fetch a bounded sample for one strategy:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router fetch \
  --strategy pmc_oai \
  --limit 25 \
  --delay-seconds 0.4
```

Summarize latest route and fetch outputs:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router summarize
```

Acquire PMC OAI XML and extracted text in resumable batches:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-pmc-oai \
  --limit 100 \
  --delay-seconds 0.5 \
  --max-bytes 8000000
```

The acquisition command skips records whose raw XML and extracted text files
already exist by default. Keep `--delay-seconds` at `0.5` unless there is a
specific reason to change it; PMC OAI-PMH documents a maximum of 3 requests per
second.

It also skips documents already attempted by earlier acquisition record files by
default, including failed attempts. Use `--no-skip-attempted` only when you want
to retry previous failures deliberately.

Acquire Unpaywall OA PDFs and extracted text in resumable batches:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-unpaywall-pdf \
  --limit 50 \
  --delay-seconds 0.5 \
  --max-bytes 20000000
```

This command uses PyMuPDF for digital PDF text extraction and routes downloaded
PDFs with weak or missing text as likely OCR/bad-text-layer cases. It does not
run OCR.

Acquire access/identity augmentation metadata:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router augment-ncbi-elink \
  --limit 200 \
  --delay-seconds 0.4

uv run python -m pocs.official_source_fetch_router.fetch_router augment-openalex \
  --limit 200 \
  --delay-seconds 0.2
```

These augmentation commands do not fetch full text. They save raw JSON and
normalized PMCID/DOI/OA URL/LinkOut hints for later source acquisition routes.

Acquire prioritized full text from augmented URLs:

```bash
uv run python -m pocs.official_source_fetch_router.fetch_router acquire-augmented-links \
  --limit 100 \
  --delay-seconds 0.5 \
  --max-bytes 20000000
```

This command is intentionally filtered, not generic. It skips documents that
already have source-ready text, ignores known non-source hosts such as
MedlinePlus, Ovid, ClinicalKey, Lens, Scite, and similar metadata/linkout
surfaces, and prioritizes:

1. PMC article links converted to PMC OAI-PMH;
2. PDF-like links;
3. selected publisher/repository HTML links;
4. DOI landing links.

## Strategy Order

1. `pmc_oai`: PMC OAI-PMH full-text XML for local or Europe PMC-discovered
   PMCIDs.
2. `europe_pmc_fulltextxml`: Europe PMC fullTextXML by PMCID or PMID.
3. `ncbi_elink`: NCBI ELink full-text/LinkOut discovery for PMID records.
4. `unpaywall_pdf`: existing Unpaywall OA PDF URLs.
5. `openalex_identity_access`: OpenAlex identity/OA augmentation.
6. `publisher_known_path`: bounded known publisher/DOI landing probes.

PMC content retrieval should use official PMC services such as OAI-PMH, FTP,
Cloud, E-Utilities, or BioC rather than systematic page scraping.

## Outputs

```text
data/normalized/official_source_fetch_router/
```

- `*_route_records.jsonl`: one route decision per source-availability candidate;
- `*_route_summary.json`: route counts and candidate ceiling;
- `*_fetch_records.jsonl`: bounded retrieval results;
- `*_fetch_summary.json`: extraction and failure counts.
- `*_acquire_records.jsonl`: source acquisition records with raw/text paths;
- `*_acquire_summary.json`: batch acquisition counts.

Acquired PMC OAI files are written under:

```text
data/raw/official_source_fetch_router/pmc_oai/
data/processed/official_source_fetch_router/pmc_oai/
data/raw/official_source_fetch_router/unpaywall_pdf/
data/processed/official_source_fetch_router/unpaywall_pdf/
data/raw/official_source_fetch_router/ncbi_elink/
data/raw/official_source_fetch_router/openalex_identity_access/
data/raw/official_source_fetch_router/augmented_links/
data/processed/official_source_fetch_router/augmented_links/
```

## First Probe Notes

Initial bounded probes on 2026-06-04 showed:

- `pmc_oai`: 10 / 10 HTTP success and 10 / 10 classification-ready source text.
- `ncbi_elink`: 9 / 10 HTTP success and 9 / 10 discovered OA/LinkOut URLs after
  JSON parsing was corrected.
- `openalex_identity_access`: 6 / 10 HTTP success and 5 / 10 discovered OA URLs
  in the first mixed DOI sample.
- `unpaywall_pdf`: 3 / 10 HTTP success and 3 / 10 classification-ready PDF text;
  the failures were access blocks.
- `publisher_known_path`: 5 / 10 HTTP success and 4 / 10 classification-ready
  text; failures were mostly access blocks.
- `europe_pmc_fulltextxml`: 0 / 10 in the first PMCID-based probe. Keep this
  strategy as experimental until the correct identifier/source pattern is
  validated against Europe PMC.

Operational interpretation: PMC OAI-PMH should be the first production-like
reenrichment route for local or Europe PMC-discovered PMCIDs.
