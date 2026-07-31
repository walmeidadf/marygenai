# AGENTS.md

Guidance for AI agents working on MaryGenAI.

## Project Mission

MaryGenAI is a public research and engineering project building a reliable
cannabinoid scientific source-intelligence and candidate-classification engine.
Its value is to make medical literature easier to discover, filter, inspect, and
verify through structured metadata, evidence-backed AI classifications, and
provenance.

The first external integration is an implemented read-only MCP pilot used by
tools such as ChatGPT and Claude. A physician should be able to filter studies
by condition, cannabinoid, study type, population, outcome, and confidence,
then inspect the original sources.

AI classifications are probabilistic retrieval metadata and candidate evidence.
They are not reviewed clinical truth, medical advice, or treatment
recommendations.

## Product Quality Boundary

Treat uncertainty in three distinct ways:

1. Scientific or interpretive uncertainty is legitimate product information. It
   should be declared and supported by evidence.
2. Source insufficiency should lower confidence and remain visible in provenance.
3. Known schema, prompt, model-parameter, source-routing, or pipeline defects
   should be improved rather than accepted as unavoidable uncertainty.

Current `classification_confidence` values are categorical model assessments,
not calibrated probabilities. Do not describe them as statistically calibrated
scores. Future retrieval confidence may combine source quality, evidence support,
metadata agreement, repeated-run consistency, and validation against trusted
references.

Evaluate classification work in three groups:

- technical validity: provider success, valid JSON, schema pass rate, retries,
  latency, and cost;
- retrieval utility: filter coverage, evidence-span presence, source
  traceability, and whether relevant documents remain discoverable;
- inference quality: agreement with trusted references, uncertainty quality,
  unsupported claims, systematic errors, and calibration.

## Core Rules

- Use English for all code, variables, filenames, comments, documentation,
  schemas, and CLI output.
- Use Python 3.13+ and `uv`.
- Keep supported code under `src/marygenai/`.
- Public commands must be exposed through the `marygenai` CLI.
- Do not add public standalone POC runners when a package command is the intended
  supported interface.
- Preserve durable experimental findings in `docs/experimental_findings.md` or
  `docs/decisions.md`.
- Keep private inputs, historical experiment implementations, generated data,
  raw downloads, PDFs, secrets, and scratch files under ignored `data/` or
  `temp/` paths.
- Preserve legacy files in `temp/legacy/` unless the user explicitly asks to
  delete them.
- Do not document private legacy data as publicly available.
- Record meaningful architecture or product choices in `docs/decisions.md`.
- Keep the product contract aligned with `docs/product_value.md`.
- Keep implementation priorities aligned with `docs/mvp_plan.md` and
  `docs/roadmap.md`.
- Read `docs/2026-07-31_mcp_pilot_handoff.md` before planning MCP, source
  discovery, enrichment, deployment, or physician-pilot work.
- Use `docs/2026-07-11_batch_and_mcp_handoff.md` and
  `docs/2026-07-17_identity_and_mcp_handoff.md` as historical Batch and identity
  context, not as the current operating state.
- Do not place patient-identifying data in MCP queries, logs, evaluation
  artifacts, or demonstration notes.
- MCP results must remain candidate matches. Preserve zero-result scope,
  preferred physician-facing access URLs, study-detail inspection before
  detailed claims, and separation of direct from tangential matches.

## Protected State

Do not mutate SQLite, `review_state`, `review_item`, `review_decision`, review
queues, or reviewed knowledge during source acquisition, corpus preparation,
classification, evaluation, or documentation work unless the user explicitly
requests a review workflow operation.

Classification outputs must remain ignored local candidate-evidence artifacts.

## Legacy Evaluation

The maintainer has private legacy exports used locally as a trusted bootstrap and
validation anchor. They are not public repository inputs.

For classification prompts, comparisons, and reports, prefer normalized English
legacy context from `data/normalized/legacy_english_context/`, especially:

- `type_of_study`;
- `study_result`;
- `key_findings`;
- English list fields such as cannabinoids studied.

Portuguese fields such as `legacy_study_type` and `legacy_result` may remain
traceability or fallback fields, but they are not the primary analytic baseline
when English context exists.

Legacy agreement is a strong evaluation signal, not an instruction to copy the
legacy label when source evidence clearly differs. Preserve disagreements for
analysis with evidence and confidence.

## Supported Repository Layout

```text
src/marygenai/        # supported package code
tests/                # supported package tests
docs/                 # current public documentation and project memory
ontology/             # versioned ontology contracts and artifacts
scripts/              # thin orchestration around supported CLI commands
infra/terraform/      # versioned read-only MCP cloud infrastructure
infra/lambda/         # locked minimal Lambda runtime requirements
data/                 # generated local artifacts, ignored
temp/                 # private inputs, archived experiments, scratch, ignored
build/                # generated deployment packages, ignored
```

Historical POC implementations may be kept locally under
`temp/project_archive/`. Do not restore them to the public surface unless a
specific experiment is being promoted into a supported `src/marygenai/` command
with tests and documentation.

## Common Commands

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai --help
uv run marygenai db init
uv run marygenai pubmed-discovery --help
uv run marygenai access-enrichment --help
uv run marygenai classification-corpus --help
uv run marygenai classification --help
uv run ruff check .
uv run pytest
```

Batch operating pattern for an explicitly approved new or changed corpus:

```bash
uv run marygenai classification prepare-batch \
  --limit 150 \
  --offset <offset> \
  --input-path data/normalized/classification_corpus/20260617T142419Z_classification_corpus_records.jsonl \
  --dataset-split strict_classification_ready \
  --model gpt-5.4-mini \
  --max-source-chars 12000 \
  --max-completion-tokens 3000
uv run marygenai classification submit-batch \
  --batch-input-path data/normalized/classification_batches/<run_id>_openai_batch_input.jsonl \
  --manifest-path data/normalized/classification_batches/<run_id>_openai_batch_manifest.jsonl
uv run marygenai classification watch-batch \
  --submission-path data/normalized/classification_batches/<run_id>_openai_batch_submission.json \
  --interval-seconds 300 \
  --max-checks 288
```

The current 3,149-document strict corpus is exhausted. Do not submit more of its
historical offsets. For a newly approved corpus, submit only one Batch sub-batch
at a time unless the maintainer confirms a higher provider-side enqueued-token
limit.

Maintainer-only bootstrap:

```bash
uv run marygenai initial-load setup-data
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

## Data And Provenance Principles

- Treat source records, publications, trial records, interaction documents, and
  PDFs as distinct document types.
- Separate raw payloads from normalized records.
- Deduplicate canonical corpus records by `document_id`.
- Preserve source URL/path, acquisition method, content hash, model, prompt,
  schema, evidence spans, confidence, warnings, and run identifiers.
- Keep trust levels explicit:
  `source_discovered`, `metadata_enriched`, `source_text_available`,
  `ai_classified_candidate`, and `human_reviewed`.
- Prefer structured parsers and schemas over ad hoc text manipulation.
- Let validated access patterns and retrieval needs drive storage choices.

## Human Review

Human review is required before candidate evidence becomes reviewed knowledge.
Any review workflow must preserve reviewer identity, reviewed field, original
value, reviewed value, timestamp, rationale, ontology version, extractor
version, and provenance.

Use `docs/review_status_guide.md` as the canonical workflow vocabulary. Keep
queue status, document review state, structured identity decisions, and
candidate-classification confidence separate.

## Safety Boundary

MaryGenAI catalogs and retrieves scientific evidence. It must not present
candidate classifications, retrieved studies, or generated summaries as medical
advice or treatment recommendations.
