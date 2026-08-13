# MaryGenAI

MaryGenAI is a public research and engineering project for scientific source
intelligence and candidate classification in cannabinoid medicine.

It helps physicians, researchers, and evidence professionals discover, filter,
inspect, and verify scientific documents. Its first external integration is a
read-only Model Context Protocol (MCP) pilot that exposes candidate studies to
compatible AI assistants and research tools.

MaryGenAI does **not** provide medical advice, treatment recommendations, or
reviewed clinical truth. AI classifications are probabilistic retrieval
metadata and always require inspection of the supporting evidence and original
publication.

## What The Project Does

MaryGenAI:

- discovers scientific publications through explicit, auditable source routes;
- resolves document identity and preserves identifier conflicts;
- evaluates whether acquired source text is usable for classification;
- builds deduplicated classification corpora;
- produces evidence-backed candidate labels for retrieval;
- preserves source hashes, evidence spans, model and prompt versions,
  uncertainty, and provenance;
- exposes candidate records through an isolated read-only retrieval index and
  MCP interface;
- keeps candidate evidence separate from human-reviewed knowledge.

Current confidence values are categorical model assessments, not calibrated
probabilities. Retrieval rank and confidence also do not measure clinical
evidence strength.

See [Product Value](docs/product_value.md) for the complete product and quality
boundary.

## Current Status

The implemented pilot includes:

- 3,149 strict-valid candidate-classification records in maintainer-local,
  ignored artifacts;
- an isolated DuckDB retrieval index over the strict corpus and the qualified
  PubMed candidate extension;
- read-only search, study detail, facets, and capability discovery;
- local CLI, MCP stdio, and stateless Streamable HTTP interfaces;
- a read-only Dataset Viewer API over the same retrieval service;
- a responsive public website and Dataset Viewer frontend with a clearly
  labeled synthetic demonstration fallback;
- a production Cloudflare same-origin Viewer proxy backed by the private AWS
  development gateway and immutable candidate snapshot;
- explicit candidate-result, zero-result, source-link, and study-detail
  presentation rules.

The active private AWS snapshot contains 3,437 records: the 3,149-record strict
corpus plus 288 qualified PubMed candidates. Every record remains
`ai_classified_candidate` with `review_state=needs_review`. The generated corpus
and index are not committed public datasets. The authenticated Viewer API is
deployed, and the production Cloudflare Worker proxies bounded read-only
requests to it without exposing the Viewer credential or distributing the
DuckDB artifact. Near-term work is production monitoring, documentation and
repository review, controlled PubMed candidate growth, and a complete
curation-readiness package. External curator availability does not block
candidate-data work, and no candidate becomes reviewed knowledge without an
explicit review workflow.

See [Current Status](docs/current_status.md) for the verified snapshot, known
limitations, and next workstreams.

## Quick Start

Requirements:

- Python 3.13 or newer;
- [`uv`](https://docs.astral.sh/uv/).

Install development dependencies and inspect the CLI:

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai --help
```

Initialize local operational storage and discover a bounded PubMed window:

```bash
uv run marygenai db init
uv run marygenai pubmed-discovery run \
  --datetype pdat \
  --mindate 2024/01/01 \
  --maxdate 2024/01/31 \
  --retmax 100
```

Generated data, source payloads, PDFs, private inputs, credentials, review
state, and deployment artifacts remain in ignored local paths.

## Read-Only Retrieval And MCP

The retrieval commands operate on an ignored local index built from candidate
artifacts:

```bash
uv run marygenai retrieval build-index
uv run marygenai retrieval inspect-index
uv run marygenai retrieval search \
  --condition "Dravet syndrome" \
  --cannabinoid Cannabidiol \
  --population pediatric_humans
uv run marygenai mcp serve
```

The runtime opens DuckDB with `read_only=True`. It does not receive SQLite
review state, provider credentials, provider tools, or data-write tools.

The index is generated from maintainer-local candidate artifacts and is not
included in a fresh clone. Public contributors can run source discovery and
corpus preparation, but cannot reproduce the complete pilot index until a
licensed public snapshot is released.

See the [Read-Only MCP Retrieval Contract](docs/mcp_retrieval_contract.md) and
[Official Workflows](docs/official_workflows.md).

## Website And Dataset Viewer

The frontend requires Node.js 22.13 or newer. A fresh clone starts with public,
synthetic records because the complete candidate index is an ignored local
artifact:

```bash
cd web
npm install
npm run dev
```

To connect the Viewer to a local immutable index, start the read-only API and
configure the frontend proxy in a second terminal:

```bash
uv run marygenai viewer serve-api
cd web
MARYGENAI_VIEWER_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The Viewer API reuses `RetrievalService`, opens DuckDB in read-only mode, and
does not receive SQLite, review queues, provider credentials, or write tools.

## Candidate Classification

Local packet generation and deterministic smoke validation do not call a model:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
uv run marygenai classification build-prompt-packets --limit 5
uv run marygenai classification run-smoke --limit 5
```

Provider-backed synchronous and Batch commands are explicit operations. They
require credentials, can incur cost, and write ignored candidate-evidence
artifacts. The completed historical strict corpus is exhausted; new paid
classification should target only an explicitly approved new or changed corpus.

Detailed provider, evaluation, and review commands are documented in
[Official Workflows](docs/official_workflows.md).

## Data, Privacy, And Safety

- Do not put patient-identifying information in queries, logs, evaluation
  artifacts, or demonstration notes.
- Do not commit `.env`, credentials, raw downloads, PDFs, generated corpora,
  local databases, Terraform state, or private legacy exports.
- Do not treat discovery, download, classification, retrieval rank, or queue
  completion as human review.
- Preserve original sources, hashes, evidence spans, uncertainty, and trust
  levels.
- Use only lawful, source-declared acquisition routes.

The private maintainer bootstrap under `temp/legacy/` is not distributed and is
not required for the public source-discovery path.

## Repository Structure

```text
src/marygenai/        # supported package and CLI workflows
tests/                # tests for the supported package surface
docs/                 # public product, architecture, workflow, and history docs
ontology/             # ontology contracts and future versioned artifacts
scripts/              # thin orchestration around supported CLI commands
infra/                # reproducible read-only MCP deployment configuration
web/                  # public website and read-only Dataset Viewer frontend
data/                 # generated datasets and source artifacts, ignored
temp/                 # private inputs, archived experiments, scratch, ignored
build/                # generated deployment packages, ignored
```

## Documentation

Start with the [Documentation Index](docs/README.md). The primary public
documents are:

- [Current Status](docs/current_status.md)
- [Product Value](docs/product_value.md)
- [Project Brief](docs/project_brief.md)
- [Architecture](docs/architecture.md)
- [Official Workflows](docs/official_workflows.md)
- [MVP Plan](docs/mvp_plan.md)
- [Roadmap](docs/roadmap.md)
- [Decision Log](docs/decisions.md)
- [Experimental Findings](docs/experimental_findings.md)

## Development

```bash
uv run ruff check .
uv run pytest
```

All code, schemas, filenames, documentation, and CLI output are maintained in
English. See [AGENTS.md](AGENTS.md) for repository-specific engineering and
safety rules.

## License

No software or data license has been published yet. Public visibility of this
repository does not grant permission to copy, modify, or redistribute its
contents. Select and add an explicit license before describing MaryGenAI as
open-source or inviting external reuse.
