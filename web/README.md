# MaryGenAI Web

This vinext application contains the public project website and read-only
Dataset Viewer.

## Requirements

- Node.js 22.13 or newer;
- npm;
- optionally, the MaryGenAI Python environment and an immutable retrieval index.

## Synthetic Demonstration

A fresh clone runs with fictional fixtures. The interface labels its snapshot,
banner, evidence, warnings, and provenance as a synthetic demonstration. These
records are not scientific publications and are not copied from private or
ignored project data.

```bash
npm install
npm run dev
```

Open `http://localhost:3000/` for the website and
`http://localhost:3000/dataset` for the Viewer.

## Local Candidate Index

Start the Python API from the repository root:

```bash
uv run marygenai viewer serve-api
```

Then configure the same-origin proxy when starting this application:

```bash
MARYGENAI_VIEWER_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The Python API reuses `RetrievalService` and opens DuckDB with
`read_only=True`. It does not receive SQLite, review workflow state, provider
credentials, or write tools.

## Validation

```bash
npm run lint
npm test
npm run build
```

The `.openai/hosting.json` file contains no site identifier or persistence
binding. A successful local build does not publish the website or authorize
candidate-index exposure.
