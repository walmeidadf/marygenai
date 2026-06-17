# AGENTS.md

Guidance for AI agents working on MaryGenAI.

## Project Mission

MaryGenAI is a public research and engineering lab for building a reliable
cannabinoid scientific source-intelligence engine. The near-term goal is not to
ship a user-facing medical tool. The near-term goal is to build a reproducible
MVP for discovering candidate publications, resolving publication identity,
enriching metadata, acquiring source text when lawful and technically feasible,
preparing classification-ready corpora, and preserving provenance for automated
and human review layers.

The project may later expose classified scientific-document candidates through a
read-only MCP server so AI tools can find documents related to cannabinoid
medicine. AI classification outputs are candidate evidence only. They must not
be presented as reviewed clinical truth unless a human review workflow has
explicitly reviewed and promoted them.

The maintainer has private legacy exports that are used locally as a trusted
bootstrap and validation anchor. Those files are not part of the public
repository. Public contributors should treat reviewed snapshots produced by the
project as the future public baseline, not expect access to the private legacy
files.

## Core Rules

- Use English for all code, variables, filenames, comments, documentation, schemas, and CLI output.
- Use Python 3.13+.
- Use `uv` for virtual environment and dependency management.
- Do not commit generated data, raw downloads, secrets, PDFs, or local scratch files.
- Keep `data/` and `temp/` ignored by Git.
- Preserve legacy files in `temp/legacy/` unless the user explicitly asks to delete them.
- Do not document private legacy data as if it is publicly available.
- Keep public documentation clear that generated source-intelligence snapshots,
  candidate classifications, and future reviewed snapshots have different trust
  levels. Public users should not assume AI-classified records are human-reviewed.
- Prefer small POCs over production abstractions until a source has been evaluated.
- Record architecture decisions in `docs/decisions.md` when a meaningful choice is made.
- Keep MVP planning aligned with `docs/mvp_plan.md`.
- When comparing, evaluating, prompting from, or reporting against the legacy
  bootstrap for classification work, use normalized English legacy context first
  when it is available, especially `type_of_study`, `study_result`,
  `key_findings`, and English list fields from
  `data/normalized/legacy_english_context/`. Portuguese legacy fields such as
  `legacy_study_type` and `legacy_result` may remain operational fallback fields,
  but they should not be the primary analytic baseline when English legacy
  context exists.

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

For the maintainer's local environment, the private legacy bootstrap currently
loads thousands of publication records. The `legacy_identity_review` queue is
only the subset that lacks PMID, PMCID, and DOI; it is not the full amount of
useful legacy information.

The maintainer-local English legacy context is the preferred legacy reference
for classification prompts, model evaluation, and analysis reports when present.
Use it to avoid translating Portuguese legacy labels during scientific
classification comparisons.

For public users, Initial Load is useful as a reproducible import pathway and as
documentation of the private bootstrap process. Until public reviewed snapshots
are published, they can run source discovery and tests but should not expect the
private legacy CSVs to exist.

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

When working on review workflows, use `docs/review_status_guide.md` as the
canonical status vocabulary. Keep queue workflow status, document review state,
structured identity decisions, and PubMed candidate identity status separate.

## Public Documentation Expectations

- Write docs for people encountering the repository without private context.
- Separate maintainer-only local state from public reproducible workflows.
- Avoid implying that ignored `data/`, `temp/legacy/`, PDFs, raw downloads, or
  generated SQLite files are committed.
- When documenting current status, distinguish code capabilities from data that
  has been generated only in a local maintainer workspace.
- Public users should be guided toward PubMed discovery, reviewed snapshot
  exports, tests, and source adapters; private legacy bootstrap details should be
  framed as historical and maintainer-local context.

## MVP Prioritization

- `cannabinoid_focus` is the dominant prioritization signal and should outweigh
  citation metrics, recency, and general publication influence.
- Treat iCite and other citation metrics as secondary audit/enrichment signals,
  not as primary ranking inputs.
- Semantic Scholar is a later enrichment source, not a blocker for MVP design.
- The first MVP surface is a source discovery, source acquisition, candidate
  classification, and provenance workflow. Human curation remains required for
  reviewed knowledge, but it is no longer a blocker for building the source and
  AI-classification substrate.
- The first public-facing integration target is a read-only retrieval surface,
  potentially an MCP server over discovered, enriched, classification-ready, and
  candidate-classified scientific documents. It is not a clinical recommendation
  interface.

## Data Modeling Principles

- Treat source records, publications, clinical trial records, drug interaction documents, and PDFs as different document types.
- Do not force every record into an `article` model.
- Store extraction provenance: source, method, model/prompt version if applicable, confidence, evidence text, and review state.
- Separate raw source payloads from normalized records.
- Avoid premature commitment to PostgreSQL, NoSQL, or graph storage. Let POC findings drive that decision.

## Human Review

Human review is required before candidate evidence becomes reviewed knowledge,
but large-scale human curation is not a near-term assumption. Until reviewers are
available, automated classification should be clearly marked as candidate
evidence with extraction provenance and model/prompt version.

Label Studio is not yet a fixed choice. Any review workflow must preserve:

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
