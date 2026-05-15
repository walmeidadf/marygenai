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
6. Small full-text and PDF sample, followed by evidence extraction and review
   export. Completed first local review-export pass on 2026-05-14.
7. Legacy-anchored PubMed discovery for high-reputation study types. Implemented
   and validated on 2026-05-14 and 2026-05-15.
8. NIH iCite citation enrichment. Implemented as a cost-benefit evaluation on
   2026-05-14 and validated on an older April 2025 window on 2026-05-15.
9. MVP review and curation platform. Proposed next; see [MVP Plan](mvp_plan.md).

The project should not design a broad continuous crawler yet. The next step is an
internal MVP that turns the validated POC flows into a review queue and reviewed
knowledge export.
