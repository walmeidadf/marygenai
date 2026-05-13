# Unpaywall POC

Goal: evaluate open-access metadata, license information, and PDF URLs without bulk-downloading PDFs.

Unpaywall enrichment is currently exercised through:

```bash
uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25
```

`UNPAYWALL_EMAIL` must be set in `.env` for DOI enrichment.
