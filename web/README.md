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

The deployed Cloudflare Worker serves the public site as Static Assets. The
same Worker can also execute the vinext server routes that proxy
`/api/viewer/*` to AWS. The real Python/DuckDB Viewer API remains in an
environment with access to the approved immutable index. The deployment reuses
the existing AWS API Gateway/Lambda/S3 retrieval pattern and configures
`MARYGENAI_VIEWER_API_BASE_URL` and the secret
`MARYGENAI_VIEWER_API_BEARER_TOKEN` in the proxy runtime. The token is
server-side only and must never use a `NEXT_PUBLIC_` prefix. Proxy and upstream
responses use `Cache-Control: private, no-store`.

Local Cloudflare automation uses the ignored `.env.cloudflare.local` file and
the ignored Viewer token under `data/private/`. Validate the generated Worker
package without uploading it:

```bash
npm run cloudflare:preview:dry-run
```

Exercise the built proxy against the authenticated AWS Viewer API without
starting a public server:

```bash
npm run cloudflare:proxy:smoke
```

After confirming that Worker preview URLs are access-protected, upload a new
version without changing production traffic:

```bash
npm run cloudflare:preview:upload
```

## Validation

```bash
npm run lint
npm test
npm run build
```

The `.openai/hosting.json` file contains no project identifier or persistence
binding for deployment through OpenAI Sites. The Cloudflare deployment does not
itself authorize candidate-index exposure.
