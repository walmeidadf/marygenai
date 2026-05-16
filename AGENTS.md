# AGENTS.md

Guidance for AI agents working on MaryGenAI.

## Project Mission

MaryGenAI is a research and engineering lab for building a reliable,
human-reviewed cannabinoid evidence knowledge base. The near-term goal is not to
ship a user-facing medical tool. The near-term goal is to build an internal MVP
for validating the legacy dataset, discovering new candidate publications,
enriching them through validated source flows, and preserving review provenance.

## Core Rules

- Use English for all code, variables, filenames, comments, documentation, schemas, and CLI output.
- Use Python 3.13+.
- Use `uv` for virtual environment and dependency management.
- Do not commit generated data, raw downloads, secrets, PDFs, or local scratch files.
- Keep `data/` and `temp/` ignored by Git.
- Preserve legacy files in `temp/legacy/` unless the user explicitly asks to delete them.
- Prefer small POCs over production abstractions until a source has been evaluated.
- Record architecture decisions in `docs/decisions.md` when a meaningful choice is made.
- Keep MVP planning aligned with `docs/mvp_plan.md`.

## Common Commands

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai initial-load run
uv run marygenai db init
uv run marygenai initial-load persist
uv run ruff check .
uv run pytest
```

## Repository Layout

```text
data/                 # generated datasets and raw POC outputs, ignored
temp/                 # local scratch and legacy files, ignored
ontology/             # versioned vocabularies and ontology artifacts
pocs/                 # source-specific experiments
src/marygenai/        # shared utilities
tests/                # automated tests
docs/                 # project memory and design notes
```

## POC Philosophy

Each source POC should answer:

- What records can this source provide?
- Which ontology fields can it populate directly?
- Which fields require inference, full text, or human review?
- How stable and lawful is the access method?
- Should this source become a production adapter, enrichment source, or be discarded?

POCs may write outputs to `data/`, but should include enough code and notes to reproduce the experiment.
Keep POC outputs separate from MVP Initial Load outputs. If old local artifacts
make `data/` noisy, archive them under `temp/scratch/` rather than committing
them or mixing them with current MVP snapshots.

## MVP Initial Load

The first MVP implementation lives in `src/marygenai/initial_load/` and writes
auditable JSONL snapshots plus run manifests under ignored `data/` paths.

```bash
uv run marygenai initial-load setup-data
uv run marygenai initial-load run
```

The current Initial Load reads legacy Cannadocs CSVs from
`temp/legacy/cannadocs/`, handles Unicode filenames without renaming them,
normalizes legacy source records, canonical publication candidates, ontology
entities, document-to-ontology links, and run metadata. SQLite persistence under
`src/marygenai/persistence/` now loads those snapshots into
`data/db/marygenai.sqlite` as local operational review state.

The current review surface includes:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

The first UI is available at `http://127.0.0.1:8000/ui` and is an internal
review and curation surface for `legacy_identity_review`, not a clinical or
public product.

## MVP Prioritization

- `cannabinoid_focus` is the dominant prioritization signal and should outweigh
  citation metrics, recency, and general publication influence.
- Treat iCite and other citation metrics as secondary audit/enrichment signals,
  not as primary ranking inputs.
- Semantic Scholar is a later enrichment source, not a blocker for MVP design.
- The first MVP surface is a review and curation workflow, not a clinical
  recommendation interface.

## Data Modeling Principles

- Treat source records, publications, clinical trial records, drug interaction documents, and PDFs as different document types.
- Do not force every record into an `article` model.
- Store extraction provenance: source, method, model/prompt version if applicable, confidence, evidence text, and review state.
- Separate raw source payloads from normalized records.
- Avoid premature commitment to PostgreSQL, NoSQL, or graph storage. Let POC findings drive that decision.

## Human Review

Human review is a project requirement, but Label Studio is not yet a fixed choice. Any review workflow must preserve:

- reviewer identity;
- reviewed field;
- original value;
- reviewed value;
- review timestamp;
- notes or rationale;
- ontology version;
- extractor version.

## Safety Boundary

This project catalogs evidence and metadata. It must not present outputs as medical advice or treatment recommendations.
