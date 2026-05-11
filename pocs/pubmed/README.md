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
