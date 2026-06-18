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

Classification preparation and validation:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
uv run marygenai classification build-prompt-packets --limit 5
uv run marygenai classification run-smoke --limit 5
uv run marygenai classification evaluate
```

`classification run-smoke` defaults to deterministic mock output. A provider call
requires `--no-dry-run`, a configured `OPENAI_API_KEY`, and an explicit model.
All outputs remain candidate evidence.

`classification evaluate` is local-only. It separates technical validity,
retrieval utility, and inference quality, compares against normalized English
legacy context when available, and writes ignored reports plus a targeted rerun
input under `data/normalized/classification_evaluations/`.

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
- [Architecture](docs/architecture.md)
- [Classification Contract](docs/classification_dataset_plan.md)
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
