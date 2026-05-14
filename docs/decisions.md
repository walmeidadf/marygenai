# Decision Log

## 2026-05-10: Use English Throughout The Project

All code, variables, filenames, comments, schemas, documentation, and CLI output should be written in English.

## 2026-05-10: Use Python 3.13+ And `uv`

The project uses Python 3.13+ and `uv` for virtual environment and dependency management.

## 2026-05-10: Start As A POC Lab

The project will start with source-specific POCs before committing to a production crawler, final database, or review interface.

## 2026-05-10: Keep Legacy Files Local

Legacy exports are useful for analysis but should not be committed. They are stored in `temp/legacy/`, and `temp/` is ignored by Git.

## 2026-05-10: Defer Database Choice

PostgreSQL, NoSQL, graph databases, and file-based approaches remain open options. The decision should follow source POC results and ontology modeling needs.

## 2026-05-10: Defer Review Interface Choice

Human review is required, but Label Studio is not yet a fixed decision. Any review workflow must preserve field-level review provenance.

## 2026-05-13: Treat PubMed As Metadata Hub Before Full-Text Crawling

PubMed/NLM is the primary publication identity and metadata source for the next
publication POCs. The project will first expand PubMed metadata testing, reconcile
legacy PubMed/NLM links, and classify full-text availability through PMC, Europe
PMC, Unpaywall, DOI, and publisher links before designing any continuous crawler or
bulk PDF workflow.

## 2026-05-13: Use PubMed As The Primary Study Discovery Source

For the publication-source track, PubMed is the current primary source for detecting
new candidate studies. It should be used to discover and prioritize records, while
PMC, Europe PMC, Unpaywall, DOI, and publisher links should be used later for
access enrichment. PubMed should not be treated as a direct file crawler.

## 2026-05-13: Prefer HTML/XML Before PDF For Full-Text Extraction

The first POC 6 sample showed that direct PMC HTML and structured full-text XML are
better first-choice extraction inputs than PDF. Europe PMC rendered article pages
should not be treated as stable static HTML fetch targets because they can return
JavaScript-dependent placeholder content. When a `PMCID` is available, the
pipeline should prefer PMC HTML and use Europe PMC full-text XML when available.
PDF retrieval should remain a narrow fallback or supplemental artifact until a PDF
parser is justified by extraction gaps.

All full-text extraction outputs remain candidate evidence until human review.

## 2026-05-13: Normalize LLM Evidence Through Strict Review-First Schemas

POC 6b keeps LLM extraction out of the final-truth role. LLMs and heuristics may
generate candidate evidence snippets and candidate values from section-scoped
text, but normalized POC outputs must pass strict Pydantic models and every field
must remain `needs_review=true` with `review_state=needs_review`.

Provider behavior should be recorded as provenance and operational evidence.
Local models may be useful for candidate discovery, while hosted models can be
used for structured comparison. Rate-limit headers, provider errors, and rejected
JSON are part of the POC result, not incidental noise.

## 2026-05-14: Use Review-Ready JSONL Rows Before Choosing A Review Tool

POC 6c uses field-level JSONL rows as the first human-review interchange format.
Each row preserves the source record id, field, candidate value, evidence text,
section, provider, model, confidence, ontology version, extractor version, and
empty review placeholders for reviewer identity, reviewed value, timestamp, and
notes.

This keeps the review contract explicit while deferring the final interface choice
between Label Studio, spreadsheet review, or a custom review UI.

## 2026-05-14: Treat Legacy As A Trusted Curated Reference

The legacy dataset should be used as a high-trust curated reference, not merely as
historical data. Populated legacy values can anchor validation and comparison for
identity, inclusion, study classification, conditions, compounds, and extracted
field values.

Missing legacy values should remain interpretable. For sparse or context-dependent
fields such as dosage and treatment duration, absence may mean `not_applicable` or
`not_reported`, especially for simpler studies or records without intervention,
control group, placebo, or protocol details.

## 2026-05-14: Separate Discovery From Full-Text Extraction

New-publication discovery should first associate PubMed results against the legacy
identity index and classify records as exact matches, possible matches, new
candidates, or manual identity-review items. Full-text access enrichment and
field extraction should run only after records are prioritized for inclusion.
