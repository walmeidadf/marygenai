# MaryGenAI

MaryGenAI is an open-source scientific source-intelligence and
candidate-classification engine for cannabinoid medicine.

Its purpose is to make scientific literature easier to discover, filter, inspect,
and verify. The intended downstream experience is a physician or researcher using
their preferred AI assistant to find relevant studies through a future read-only
MCP interface, then opening the underlying publications for deeper assessment.

MaryGenAI does not provide medical advice and does not turn model output into
clinical truth.

## Product Contract

The engine:

- discovers and resolves scientific-document identity;
- enriches metadata and lawful source-access paths;
- prepares deduplicated, classification-ready corpora;
- classifies retrieval dimensions such as study type, condition, cannabinoid,
  population, evidence context, outcome domain, and overall direction;
- preserves source snippets, model and prompt versions, uncertainty, and
  provenance;
- keeps AI classifications clearly separated from human-reviewed knowledge.

Candidate classifications are useful even when uncertainty remains. A study can
still be found through a broad filter, ranked below a higher-confidence match,
and inspected through its supporting evidence. Known schema, prompt, source, or
pipeline defects are not acceptable uncertainty and should be corrected.

Current confidence values are categorical model assessments, not calibrated
probabilities. A future retrieval confidence score should combine source quality,
evidence support, deterministic metadata agreement, pipeline validation, and
calibration against trusted references.

See [Product Value](docs/product_value.md) for the complete product and quality
boundary.

## Official Workflows

The supported public interface is the `marygenai` package CLI:

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai --help
```

Current handoff state:

- a first 500-document strict classification-ready Batch tranche is complete;
- the tranche produced 500/500 strict-valid candidate records after
  deterministic provenance-recorded technical repairs;
- measured Batch cost was about USD 2.52, or about USD 0.00504 per document;
- the recommended next product step is a read-only retrieval/MCP demo over
  those 500 candidate records while optional remaining-corpus Batch work
  continues in sequential chunks.

See [2026-07-11 Batch And MCP Handoff](docs/2026-07-11_batch_and_mcp_handoff.md)
for run IDs, costs, artifact paths, continuation prompts, and Batch operating
rules.

Core source-intelligence flow:

```bash
uv run marygenai db init
uv run marygenai pubmed-discovery run \
  --datetype pdat \
  --mindate 2024/01/01 \
  --maxdate 2024/01/31 \
  --retmax 100
uv run marygenai access-enrichment run --limit 50
uv run marygenai access-enrichment audit-artifacts
```

Classification preparation, validation, and the first candidate-base canary:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
uv run marygenai classification build-prompt-packets --limit 5
uv run marygenai classification run-smoke --limit 5
uv run marygenai classification run-smoke \
  --limit 50 \
  --input-path <classification_corpus_records.jsonl> \
  --dataset-split strict_classification_ready \
  --no-dry-run \
  --provider openai \
  --model gpt-5.4-mini
uv run marygenai classification prepare-batch \
  --limit 150 \
  --offset 0 \
  --input-path <classification_corpus_records.jsonl> \
  --dataset-split strict_classification_ready \
  --model gpt-5.4-mini
uv run marygenai classification submit-batch \
  --batch-input-path <openai_batch_input.jsonl> \
  --manifest-path <openai_batch_manifest.jsonl>
uv run marygenai classification watch-batch \
  --submission-path <openai_batch_submission.json> \
  --interval-seconds 300 \
  --max-checks 288
uv run marygenai classification retrieve-batch \
  --submission-path <openai_batch_submission.json>
uv run marygenai classification profile-retrieval-fields --sample-size 12
uv run marygenai classification extract-retrieval-metadata \
  --input-path <retrieval_field_validation_sample.jsonl>
uv run marygenai classification build-v4-comparison-packets \
  --sample-path <retrieval_field_validation_sample.jsonl> \
  --parser-records-path <retrieval_metadata_parser_records.jsonl> \
  --limit 8
uv run marygenai classification build-validation-benchmark --sample-size 48
uv run marygenai classification build-validation-holdout \
  --exclude-decisions-path <reviewed_benchmark_decisions.jsonl>
uv run marygenai classification evaluate-validation-benchmark \
  --candidates-path <benchmark_candidates.jsonl> \
  --decisions-path <reviewed_benchmark_decisions.jsonl>
uv run marygenai classification apply-study-design-rules \
  --input-path <benchmark_or_holdout_candidates.jsonl>
uv run marygenai classification evaluate
```

`classification run-smoke` defaults to deterministic mock output. A provider call
requires `--no-dry-run`, a configured `OPENAI_API_KEY`, and an explicit model.
All outputs remain candidate evidence.

The first product-oriented broad/v3 Batch tranche is complete with 500 strict
classification-ready documents. Use it as the first MCP-demo candidate base.
Further classification should use sequential Batch chunks sized by estimated
enqueued tokens, normally 150 records for the current prompt shape.

`classification evaluate` is local-only. It separates technical validity,
retrieval utility, and inference quality, compares against normalized English
legacy context when available, and writes ignored reports plus a targeted rerun
input under `data/normalized/classification_evaluations/`.

`classification build-validation-benchmark` creates a deterministic,
title-explicit, stratified candidate set for human review. It does not call an
LLM, mutate SQLite, or create reviewed knowledge.

`classification profile-retrieval-fields` measures the actual downloaded corpus
and prepares a small cross-domain validation worklist. Legacy English context is
reported as a guardrail, not treated as the classification queue.

`classification extract-retrieval-metadata` tests deterministic source parsing
on that worklist. Its outputs are field candidates with evidence and provenance,
not final classifications.

`classification build-v4-comparison-packets` creates versioned broad-v4 and
selective field-family prompt packets, field-level routing records, strict local
mock responses, assembled mock candidates, token estimates, and configurable
cost projections. It also writes a frozen comparison manifest that can be
reused with `--manifest-path`. It never calls a provider.

Selective-v4 work is documented as a future optimization path, not a blocker for
the first candidate-classified base or read-only MCP demonstration.

`classification prepare-batch` writes OpenAI Batch-compatible JSONL plus a local
manifest for later submission. Use `--offset` with `--limit` to prepare
non-overlapping corpus chunks after the dataset split filter is applied. It has
a local estimated enqueued-token guard so oversized batches fail before upload.
It does not upload files, create a remote batch, call a provider, mutate
SQLite, or create reviewed knowledge.

`classification submit-batch`, `classification retrieve-batch`, and
`classification watch-batch` are explicit provider-backed operations.
`watch-batch` polls status, downloads the output as soon as the remote Batch
completes, and writes a local watch log. They write ignored local audit
artifacts and convert completed Batch outputs into the same
candidate-classification run format used by synchronous validation. Outputs
remain candidate evidence.

The benchmark evaluator measures deterministic candidates against append-only,
human-confirmed review decisions. The holdout builder freezes a separate
40-document set before rule changes so development cases cannot leak into final
validation.

`apply-study-design-rules` applies versioned deterministic source-text
refinements without calling an LLM. Its output preserves candidate IDs, source
hashes, the original labels, applied rules, and run provenance.

Maintainer-only private bootstrap:

```bash
uv run marygenai initial-load setup-data
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

The initial load expects private files under `temp/legacy/`. Public contributors
should not expect those files to exist.

Review commands operate on local SQLite workflow state:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

## Repository Structure

```text
src/marygenai/        # supported package and CLI workflows
tests/                # tests for the supported package surface
docs/                 # current product, architecture, operations, and decisions
ontology/             # public ontology contracts and future versioned artifacts
scripts/              # thin runners around supported package commands
data/                 # generated datasets and source artifacts, ignored
temp/                 # private inputs, archived experiments, and scratch, ignored
```

Historical POC implementations are intentionally not part of the supported public
surface. Their durable findings are summarized in
[Experimental Findings](docs/experimental_findings.md), and their implementation
history remains available through Git.

## Documentation

- [Product Value](docs/product_value.md)
- [Project Brief](docs/project_brief.md)
- [Official Workflows](docs/official_workflows.md)
- [2026-07-11 Batch And MCP Handoff](docs/2026-07-11_batch_and_mcp_handoff.md)
- [Architecture](docs/architecture.md)
- [Classification Architecture](docs/classification_architecture.md)
- [Classification Contract](docs/classification_dataset_plan.md)
- [Classification Data Dictionary](docs/classification_data_dictionary.md)
- [Candidate Classification V4 Plan](docs/classification_v4_plan.md)
- [MVP Plan](docs/mvp_plan.md)
- [Roadmap](docs/roadmap.md)
- [Data Sources](docs/data_sources.md)
- [Source Availability](docs/source_availability_assessment.md)
- [Experimental Findings](docs/experimental_findings.md)
- [Decision Log](docs/decisions.md)

## Development

```bash
uv run ruff check .
uv run pytest
```
