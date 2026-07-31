# 2026-07-17 Identity And MCP Handoff

> Historical identity handoff. Use
> [2026-07-31 Remote MCP Pilot Handoff](2026-07-31_mcp_pilot_handoff.md) for the
> current corpus, deployment, demonstration, and continuation state.

## 2026-07-20 Implementation Update

The proposed read-only identity projection is implemented in retrieval index
schema v2. The original 1,100-record audit reproduced exactly after structured
source parsing: PMID 1,087, PMCID 990, DOI 1,071, with 958 documents carrying
all three identifiers, 132 carrying two, 10 carrying one, and no conflicts.

Four later 150-record chunks through offset 1,550 completed and were retrieved.
The offset-1,400 chunk required a 33-request targeted retry after provider HTTP
500 errors. Five additional chunks at offsets 1,700 through 2,300 also completed
and were validated locally. The rebuilt ignored index now contains 2,450
candidates with projected coverage PMID 2,437, PMCID 1,980, and DOI 2,412. It exposes
original corpus identity separately from projected identity, identifier-level
provenance, conflicts, labeled identity URLs, and a deterministic preferred
physician-facing link. SQLite and review state remain untouched.

Five final chunks at offsets 2,450 through 3,050 exhausted the 3,149-document
strict corpus. The ignored index now contains 3,148 strict-valid candidates
across 23 classification runs; one response at offset 2,750 ended at the
completion-token limit with truncated JSON and was not repaired locally.
Projected coverage is PMID 3,098, PMCID 2,414, and DOI 3,067.

The final offset also exposed a source-identity quality boundary: 59 of its 99
documents have projected identifier conflicts, bringing the index to 60
conflict documents and 97 identifier conflicts. These conflicts remain visible
and unresolved. They are not safe normalization repairs and require
source-routing or identity review before physician-facing use.

An explicitly authorized targeted Batch later recovered the single truncated
record with strict schema validity and four exactly grounded evidence spans. The
ignored index now contains all 3,149 strict candidates across 24 runs, with
projected coverage PMID 3,099, PMCID 2,415, and DOI 3,068. The conflict counts
remain unchanged.

## Session Outcome

MaryGenAI's ignored read-only DuckDB index contains 1,100 unique
AI-classified candidate documents from eight completed Batch runs. A local,
read-only identity audit found that the index exposes only the sparse identity
copied from the classification corpus even though richer bibliographic
identifiers already exist in retrieved article metadata and cached enrichment
artifacts.

No provider or network call was made. SQLite, review queues, review decisions,
candidate records, and reviewed knowledge were not mutated.

## Indexed Runs

- `20260710T173226Z`: 150 records
- `20260710T180539Z`: 150 records
- `20260710T211154Z`: 150 records
- `20260711T153044Z`: 50 records
- `20260716T191943Z`: 150 records
- `20260717T111520Z`: 150 records
- `20260717T113729Z`: 150 records
- `20260717T120705Z`: 150 records

The default index is:

`data/normalized/retrieval_indexes/marygenai_candidate_retrieval_v1.duckdb`

The generated index and all source artifacts under `data/` remain ignored
candidate-evidence artifacts.

## Identity Audit

| Identifier | Structured in corpus/index | Recoverable locally | Additional local values |
|---|---:|---:|---:|
| PMID | 0 | 1,087 | 1,087 |
| PMCID | 722 | 990 | 268 |
| DOI | 378 | 1,071 | 693 |

Local identity combinations after deterministic normalization:

- 958 documents have PMID, PMCID, and DOI;
- 132 documents have two of the three identifiers;
- 10 documents have one identifier;
- no identifier conflicts were found.

The additional values were recovered from:

- primary-article metadata in locally persisted PMC HTML and NXML;
- PMCID-bearing source and routing URLs;
- cached Europe PMC metadata;
- cached OpenAlex metadata.

SQLite `document`, SQLite `document_identity`, the classification corpus, and
the DuckDB index contain the same sparse structured identity. Richer values are
present in ignored local artifacts but have not been projected into the
retrieval identity.

## Why Structured PMID Coverage Is Zero

The Batch preparation path iterates the classification corpus in file order and
applies `--offset` after the strict-source filter. The corpus is ordered by
`document_id`. The first 1,100 strict records therefore consist of all 378
eligible `publication:doi` records followed by 722 `publication:pmcid` records.
No `publication:pmid` record is part of this indexed tranche.

This explains the primary identity labels but does not justify hiding PMID
associations already present in local article and enrichment metadata.

## DOI Normalization Defect

Ninety-eight of the 378 structured DOI values include a Frontiers article-route
suffix such as:

```text
10.3389/fneur.2022.818522/full
```

The correct DOI is:

```text
10.3389/fneur.2022.818522
```

The current initial-load DOI regular expression captures the remaining URL path.
The correction should be a narrow deterministic normalization with tests and
identifier-level provenance. Do not broadly strip arbitrary DOI suffixes.

## URL Audit

- `canonical_url`: 1,100/1,100, all unique;
- canonical HTTPS: 1,098/1,100;
- canonical HTTP: 2/1,100;
- `source_url`: 1,100/1,100, all HTTPS;
- PMC OAI machine endpoints in `source_url`: 483.

The existing MCP search and detail responses expose `canonical_url` and
`source_url`, but the source URL can be a machine acquisition endpoint. A
physician-facing response should expose separately labeled links where locally
available:

- PubMed identity and abstract page;
- PMC full-text article page;
- DOI resolver URL;
- canonical publisher URL;
- source-acquisition URL for provenance.

The next implementation should propose and test `identity_urls` and a
deterministic `preferred_access_url`. It must not claim that a URL is live or
open access unless that status is supported by the indexed local provenance.
No live URL health check was performed in this audit.

## Required Next Implementation

1. Add a local-only, read-only bibliographic identity projection used by the
   retrieval index builder.
2. Read only the existing corpus, candidate records, primary article metadata,
   and cached enrichment artifacts.
3. Normalize identifiers conservatively, including the known Frontiers
   `/full` DOI extraction defect.
4. Preserve identifier value, source artifact, extraction method, normalization
   rule, and conflict status.
5. Keep the original corpus identity visible; do not silently replace it.
6. Expose enriched identity and labeled access URLs in both search and study
   detail responses.
7. Add an identity-coverage section to `retrieval inspect-index`.
8. Add unit and integration tests for identity extraction, conflict handling,
   URL derivation, DuckDB projection, and MCP responses.
9. Update the retrieval contract, README, decision log, and findings when the
   final response contract is chosen.
10. Run `uv run ruff check .` and `uv run pytest`, then commit and push directly
    to `origin/main` while keeping `main` as the only branch.

## Acceptance Boundary

- Do not mutate SQLite, review state, review queues, review decisions, candidate
  classification artifacts, or reviewed knowledge.
- Do not call an LLM, provider, or network service without explicit maintainer
  authorization.
- Identity enrichment is bibliographic retrieval metadata with provenance. It
  is not clinical truth, medical advice, or a treatment recommendation.
- Treat conflicts as explicit audit results. Never resolve a conflict by field
  precedence alone.
- Keep generated identity projections and indexes under ignored `data/` paths.

## Prompt For The Next Session

```text
Follow AGENTS.md. We can converse in Portuguese, but all code, documentation,
schemas, prompts, CLI output, and repository artifacts must remain in English.

MaryGenAI context:
- MaryGenAI is a scientific source-intelligence and candidate-classification
  engine for cannabinoid medicine.
- AI classifications are retrieval metadata and candidate evidence, not
  reviewed clinical truth, medical advice, or treatment recommendations.
- Do not mutate SQLite, review queues, review decisions, candidate records, or
  reviewed knowledge.
- Do not call an LLM, provider, or network service without explicit
  authorization.
- Use Python 3.13+, uv, supported code under src/marygenai/, and public commands
  through the marygenai CLI.
- Use apply_patch for edits.
- Run ruff and pytest.
- Keep main as the only active local and remote branch.

Read first:
- AGENTS.md
- README.md
- docs/product_value.md
- docs/mvp_plan.md
- docs/roadmap.md
- docs/official_workflows.md
- docs/classification_architecture.md
- docs/classification_dataset_plan.md
- docs/classification_data_dictionary.md
- docs/mcp_retrieval_contract.md
- docs/mcp_clinical_retrieval_research.md
- docs/decisions.md
- docs/experimental_findings.md
- docs/2026-07-11_batch_and_mcp_handoff.md
- docs/2026-07-17_identity_and_mcp_handoff.md

Current state:
- The ignored read-only DuckDB index contains 1,100 unique candidate documents
  from eight completed Batch runs.
- Current structured identity coverage is DOI 378, PMCID 722, PMID 0,
  canonical_url 1,100, and source_url 1,100.
- A read-only local audit recovered PMID for 1,087 documents, PMCID for 990, and
  DOI for 1,071 from primary HTML/NXML metadata, source/routing URLs, cached
  Europe PMC metadata, and cached OpenAlex metadata.
- After conservative normalization, 958 documents have all three identifiers,
  132 have two, 10 have one, and no conflicts were found.
- Ninety-eight structured DOI values incorrectly include a trailing Frontiers
  /full route suffix.
- All 1,100 records have canonical and source URLs, but 483 source URLs are PMC
  OAI machine endpoints rather than physician-facing article pages.
- SQLite and review state must remain untouched.

Objective:
Design and implement the first read-only bibliographic identity projection for
the retrieval index and MCP, using only existing local artifacts.

Required sequence:
1. Reproduce the identity audit before changing code and document any count
   difference.
2. Present a short plan and proposed identity/access-link response contract
   before implementation.
3. Implement conservative local identifier extraction and normalization with
   identifier-level provenance and explicit conflict handling.
4. Preserve the original corpus identity separately from projected retrieval
   identity.
5. Project enriched PMID, PMCID, DOI, and labeled PubMed, PMC full-text, DOI,
   canonical, and source URLs into DuckDB.
6. Expose the identity consistently in MCP search and detail responses.
7. Add identity coverage and conflict counts to the CLI index inspection.
8. Add focused unit tests and end-to-end retrieval/MCP tests.
9. Rebuild and inspect the ignored local index without mutating SQLite or
   review state.
10. Update README and relevant docs with the final contract and decision.
11. Run ruff and pytest.
12. Commit and push directly to origin/main, keeping main as the only branch.

Before implementing, show the proposed contract, especially identifier
provenance, conflict representation, identity_urls, preferred_access_url, and
the rules for choosing a physician-facing link.
```
