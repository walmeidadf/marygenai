# AGENTS.md

Guidance for AI agents working on MaryGenAI.

## Project Mission

MaryGenAI is a research and engineering lab for building a reliable, human-reviewed cannabinoid evidence knowledge base. The near-term goal is not to ship a user-facing medical tool. The near-term goal is to evaluate data sources, shape the ontology, and learn which extraction strategies are trustworthy.

## Core Rules

- Use English for all code, variables, filenames, comments, documentation, schemas, and CLI output.
- Use Python 3.13+.
- Use `uv` for virtual environment and dependency management.
- Do not commit generated data, raw downloads, secrets, PDFs, or local scratch files.
- Keep `data/` and `temp/` ignored by Git.
- Preserve legacy files in `temp/legacy/` unless the user explicitly asks to delete them.
- Prefer small POCs over production abstractions until a source has been evaluated.
- Record architecture decisions in `docs/decisions.md` when a meaningful choice is made.

## Common Commands

```bash
uv sync --extra dev
uv run marygenai info
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
