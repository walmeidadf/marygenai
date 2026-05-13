# Legacy Dataset Notes

Legacy files are stored locally in `temp/legacy/` and ignored by Git.

## Files

- `colunas-ontologia.xlsx`
- `cannadocs/Estudos-Grid view.csv`
- `cannadocs/Canabinoides-Grid view.csv`
- `cannadocs/Condicoes Medicas-Grid view.csv`
- `cannadocs/Sistemas do Organismo-Grid view.csv`
- `cannadocs/Terpenos-Grid view.csv`
- `cannadocs/Glossario-Grid view.csv`
- `cannadocs/Calculadora-Grid view.csv`

Some filenames contain accents because they came from the legacy export.

## Observations From Initial Profiling

The studies table has 7,347 rows, 7,347 unique URLs, and 7,347 unique study IDs. Study ID `6245` is missing from the numeric sequence. There are 17 duplicate English titles and 12 duplicate Portuguese titles.

The dataset is strongly PubMed/NLM-oriented:

- `nlm.nih.gov`: 5,491 studies;
- `www.sciencedirect.com`: 379;
- `onlinelibrary.wiley.com`: 179;
- `www.mdpi.com`: 129;
- `www.frontiersin.org`: 103.

Top legacy study types:

- `Metanalise`: 3,176;
- `Estudo Animal`: 1,634;
- `Estudo Laboratorial`: 971;
- `Ensaio Clinico`: 751;
- `Ensaio Clinico Duplo-Cego`: 575;
- `Metanalise Clinica`: 240.

Top medical conditions by split count:

- pain;
- cancer;
- inflammation;
- cannabis adverse effects;
- dependence;
- anxiety;
- cannabis dependence;
- chronic pain;
- cardiovascular disease;
- depression;
- epilepsy.

Sparse fields:

- dosage: about 12%;
- treatment duration: about 3%;
- adverse events: about 2%;
- starting dose and maximum dose: about 1%.

These sparse fields should not be treated as reliable default metadata from abstract-only extraction.

## Legacy Reconciliation POC

The first local-only reconciliation pass ran on 2026-05-13.

Results:

- 7,347 legacy study rows parsed;
- 3,805 rows with directly extracted `PMID`;
- 1,676 rows with directly extracted `PMCID`;
- 659 rows with directly extracted DOI;
- 6,140 rows, or 83.6%, with `PMID`, `PMCID`, or DOI;
- 1,207 rows need a resolver or manual review because only a canonical URL was
  available.

The reconciliation script is:

```bash
uv run python pocs/legacy_reconciliation/reconcile_legacy.py run
```

Outputs are local and ignored under `data/normalized/legacy_reconciliation/`.

## Link Resolver POC

The first local-only link resolver pass ran on 2026-05-13 using the reconciliation
output above.

Results:

- 7,347 records classified;
- 1,676 records with direct PMC full-text path from `PMCID`;
- 3,805 PMID-only records requiring PubMed or Europe PMC enrichment;
- 659 DOI records requiring Unpaywall or Europe PMC enrichment;
- 1,207 publisher/other URL records requiring identifier extraction or title search.

The resolver script is:

```bash
uv run python pocs/link_resolver/resolve_links.py run
```

Outputs are local and ignored under `data/normalized/link_resolver/`.

## Access Enrichment POC

The first Europe PMC plus Unpaywall enrichment pass ran on 2026-05-13.

Results:

- 20 resolver records sampled;
- Europe PMC queried for 20 records;
- Europe PMC found 15 records;
- Unpaywall queried for 20 DOI lookups;
- Unpaywall found 16 records;
- Unpaywall marked 11 records as open access;
- Unpaywall exposed 7 PDF URLs;
- 10 records had open-access PDF candidates;
- 1 record had an open-access landing candidate;
- 4 records had metadata enrichment without full text;
- 4 records were not enriched;
- 0 records had enrichment errors.

The enrichment script is:

```bash
uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 10
```

Outputs are local and ignored under `data/normalized/access_enrichment/` and
`data/raw/access_enrichment/`.
