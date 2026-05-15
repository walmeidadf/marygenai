# MaryGenAI

MaryGenAI is a research and engineering lab for scientific data sources,
ontology design, and human-reviewed curation of cannabinoid therapy evidence.

## Current Goal

The project has moved from isolated source POCs toward an MVP plan for an
internal review and curation platform. The MVP should validate the curated legacy
dataset, discover candidate publications from the end of legacy coverage onward,
enrich those candidates with validated source flows, and preserve field-level
human review provenance.

The MVP is not a medical advice product. It catalogs evidence and metadata for
human-reviewed scientific curation.

POCs remain useful for testing source quality and should continue to measure:

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
uv run marygenai initial-load run
uv run marygenai db init
uv run marygenai initial-load persist
```

## Documentation

- [Project brief](docs/project_brief.md)
- [MVP plan](docs/mvp_plan.md)
- [Architecture approach](docs/architecture.md)
- [MVP architecture requirements](docs/mvp_architecture_requirements.md)
- [Roadmap](docs/roadmap.md)
- [Data sources](docs/data_sources.md)
- [PubMed source plan](docs/pubmed_source_plan.md)
- [Ontology notes](docs/ontology.md)
- [Legacy dataset notes](docs/legacy_dataset.md)
- [Decision log](docs/decisions.md)

## Common Commands

- MVP Initial Load: `uv run marygenai initial-load run`
- Create ignored local data layout: `uv run marygenai initial-load setup-data`
- Initialize local SQLite review DB: `uv run marygenai db init`
- Persist latest Initial Load snapshot to SQLite: `uv run marygenai initial-load persist`
- PubMed expanded metadata: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`
- Legacy reconciliation: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`
- Link resolver: `uv run python pocs/link_resolver/resolve_links.py run`
- Access enrichment: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25`
- PubMed discovery window: `uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100 --datetype pdat --mindate 2025/04/01 --maxdate 2025/04/30`
- iCite enrichment: `uv run python -m pocs.icite_enrichment.enrich_icite run --input-path <pubmed_discovery_records.jsonl>`

## MVP Direction

The MVP review queue should be dominated by `cannabinoid_focus`. Records with
direct cannabinoid evidence in title or indexed metadata belong in the primary
review queue. Abstract-only records require more caution, and records without a
cannabinoid signal should not be automatically promoted by citation metrics or
general publication influence.

## MVP Initial Load

The first MVP implementation is available as a package command:

```bash
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

It reads the legacy Cannadocs CSV exports from `temp/legacy/cannadocs/`, creates
the ignored local `data/` layout, and writes JSONL snapshots plus a run manifest.
The JSONL snapshots remain the auditable interchange record. The SQLite database
at `data/db/marygenai.sqlite` is the local operational state for review queues
and later review workflow APIs.

The current JSONL outputs are:

- legacy source records under `data/staging/source_records/legacy/`;
- canonical publication candidates under `data/normalized/publications/`;
- ontology entities and document-to-ontology links under
  `data/normalized/ontology/ontology_mappings/`;
- run manifests under `data/manifests/runs/`.

The first SQLite persistence command loads the latest Initial Load run by default
or a specific run with `--run-id`. It populates `run_manifest`, `source_record`,
`document`, `document_identity`, `publication`, `ontology_entity`,
`document_ontology_link`, and a minimal `legacy_identity_review` queue for legacy
publication candidates that lack PMID, PMCID, and DOI.

Generated `data/` files remain ignored by Git. Old POC artifacts should be kept
out of the active MVP workspace, either regenerated from POC commands when needed
or archived locally under `temp/scratch/`.
