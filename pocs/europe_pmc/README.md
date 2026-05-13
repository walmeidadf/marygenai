# Europe PMC POC

Goal: compare coverage, metadata, and full-text/open-access availability against PubMed.

Europe PMC enrichment is currently exercised through:

```bash
uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25
```
