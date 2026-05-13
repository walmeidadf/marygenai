# MaryGenAI

MaryGenAI is a POC lab for scientific data sources, ontology design, and human-reviewed curation of cannabinoid therapy evidence.

## Initial Goal

Before choosing a database, production crawler, or review interface, this project will test small batches from candidate data sources and measure:

- result volume and relevance;
- available metadata quality;
- parsing and normalization complexity;
- usefulness for the cannabinoid ontology;
- when HTML, XML, full text, or PDF processing is actually needed.

## Structure

```text
data/                 # POC-generated data; ignored by Git
temp/                 # legacy files and local scratch space; ignored by Git
ontology/             # versioned vocabularies and ontology artifacts
pocs/                 # source-specific experiments
src/marygenai/        # shared POC utilities
tests/                # automated tests
docs/                 # architecture notes and decisions
```

Legacy files are preserved locally in `temp/legacy/`.

## Setup

This project requires Python 3.13+ and uses `uv` for virtual environment and dependency management.

```bash
uv sync --extra dev
uv run marygenai info
```

## Documentation

- [Project brief](docs/project_brief.md)
- [Architecture approach](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Data sources](docs/data_sources.md)
- [PubMed source plan](docs/pubmed_source_plan.md)
- [Ontology notes](docs/ontology.md)
- [Legacy dataset notes](docs/legacy_dataset.md)
- [Decision log](docs/decisions.md)

## Active POCs

- PubMed expanded metadata: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`
- Legacy reconciliation: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`
- Link resolver: `uv run python pocs/link_resolver/resolve_links.py run`
- Access enrichment: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25`
