# PubMed POC

Goal: test E-utilities for small searches, bibliographic metadata, and PMID/DOI/abstract availability.

## Validation script

Run a small validation batch:

```bash
uv run python pocs/pubmed/validate_pubmed.py run --retmax 25
```

The script reads `PUBMED_API_KEY` from `.env`. `PUBMED_EMAIL` is optional but recommended
for NCBI E-utilities requests.

Outputs are split by architecture layer:

- `data/raw/pubmed/*_esearch.json`: raw PubMed search response;
- `data/raw/pubmed/*_efetch.xml`: raw PubMed XML response;
- `data/normalized/pubmed/*_records.jsonl`: one extracted metadata record per PMID;
- `data/normalized/pubmed/*_summary.json`: source-level counts and metadata availability metrics.

The default query targets broad cannabinoid terms in titles and abstracts. Override it
when testing narrower ontology concepts:

```bash
uv run python pocs/pubmed/validate_pubmed.py run \
  --query '"cannabidiol"[Title/Abstract] AND epilepsy[Title/Abstract]' \
  --retmax 50
```

## POC 1: Expanded PubMed Metadata

Run named batches of up to 200 records across several cannabinoid-focused query
families:

```bash
uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100
```

Planned query families:

- broad cannabinoid query;
- cannabidiol plus epilepsy;
- THC plus pain;
- cannabis plus adverse effects;
- human, animal, in vitro, and review-focused filters where useful.

The expanded POC should measure `PMID`, DOI, `PMCID`, abstract, MeSH headings,
chemicals, keywords, publication types, publication status, authors, journal, date,
and language. See [PubMed Source Plan](../../docs/pubmed_source_plan.md) for the
full source plan.

First completed run:

- run id: `20260513T154941Z`;
- query families: 8;
- records fetched and normalized: 790;
- DOI availability: 768 / 790;
- `PMCID` availability: 415 / 790;
- abstract availability: 778 / 790.
