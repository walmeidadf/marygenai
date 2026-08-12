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

With a real index, preferred PubMed, PMC, or DOI links appear in the results
and study detail and open in a new browser tab. Synthetic records do not expose
source links because they are fictional.

Cloudflare Pages can host the site and synthetic Viewer even as a static build;
the browser falls back to the labeled fictional fixtures if the same-origin API
routes are absent. A compatible Pages Functions or Worker deployment can host
the proxy. The real Python/DuckDB Viewer API must run in an environment with
access to the approved immutable index. The preferred first deployment reuses
the existing AWS API Gateway/Lambda/S3 retrieval pattern and configures
`MARYGENAI_VIEWER_API_BASE_URL` and the secret
`MARYGENAI_VIEWER_API_BEARER_TOKEN` in the proxy runtime. The token is
server-side only and must never use a `NEXT_PUBLIC_` prefix. Proxy and upstream
responses use `Cache-Control: private, no-store`.

## Validation

```bash
npm run lint
npm test
npm run build
```

The `.openai/hosting.json` file contains no project identifier or persistence
binding for deployment through OpenAI Sites. The maintainer's separate
Cloudflare Pages deployment does not itself authorize candidate-index exposure.
