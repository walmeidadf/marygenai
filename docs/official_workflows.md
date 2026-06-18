# Official Workflows

The supported public interface is the `marygenai` package CLI. Commands in
historical experiments are not public APIs.

## Setup

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai --help
```

Configuration belongs in an ignored `.env` file. Never commit credentials,
generated data, raw source payloads, PDFs, or private legacy exports.

## Public Source Workflow

Initialize local operational storage:

```bash
uv run marygenai db init
```

Discover PubMed candidates for an explicit window:

```bash
uv run marygenai pubmed-discovery run \
  --datetype pdat \
  --mindate 2024/01/01 \
  --maxdate 2024/01/31 \
  --retmax 100
```

Run month-by-month discovery:

```bash
uv run python scripts/pubmed_monthly_backfill.py \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --retmax 200
```

Enrich prioritized candidates and audit locally persisted artifacts:

```bash
uv run marygenai access-enrichment run --limit 50
uv run marygenai access-enrichment audit-artifacts
```

The enrichment command may write artifacts and operational candidate state as
documented by the command. Classification and corpus commands must not mutate
SQLite or review state.

## Classification Workflow

Build a deduplicated corpus and stratified sample:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
```

Inspect prompt packets without calling a model:

```bash
uv run marygenai classification build-prompt-packets \
  --limit 5 \
  --max-source-chars 6000 \
  --target-model-provider openai \
  --target-model-name gpt-5.4-mini
```

Validate the schema with deterministic mock output:

```bash
uv run marygenai classification run-smoke --limit 5
```

Run a bounded provider-backed validation:

```bash
uv run marygenai classification run-smoke \
  --limit 5 \
  --input-path <classification_sample_records.jsonl> \
  --no-dry-run \
  --provider openai \
  --model gpt-5.4-mini \
  --max-source-chars 6000 \
  --max-completion-tokens 3000
```

Provider-backed output is candidate evidence. It is written under ignored
`data/normalized/classification_runs/` and does not become reviewed knowledge.

## Maintainer Bootstrap

These commands require private legacy inputs under `temp/legacy/`:

```bash
uv run marygenai initial-load setup-data
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

Public contributors should use public source discovery until reviewed public
snapshots become available.

## Review Workflow

Review commands intentionally operate on SQLite workflow state:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review show <review_item_id_or_document_id>
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

See [Review Status Guide](review_status_guide.md) before changing queue or
decision state.

## Validation

```bash
uv run ruff check .
uv run pytest
```
