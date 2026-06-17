# MaryGenAI

MaryGenAI is a research and engineering lab for cannabinoid scientific source
intelligence: publication discovery, identity resolution, metadata enrichment,
source-text acquisition, classification-ready corpus preparation, and
provenance-aware candidate study classification.

Parts of this project were developed using AI development tools and will still be reviewed by a human.

## Current Goal

The project has pivoted from a review-first knowledge-base MVP toward a
source-intelligence and candidate-classification engine. The near-term product is
an auditable pipeline that can discover scientific documents related to
cannabinoid medicine, enrich them with trusted identifiers and metadata, acquire
usable source text when allowed, and prepare candidate classifications for later
human review.

The maintainer workflow currently discovers PubMed candidate publications,
enriches selected candidates with validated source flows, evaluates whether real
source text is available for classification, and keeps generated outputs separate
from reviewed knowledge.

The MVP is not a medical advice product. It catalogs scientific documents,
source provenance, and candidate evidence for downstream AI-assisted discovery,
classification, and later human curation. A future read-only MCP server may
expose discovered, enriched, and candidate-classified scientific documents to AI
tools.

## Structure

```text
data/                 # generated local data; ignored by Git
ontology/             # versioned vocabularies and ontology artifacts
pocs/                 # source-specific experiments
src/marygenai/        # shared POC utilities
tests/                # automated tests
docs/                 # architecture notes and decisions
```


## Setup

This project requires Python 3.13+ and uses `uv` for virtual environment and dependency management.

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai db init
uv run pytest
uv run ruff check .
```

```bash
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

PubMed discovery can be run after a local database has a baseline identity index.

```bash
uv run marygenai pubmed-discovery run --datetype pdat --mindate 2024/01/01 --maxdate 2024/01/31 --retmax 100
uv run marygenai access-enrichment run --limit 50
uv run marygenai review queues
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

## Documentation

- [Project brief](docs/project_brief.md)
- [MVP plan](docs/mvp_plan.md)
- [Classification dataset and schema plan](docs/classification_dataset_plan.md)
- [Architecture approach](docs/architecture.md)
- [MVP architecture requirements](docs/mvp_architecture_requirements.md)
- [Roadmap](docs/roadmap.md)
- [Data sources](docs/data_sources.md)
- [Source availability assessment](docs/source_availability_assessment.md)
- [PubMed source plan](docs/pubmed_source_plan.md)
- [Ontology notes](docs/ontology.md)
- [Legacy dataset notes](docs/legacy_dataset.md)
- [Decision log](docs/decisions.md)

## Common Commands

- MVP Initial Load, maintainer only until public snapshots exist:
  `uv run marygenai initial-load run`
- Create ignored local data layout: `uv run marygenai initial-load setup-data`
- Initialize local SQLite review DB: `uv run marygenai db init`
- Persist latest Initial Load snapshot to SQLite: `uv run marygenai initial-load persist`
- Discover and stage PubMed candidates for a specific month:
  `uv run marygenai pubmed-discovery run --datetype pdat --mindate 2024/01/01 --maxdate 2024/01/31 --retmax 100`
- Persist an existing PubMed discovery run:
  `uv run marygenai pubmed-discovery persist --run-id <run_id>`
- Run targeted access/full-text enrichment for prioritized PubMed candidates:
  `uv run marygenai access-enrichment run --limit 50`
- List local review queues: `uv run marygenai review queues`
- List open legacy identity review items:
  `uv run marygenai review list --queue legacy_identity_review`
- List open PubMed candidate review items:
  `uv run marygenai review list --queue publication_candidate_review`
- Show review detail for an item or publication:
  `uv run marygenai review show <review_item_id_or_document_id>`
- Update review item status:
  `uv run marygenai review update <review_item_id> --status in_review --note "Review started"`
- Save a structured legacy identity decision:
  `uv run marygenai review decision-create <review_item_id> --reviewer reviewer@example.org --decision confirmed_identity --rationale "Identity confirmed"`
- Apply the latest structured identity decision to workflow state:
  `uv run marygenai review decision-apply <review_item_id>`
- List structured identity decisions:
  `uv run marygenai review decision-list <review_item_id_or_document_id>`
- Serve the local review API:
  `uv run marygenai review-api serve --host 127.0.0.1 --port 8000`
- Serve the first local review UI and API:
  `uv run marygenai review-ui serve --host 127.0.0.1 --port 8000`
- PubMed expanded metadata: `uv run python pocs/pubmed/validate_pubmed.py batch --retmax 100`
- Legacy reconciliation: `uv run python pocs/legacy_reconciliation/reconcile_legacy.py run`
- Link resolver: `uv run python pocs/link_resolver/resolve_links.py run`
- Access enrichment: `uv run python pocs/access_enrichment/enrich_access.py run --limit-per-class 25`
- PubMed discovery window: `uv run python -m pocs.pubmed_discovery.discover_pubmed run --retmax 100 --datetype pdat --mindate 2025/04/01 --maxdate 2025/04/30`
- iCite enrichment: `uv run python -m pocs.icite_enrichment.enrich_icite run --input-path <pubmed_discovery_records.jsonl>`

Review status meanings are documented in
[`docs/review_status_guide.md`](docs/review_status_guide.md). Start there when
onboarding a reviewer or explaining the difference between queue workflow status,
legacy identity decisions, and PubMed candidate identity status.

## MVP Direction

The MVP should first produce a classification substrate: a deduplicated
classification-ready corpus rollup, a strict classification schema, and a small
stratified candidate-classification POC. Current local provider tests favor
OpenAI `gpt-5.4-mini` for the next 100-document cost and quality gate before any
full-corpus classification run. Classification evaluation should use the
maintainer-local English legacy context first when present, rather than
Portuguese legacy labels. `cannabinoid_focus` remains the dominant
prioritization signal. Records with direct cannabinoid evidence in title,
indexed metadata, or usable source text belong in the primary queue. Abstract-only
records require caution, and records without a cannabinoid signal should not be
automatically promoted by citation metrics or general publication influence.

Trust levels must remain explicit:

- `source_discovered`: metadata or identity exists, source text not necessarily
  available.
- `metadata_enriched`: identifiers and source metadata were enriched.
- `source_text_available`: real source text exists and passed quality gates.
- `ai_classified_candidate`: an AI/model output exists and is candidate evidence.
- `human_reviewed`: a reviewer promoted or corrected the candidate record.

## MVP Initial Load, Maintainer Bootstrap

The first MVP bootstrap implementation is available as a package command:

```bash
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

It reads the legacy data, and writes JSONL snapshots plus a run manifest.
The JSONL snapshots remain the auditable interchange record. The SQLite database at `data/db/marygenai.sqlite` is the local operational state for review queues
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

New public users should not expect these private CSVs to exist. The intended
public entry point is a reviewed snapshot export once the maintainer workflow has
produced one.

The first review CLI inspects that operational queue without changing JSONL
snapshots:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review show <review_item_id_or_document_id>
uv run marygenai review update <review_item_id> --status resolved --note "Identity confirmed"
```

The first local FastAPI layer serves the same review state for a future UI:

```bash
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
```

Initial endpoints:

- `GET /health`
- `GET /review/queues`
- `GET /review/queues/{queue_type}/items?status=open|in_review|resolved|dismissed|all&limit=20`
- `GET /review/items/{review_item_id}`
- `GET /review/items/{review_item_id}/identity-decisions`
- `POST /review/items/{review_item_id}/identity-decisions`
- `POST /review/items/{review_item_id}/identity-decisions/apply`
- `GET /publications/{document_id}`
- `GET /publications/{document_id}/identity-decisions`
- `PATCH /review/items/{review_item_id}/status`

The API reads `data/db/marygenai.sqlite` by default, mutates only operational
SQLite review state for status updates, and leaves JSONL snapshots unchanged.
See [`docs/review_status_guide.md`](docs/review_status_guide.md) for the
canonical explanation of `open`, `in_review`, `resolved`, `dismissed`,
structured identity decisions, and PubMed candidate identity statuses.

The first local review UI is served by the same FastAPI app at `/ui`:

```bash
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/ui` to inspect API health, queue totals, open
`legacy_identity_review` items, publication detail, legacy reference values,
ontology links, identity signals, workflow status updates, and structured legacy
identity decisions with reviewed PMID, PMCID, DOI, canonical URL, rationale,
reviewer, original identity signals, and provenance. PubMed candidate review is
available through the CLI and API; adding first-class UI filters for
`publication_candidate_review`, `needs_manual_identity_review`, `new_candidate`,
`direct_title_or_indexed`, `high_auto_full_text`, and
`high_manual_full_text` is the next UI improvement. Status remains operational
workflow state; identity decisions are saved as separate curation records. The UI
keeps saving an identity decision separate from applying the latest applicable
decision to the local workflow status. Applying a `confirmed_identity` or
`corrected_identity` decision resolves the item, applying `not_same_publication`
dismisses it, and `unresolved` remains a saved decision that does not close the
item. This UI is an internal review and curation surface, not a clinical or
public product.

The local maintainer database currently uses the private legacy bootstrap as a
trusted reference. The `legacy_identity_review` queue contains only legacy
records that lack PMID, PMCID, and DOI; it is not the full legacy corpus. Most of
the legacy publication records have usable identifiers and are already useful for
comparison and deduplication.

Generated `data/` files remain ignored by Git. Old POC artifacts should be kept
out of the active MVP workspace, either regenerated from POC commands when needed
or archived locally under `temp/scratch/`.

## PubMed Candidate Discovery

The first post-legacy enrichment slice is available through:

```bash
uv run marygenai pubmed-discovery run --retmax 100
```

By default the command anchors the search to the latest baseline publication year
stored in local SQLite and starts one year earlier as a small overlap window. The
current maintainer plan is to run explicit monthly windows from `2024/01/01`
through the current date. It uses PubMed E-utilities for discovery and metadata,
writes ignored audit
snapshots under `data/staging/source_records/pubmed/`,
`data/normalized/publication_enrichments/pubmed/`,
`data/normalized/review_items/`, and `data/manifests/`, then persists
non-exact candidates to SQLite as `needs_review` publication records.

Candidates are classified against the baseline index as `in_legacy_exact`,
`possible_legacy_match`, `needs_manual_identity_review`, or `new_candidate`.
Only non-exact candidates enter the `publication_candidate_review` queue. They
are not reviewed knowledge and remain separate from the Initial Load JSONL
snapshots.

After discovery, access and full-text enrichment can run in parallel with human
review for prioritized candidates. Start with `direct_title_or_indexed` records
that have `full_text_review_priority='high_auto_full_text'`, and avoid file
retrieval for `needs_manual_identity_review` records until identity is checked.
The preferred retrieval order is PMC HTML/NXML, Europe PMC XML/full-text
metadata, Unpaywall open-access locations, and then narrow PDF fallback. Retrieved
payloads and files must remain under ignored `data/` paths with provenance and
must not be treated as reviewed knowledge.

The first operational access enrichment command is:

```bash
uv run marygenai access-enrichment run --limit 50
```

By default it selects unique SQLite candidates from `publication_candidate_discovery`
where `cannabinoid_focus='direct_title_or_indexed'` and
`full_text_review_priority='high_auto_full_text'`, excluding
`identity_status='needs_manual_identity_review'` and candidates that already have
at least one `access_enrichment_artifact` row. This makes repeated limited runs
advance through new eligible candidates. Use `--refresh-existing` for deliberate
re-enrichment, or `--no-skip-enriched` when testing compatibility behavior. It
writes raw PMC, Europe PMC, and Unpaywall payloads plus normalized access
enrichment snapshots and run manifests under ignored `data/` paths, and persists
artifact provenance in SQLite without changing candidate review state or
promoting outputs to reviewed knowledge.

To run incremental overnight access batches, use the helper script. It defaults
to 20 batches, 50 candidates per batch, and a 30 second delay between batches:

```bash
uv run python scripts/access_enrichment_batches.py
```

Tune the batch count, limit, and delay when needed:

```bash
uv run python scripts/access_enrichment_batches.py --batches 10 --limit 25 --sleep-seconds 60
```

Pass access-enrichment filters after `--`:

```bash
uv run python scripts/access_enrichment_batches.py -- --cannabinoid-focus direct_title_or_indexed --full-text-priority high_auto_full_text
```

The local API exposes candidate inspection at:

- `GET /publication-candidates`
- `GET /publication-candidates/{document_id}/provenance`

The review queue item listing also accepts candidate-oriented filters for the
local UI, for example:

- `GET /review/queues/publication_candidate_review/items?identity_status=needs_manual_identity_review`
- `GET /review/queues/publication_candidate_review/items?priority_tier=direct_title_or_indexed`
- `GET /review/queues/publication_candidate_review/items?full_text_review_priority=high_auto_full_text`

To backfill many months in sequence, use the helper script. It defaults to
`2024-06-01` because the maintainer backfill has already run January through May
2024 locally:

```bash
uv run python scripts/pubmed_monthly_backfill.py
```

Preview the month windows without calling PubMed:

```bash
uv run python scripts/pubmed_monthly_backfill.py --dry-run
```

Override the date range when needed:

```bash
uv run python scripts/pubmed_monthly_backfill.py --start-date 2024/01/01 --end-date 2024/12/31 --retmax 200
```

Monthly PubMed windows are audit batches, not guaranteed disjoint sets. PubMed
can return the same PMID in more than one month because the E-utilities
publication-date filter does not always match the normalized publication date
extracted from XML. The SQLite operational queue deduplicates by publication
document id, so use `publication_candidate_discovery` or `marygenai review
queues` for the unique review backlog instead of summing monthly JSONL counts.
