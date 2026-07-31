# 2026-07-31 Remote MCP Pilot Handoff

## Purpose

This is the current continuation point for MaryGenAI MCP, source discovery,
enrichment, deployment, and physician-pilot work. Earlier Batch and identity
handoffs remain historical evidence, but they no longer describe the active
corpus or deployment milestone.

MaryGenAI exposes scientific source intelligence and AI-classified candidate
evidence. It does not provide reviewed clinical truth, medical advice, or
treatment recommendations.

## Current Snapshot

- Git branch: `main`, aligned with `origin/main` before this documentation
  handoff at commit `47ffdfa`.
- Branch policy: keep `main` as the only active local and remote branch unless
  the maintainer explicitly requests otherwise.
- Strict corpus: 3,149 classification-ready documents.
- Classification: 3,149/3,149 strict-valid candidate records with evidence
  spans across twenty-four runs, including targeted retries.
- Index: ignored DuckDB v2 at
  `data/normalized/retrieval_indexes/marygenai_candidate_retrieval_v1.duckdb`.
- Identity projection: PMID for 3,099 documents, PMCID for 2,415, DOI for 3,068,
  and 60 documents with explicit unresolved identifier conflicts.
- Trust boundary: every record is `ai_classified_candidate` with
  `review_state=needs_review`; none is reviewed knowledge.
- Protected state: SQLite, review queues, review decisions, and reviewed
  knowledge were not changed by index construction, deployment, or testing.

The strict corpus is exhausted. A provider-backed classification run is not a
routine continuation step. It requires explicit authorization and an
intentionally new or changed corpus.

## Implemented Retrieval And MCP Surface

The supported CLI provides:

```bash
uv run marygenai retrieval build-index
uv run marygenai retrieval inspect-index
uv run marygenai retrieval search --query "cannabidiol"
uv run marygenai mcp serve
uv run marygenai mcp serve-http
```

The MCP surface exposes four read-only tools:

- `search_studies` for lexical and structured candidate retrieval;
- `get_study` for complete identity, evidence, uncertainty, and provenance;
- `get_facets` for counts before pagination;
- `get_search_capabilities` for filters, limits, language, presentation, and
  trust contracts.

It also exposes the index manifest, capabilities, and study-detail resources.
The same query service backs the CLI, local stdio, local Streamable HTTP, and
remote AWS runtime. DuckDB is always opened with `read_only=True`.

## Remote Pilot

The current development environment is in AWS `us-east-2` and is operated with
`AWS_PROFILE=Pessoal`. Terraform under `infra/terraform/` manages:

- API Gateway HTTP API;
- Lambda Python 3.13;
- a private versioned S3 bucket with content-addressed DuckDB and manifest
  objects;
- least-privilege Lambda permissions and bounded CloudWatch log retention;
- the ACM certificate and API Gateway mapping for
  `mcp-server.marygenai.com`.

Cloudflare remains the external DNS provider. The application and ACM
validation CNAMEs are currently DNS-only. Terraform does not manage Cloudflare
or use CloudFormation.

The runtime verifies the DuckDB SHA-256, copies it to `/tmp`, and opens only the
selected immutable snapshot. It receives no SQLite database, review state,
provider credentials, provider tools, or data-write tool.

## Pilot Access

Bearer authentication is preferred. Because the maintainer's hosted Claude and
ChatGPT connector dialogs do not currently expose fixed request headers, the AWS
development environment also accepts exactly one query credential:

```text
https://mcp-server.marygenai.com/mcp?key=<pilot-token>
```

The token is shared pilot access, not OAuth and not per-physician identity. The
complete URL is a secret. Do not include it in screenshots, tickets, committed
files, or logs.

The ignored local token record is:

```text
data/private/mcp-dev-access-token.json
```

Print the connector URL only when necessary:

```bash
uv run python -c 'import json; from pathlib import Path; token=json.loads(Path("data/private/mcp-dev-access-token.json").read_text())["token"]; print(f"https://mcp-server.marygenai.com/mcp?key={token}")'
```

Hosted connector settings validated on 2026-07-31:

- Claude: use the complete URL and leave optional OAuth fields empty.
- ChatGPT: use the complete URL and select `No Auth`; MaryGenAI still validates
  the URL key.

Rotate the token after unintended exposure. Disable query authentication when
fixed request headers become available. OAuth or Cognito becomes necessary
before claiming individual physician identity, scopes, or independent
revocation.

## Host Language And Presentation Contract

The index metadata and candidate labels are primarily English. Claude,
ChatGPT, or another authorized host is responsible for translating Portuguese
or other non-English scientific concepts into concise English query terms and
structured filter values. MaryGenAI does not call a translation model or any
provider. The host must preserve DOI, PMID, PMCID, quoted evidence, and source
identity unchanged and may answer in the user's language.

Search responses carry a machine-readable presentation contract. The host must:

- call results AI-classified candidate matches, not validated relevant studies;
- interpret zero results only as no matches for the effective query in the
  current bounded index, not as absence from scientific literature;
- include `projected_identity.preferred_access_url` when citing a result;
- call `get_study` before making detailed evidence claims about a shortlist;
- distinguish direct matches from tangential or background candidates;
- never turn rank, confidence, or retrieved evidence into treatment advice.

## Completed Validation

Before this handoff:

- Ruff passed;
- 134 tests passed;
- Terraform validation and the deployed plan completed without drift after the
  presentation-contract release;
- custom-domain TLS, health, missing and invalid credential rejection, MCP
  initialization, tool discovery, Bearer access, and query-key access passed;
- hosted ChatGPT and Claude connectors both completed end-to-end retrieval.

Remote retrieval probes returned 29 candidates for Dravet syndrome plus
cannabidiol, 114 for epilepsy plus cannabidiol, and 33 for multiple sclerosis
plus tetrahydrocannabinol. These counts describe the closed candidate index and
do not measure the scientific literature as a whole.

## Live Acceptance Findings

The first ChatGPT conversation demonstrated Portuguese-to-English retrieval for
adolescent epilepsy. It preserved trust caveats but treated one tangential
pediatric cannabis review as relevant, omitted preferred access links, and made
detailed claims without opening study detail. These observations motivated the
machine-readable presentation contract.

The first Claude conversation demonstrated capability and facet inspection,
multiple translated hypothyroidism queries, and reasonable distinction between
thyroid-cancer background and hypothyroidism. Its first zero-result explanation
was broader than the bounded retrieval evidence justified. This motivated the
explicit zero-result contract.

An Alzheimer disease probe returned 77 candidates across the labels
`Alzheimer's Disease` and `Alzheimer Disease`. Inspection of five recent records
showed useful breadth across review, preclinical, and human observational
contexts, and exposed enrichment needs:

- PMID `38227160` is bibliographically a review, while its candidate study
  category is `meta_analysis` with a warning;
- PMID `37862567` has a 2023 online date and a 2024 journal-issue date, while v1
  exposes only one publication year;
- PMID `36655645` exposes DOI `10.7417/CT.2023.2497` in the current projection
  and publisher path, while PubMed reports `10.7417/CT.2023.5009`;
- direct and mechanistic background matches must be separated visibly.

These are candidate and bibliographic reconciliation findings, not reviewed
identity decisions. They were found through read-only retrieval and external
source inspection. No provider was called and no protected state was changed.

## Physician Demonstration Checklist

Use a fresh host conversation or reconnect the connector if its cached tool
descriptions predate the latest deployment. Do not enter a patient name, exact
birth date, record number, contact information, or other identifying data.
Describe only the non-identifying scientific dimensions needed for retrieval.

Prepare a small mix of questions rather than an open-ended product tour:

1. pediatric neurology: cannabidiol, Dravet syndrome, efficacy, and safety;
2. neurology: human cannabinoid evidence for multiple sclerosis;
3. neurology or geriatrics: recent direct and background candidates for
   Alzheimer disease;
4. endocrinology: hypothyroidism as an expected sparse or zero-result probe;
5. pain medicine: recent human trials for chronic or neuropathic pain.

For each question, record only non-identifying evaluation data:

- specialty and scientific question;
- whether the host translated and decomposed it appropriately;
- tool sequence and effective query;
- whether direct results appeared before tangential ones;
- whether study detail and the original source were opened;
- useful results, false positives, suspected false exclusions, and missing
  filters;
- whether trust, uncertainty, and zero-result language were understandable.

Do not infer treatment applicability during the demonstration. The useful
outcome is whether the physician can find and inspect plausible reference
documents efficiently.

## Known Limits

- Search is conservative local lexical matching, not semantic retrieval.
- Condition and cannabinoid aliases are not yet a versioned ontology service.
- Rank and retrieval confidence are not clinical evidence strength or calibrated
  probabilities.
- V3 does not reliably structure dose, route, formulation, comparator, duration,
  detailed age group, sample size, geography, outcome entity, or adverse-event
  entity.
- The index does not distinguish online-first, issue, indexing, and print dates.
- Candidate study design and bibliographic publication type can disagree.
- Sixty documents expose unresolved projected-identity conflicts, and later
  external metadata may reveal additional disagreement.
- The closed runtime performs no live source lookup, URL-health check, related
  study lookup, citation traversal, or full-text delivery.
- One shared query-key URL can be copied and does not identify or revoke users
  independently.
- There is no automatic continuous-discovery or remote snapshot-promotion job.

## Next Workstreams

Use physician feedback to order these workstreams.

1. Acceptance benchmark: turn realistic questions into repeatable cases with
   expected dimensions, source-opening checks, useful-result labels, and false
   exclusion analysis.
2. MCP retrieval: add explicit sort policy, required/preferred/excluded
   dimensions, stronger query diagnostics, directness signals, and study
   comparison only where acceptance evidence supports them.
3. Continuous discovery: run bounded PubMed windows, deduplicate canonical
   identity, acquire lawful source text, classify only new eligible records,
   rebuild an immutable index, validate it, and promote it deliberately.
4. Enrichment: reconcile bibliographic publication dates and types, preserve
   external identifier conflicts, validate physician-facing URLs, improve
   aliases, and add the highest-value missing clinical fields with evidence.
5. Operations and access: add safe aggregate observability and token rotation;
   adopt OAuth or Cognito only when individual user identity or revocation is
   required.

## Safe Continuation

Start by reading:

- `AGENTS.md`;
- `README.md`;
- `docs/product_value.md`;
- `docs/mvp_plan.md`;
- `docs/roadmap.md`;
- `docs/official_workflows.md`;
- `docs/mcp_retrieval_contract.md`;
- `docs/mcp_clinical_retrieval_research.md`;
- this handoff.

Useful read-only checks are:

```bash
git status --short --branch
git branch --all
uv run marygenai retrieval inspect-index
AWS_PROFILE=Pessoal aws sts get-caller-identity
curl https://mcp-server.marygenai.com/health
cd infra/terraform
AWS_PROFILE=Pessoal terraform plan
```

The health endpoint is intentionally unauthenticated and contains no corpus
data. Do not place the token on a command line except when explicitly testing
authenticated access, because URLs and commands may be retained in shell or
platform history.

Before committing implementation changes, run:

```bash
uv run ruff check .
uv run pytest
```

Commit and push only intentional files to `origin/main`. Keep generated data,
Terraform state and plans, deployment ZIPs, local tokens, and secrets ignored.
