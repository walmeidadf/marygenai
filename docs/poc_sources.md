# POC Sources

POCs should be small, reproducible, and comparable. Each source experiment should produce a short summary with:

- query or collection criteria;
- total records returned;
- available fields;
- important missing fields;
- examples of strong and weak records;
- normalization complexity;
- legal and operational risks;
- recommendation: discard, keep as enrichment, or promote to adapter.

Initial sources:

- PubMed / NCBI E-utilities
- Europe PMC
- ClinicalTrials.gov
- Unpaywall
- Drugs.com or an equivalent source for drug interactions
- small PDF sample set

## Current Source Sequence

The current publication-source sequence is documented in
[PubMed Source Plan](pubmed_source_plan.md).

Near-term order:

1. Expanded PubMed metadata POC. Completed first validation pass on 2026-05-13.
2. Legacy PubMed/NLM reconciliation. Completed first local-only pass on 2026-05-13.
3. Full-text availability resolver across PubMed, PMC, DOI, and publisher links.
   Completed first local-only pass on 2026-05-13.
4. Europe PMC comparison and enrichment. Completed first small sample on
   2026-05-13.
5. Unpaywall DOI enrichment. Completed first sampled pass on 2026-05-13.
6. Small full-text and PDF sample. Next planned POC.
7. PubMed discovery expansion for high-reputation study types.

The project should not design a continuous crawler until these POCs show which
sources are reliable, which fields require full text, and which access paths are
lawful and operationally stable.
