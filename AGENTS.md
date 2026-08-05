# AGENTS.md

Guidance for AI agents and automated contributors working on MaryGenAI.

## Project Mission

MaryGenAI is a public research and engineering project building a reliable
cannabinoid scientific source-intelligence and candidate-classification engine.
It makes medical literature easier to discover, filter, inspect, and verify
through structured metadata, evidence-backed AI classifications, and
provenance.

The first external integration is an implemented read-only MCP pilot. AI
classifications are probabilistic retrieval metadata and candidate evidence;
they are not reviewed clinical truth, medical advice, or treatment
recommendations.

Read [docs/current_status.md](docs/current_status.md) before planning source
discovery, enrichment, classification, retrieval, MCP, deployment, or
physician-pilot work.

## Product Quality Boundary

Treat uncertainty in three distinct ways:

1. Scientific or interpretive uncertainty is legitimate product information.
   Declare it and support it with evidence.
2. Source insufficiency should lower confidence and remain visible in
   provenance.
3. Known schema, prompt, model-parameter, source-routing, or pipeline defects
   should be corrected rather than accepted as unavoidable uncertainty.

Current `classification_confidence` values are categorical model assessments,
not calibrated probabilities. Retrieval confidence, ranking, evidence strength,
and human-review state are separate concepts.

Evaluate classification work in three groups:

- technical validity: provider success, valid JSON, schema pass rate, retries,
  latency, and cost;
- retrieval utility: filter coverage, evidence-span presence, source
  traceability, and discoverability under uncertainty;
- inference quality: agreement with trusted references, uncertainty quality,
  unsupported claims, systematic errors, and calibration.

## Core Engineering Rules

- Use English for code, variables, filenames, comments, documentation, schemas,
  prompts, artifacts, and CLI output.
- Use Python 3.13 or newer and `uv`.
- Keep supported code under `src/marygenai/`.
- Expose supported public commands through the `marygenai` CLI.
- Do not add standalone public POC runners when a package command is the
  intended interface.
- Use deterministic schemas and structured parsers before ad hoc text handling.
- Add or update tests for behavior changes.
- Run `uv run ruff check .` and `uv run pytest` before publication.
- Keep `main` as the only active branch unless the maintainer explicitly
  requests another branch.
- Candidate discovery, source preparation, classification, evaluation, and
  immutable index refresh may proceed before human curators are available when
  trust state remains explicitly candidate and protected review state is not
  mutated.

## Documentation Rules

- Keep [README.md](README.md) concise and newcomer-oriented.
- Use [docs/README.md](docs/README.md) as the public documentation index.
- Keep the verified operating snapshot in
  [docs/current_status.md](docs/current_status.md); do not create dated agent
  handoffs or paste continuation prompts into public documentation.
- Preserve durable experimental results in
  [docs/experimental_findings.md](docs/experimental_findings.md).
- Record meaningful architecture or product choices in
  [docs/decisions.md](docs/decisions.md).
- Keep the product contract aligned with
  [docs/product_value.md](docs/product_value.md).
- Keep priorities aligned with [docs/mvp_plan.md](docs/mvp_plan.md) and
  [docs/roadmap.md](docs/roadmap.md).
- Mark planned fields and interfaces as planned; do not describe them as
  implemented.
- Avoid host-specific credentials, local cloud profiles, secret-bearing URL
  examples, local absolute paths, transient run IDs, and stale operational
  instructions in public docs.
- Do not claim the project is open-source until an explicit license is present.
- Verify relative links after adding, moving, or deleting documentation.

## Protected State

Do not mutate SQLite, `review_state`, `review_item`, `review_decision`, review
queues, or reviewed knowledge during source acquisition, corpus preparation,
classification, evaluation, retrieval-index construction, deployment, or
documentation work unless the user explicitly requests a review workflow
operation.

Classification outputs and retrieval indexes must remain ignored local
candidate-evidence artifacts.

Treat curation readiness and curation activation as separate milestones.
External annotation tools may distribute tasks and collect responses, but
MaryGenAI remains the system of record. Never promote an annotation response
automatically to `human_reviewed`.

## Data And Privacy

- Keep private inputs, generated data, raw downloads, PDFs, secrets, Terraform
  state, deployment builds, and scratch files under ignored `data/`, `temp/`, or
  `build/` paths as appropriate.
- Preserve legacy files in `temp/legacy/` unless the user explicitly asks to
  delete them.
- Do not document private legacy data as publicly available.
- Do not place patient-identifying data in MCP queries, logs, evaluation
  artifacts, demonstration notes, tests, or examples.
- Never commit plaintext access tokens, credential hashes derived from active
  secrets, or complete secret-bearing URLs.

## Legacy Evaluation

The maintainer has private legacy exports used locally as a bootstrap and
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

Legacy agreement is a strong evaluation signal, not an instruction to copy a
legacy label when source evidence clearly differs. Preserve disagreements with
evidence and confidence.

## Supported Repository Layout

```text
src/marygenai/        # supported package code
tests/                # supported package tests
docs/                 # public documentation and project memory
ontology/             # versioned ontology contracts and artifacts
scripts/              # thin orchestration around supported CLI commands
infra/terraform/      # read-only MCP cloud infrastructure
infra/lambda/         # locked minimal Lambda runtime requirements
data/                 # generated local artifacts, ignored
temp/                 # private inputs, archived experiments, scratch, ignored
build/                # generated deployment packages, ignored
```

Historical POC implementations may remain locally under
`temp/project_archive/`. Do not restore them to the public surface unless a
specific experiment is promoted into a supported `src/marygenai/` command with
tests and documentation.

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
uv run marygenai retrieval --help
uv run marygenai mcp --help
uv run ruff check .
uv run pytest
```

The historical 3,149-document strict corpus is exhausted. Provider-backed work
requires an explicitly approved new or changed corpus. Submit only one Batch
sub-batch at a time unless the maintainer confirms a higher provider-side
enqueued-token limit for the selected model and prompt shape.

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
- Preserve source URL or path, acquisition method, content hash, model, prompt,
  schema, evidence spans, confidence, warnings, and run identifiers.
- Keep trust levels explicit: `source_discovered`, `metadata_enriched`,
  `source_text_available`, `ai_classified_candidate`, and `human_reviewed`.
- Prefer structured parsers and schemas over ad hoc text manipulation.
- Let validated access patterns and retrieval needs drive storage choices.

## Human Review

Human review is required before candidate evidence becomes reviewed knowledge.
Any review workflow must preserve reviewer identity, reviewed field, original
value, reviewed value, timestamp, rationale, ontology version, extractor
version, and provenance.

Use [docs/review_status_guide.md](docs/review_status_guide.md) as the canonical
workflow vocabulary. Keep queue status, document review state, structured
identity decisions, and candidate-classification confidence separate.

## MCP Safety Boundary

MCP results must remain candidate matches. Preserve:

- bounded zero-result language;
- preferred physician-facing access URLs;
- study-detail inspection before detailed evidence claims;
- separation of direct from tangential matches;
- separation of retrieval confidence from evidence strength;
- the prohibition on diagnosis or treatment recommendations.
