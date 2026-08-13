# Current Status

Last documentation verification: 2026-08-13.

## Product State

MaryGenAI has an implemented read-only candidate-retrieval pilot. The original
maintainer-local classification campaign produced 3,149 strict-valid candidate
records with evidence spans, and the qualified PubMed extension added 288
candidate records. An isolated 3,437-record DuckDB snapshot exposes them through
the CLI, MCP stdio, stateless Streamable HTTP, and a private AWS development
deployment.

A first website and Dataset Viewer are now implemented. The web frontend
shares one visual and terminology system across project communication and
candidate inspection. The Viewer has a read-only Python adapter over the
existing retrieval service and a clearly labeled synthetic demonstration mode
for fresh clones without the ignored DuckDB index. The website is deployed as
a Cloudflare Worker with Static Assets at `marygenai.com`. The authenticated
AWS Viewer API and approved candidate snapshot are deployed, while the active
Worker remains in synthetic demonstration mode until its server-side proxy
version is validated and deliberately promoted.

Every indexed record remains `ai_classified_candidate` with
`review_state=needs_review`. No candidate classification has been promoted to
reviewed clinical knowledge by index construction or deployment.

The 3,149-document campaign is complete and its historical offsets are
exhausted. New provider-backed classification requires an explicitly approved
new or changed corpus.

Human-curation activation depends on external university partnerships and is
not the critical path for candidate-data progress. Candidate discovery,
source-quality work, classification, read-only presentation, and index refreshes
may continue while curation tooling and task packages are prepared, provided no
candidate is represented as human-reviewed knowledge.

## Current Data Funnels

The maintainer-local legacy funnel currently contains:

- 7,347 legacy source rows representing 7,344 unique documents;
- 6,491 records with at least one strong PMID, PMCID, or DOI identifier;
- 6,490 deduplicated records in the latest classification corpus;
- 3,374 source-ready records;
- 3,149 strict classification-ready and candidate-classified records;
- 3,116 identified corpus records that are not source-ready.

The legacy identity queue contains 838 open items, 15 in review, and 353
resolved items. Identity work can expand the canonical corpus, but it is
separate from recovering adequate source text for already identified records.

The largest locally recorded not-source-ready families are:

- 1,170 augmented-link artifacts with insufficient extracted text;
- 968 augmented-link access blocks;
- 356 PMC HTTP failures;
- 248 blocked Unpaywall PDF routes;
- 191 records without a selected source strategy.

The post-legacy PubMed funnel currently contains:

- 1,361 unique publication candidates, including 1,359 considered new against
  the local baseline;
- 1,037 candidates with direct title or indexed cannabinoid focus;
- 773 candidates with locally persisted open XML/HTML artifacts;
- 590 candidates that combine direct cannabinoid focus with an open XML/HTML
  artifact.

The first local source-quality rollup inspected 1,104 open-artifact rows across
the 773 candidates. It found that 773 artifacts declared as XML contain HTML,
and only 12 artifact rows confirm both the candidate title and a candidate PMID
or DOI. Eight unique direct-focus, 2024+ documents pass the complete hash,
identity, text-length, scientific-section, and cannabinoid-signal gate. The
frozen `pubmed_2024plus_canary.v1` manifest therefore contains eight records and
reports an explicit 92-document shortfall against the target of 100 rather than
admitting identity-mismatched sources.

The PubMed parser now limits primary identifiers to the article-level
`PubmedData/ArticleIdList`; cited-reference IDs can no longer overwrite the
primary PMCID or DOI in future discovery runs. The existing SQLite candidates
and review state were not rewritten. Expanding the canary requires a separately
authorized rediscovery or source-reenrichment repair that preserves existing
candidate and review provenance.

The explicitly authorized eight-document provider smoke test produced 8/8 HTTP
200 responses, valid JSON, strict schema-valid candidate records, and records
with evidence spans, with no errors or retries. The evaluator accepted all
28 evidence spans with extraction tolerance and selected no document for rerun.
There is no normalized legacy reference for these new records, so this result
validates technical execution, grounding, retrieval-field production, and
provenance rather than independent scientific agreement.

The supported read-only identity-repair overlay then selected 150 direct-focus,
2024+ source-identity failures and resolved all 150 by their existing PMID with
zero fetch errors. Title and DOI agreed for all 150, while every persisted PMCID
changed. PubMed returned a corrected PMCID for 149 records; one record has no
PMCID and remains routed to Europe PMC or Unpaywall. The 149 corrected PMC
identities form the next ignored reenrichment worklist. SQLite, review queues,
review decisions, and reviewed knowledge remained unchanged.

Corrected-PMC reenrichment then evaluated 105 Europe PMC full-text XML
artifacts and froze the 100-document `pubmed_2024plus_canary.v2` corpus with no
shortfall. Five evaluated sources failed the unchanged identity/content gate.
The v2 gate also excludes veterinary-only, clearly non-medical, and titles
without a human medical or public-health signal. A cached rerun reproduced the
frozen manifest and corpus byte for byte. One local 100-request Batch input was
prepared with zero errors and an estimated 1,000,188 enqueued tokens;
preparation did not upload or call a model.

The completed v2 Batch produced 100/100 strict-valid candidate records with no
provider or conversion errors. Local evaluation accepted all 467 evidence spans
with extraction tolerance, selected no reruns, and assigned 37 high and 63
medium retrieval-confidence bands. An isolated 100-document DuckDB index has
complete PMID, PMCID, and DOI coverage with no identity conflicts. Direct MCP
calls to `search_studies` and `get_study` succeeded and preserved preferred PMC
access URLs, `needs_review`, and the human-review boundary.

The next corrected-PMC slice resolved 350/350 PubMed identities, froze 100 new
documents after excluding the v2 manifest, and reproduced its v3 manifest and
corpus byte for byte from cache. The prepared second Batch contains 100 unique
requests, zero local errors, no overlap with v2, and an estimated 999,836
enqueued tokens. The Batch completed 100/100 with no provider or conversion
errors. Evaluation accepted 462/464 evidence spans with extraction tolerance,
preserved two spans in the grounding-review worklist, and selected no document
for a paid rerun.

An isolated combined v2+v3 DuckDB index now exposes 200 candidates from both
classification runs. It has PMID and PMCID coverage for all 200 records, DOI
coverage for 199, and no projected identity conflicts. Direct MCP regression
calls retrieved v2 and v3 results, returned preferred PMC access URLs, opened a
flagged study detail with `grounding_review.status=requires_review`, and
preserved `needs_review` and human-review-required boundaries.

The v4 identity expansion resolved 500/500 PubMed records and recovered 499
official PMCIDs. After excluding the 200 prior documents, the unchanged source
and medical-scope gates selected 91 new records and reported a nine-document
shortfall rather than weakening criteria. The v4 Batch completed 91/91 with no
provider or conversion errors. Evaluation accepted all 425 evidence spans with
extraction tolerance, selected no grounding-review spans, and required no paid
reruns.

Post-classification inspection found three source-selection false positives
with no structured cannabinoid or exposure: a tobacco-cessation article and two
surgical articles where `CBD` meant common bile duct. The retrieval index now
supports an explicit, provenance-recorded cannabinoid-exposure inclusion gate.
The qualified v2+v3+v4 canary contains 288 candidates, preserves the excluded
records in an ignored report, retains the two prior v3 grounding-review spans,
and exposes only `needs_review` candidate evidence through MCP. A run-scoped
variant of the gate preserves the existing 3,149 records, including 63 older
classifications with no structured exposure, while applying the new exclusion
rule only to the three PubMed classification runs.

The private AWS development MCP now serves an immutable combined snapshot of
3,437 candidates: all 3,149 prior records plus the 288 qualified PubMed
candidates. The snapshot-only update preserved the deployed Lambda code hash,
changed no Viewer routes, and passed authenticated remote smoke tests for old
and new records. All records remain `ai_classified_candidate` and
`needs_review`.

## Implemented Surface

The supported CLI includes:

```bash
uv run marygenai retrieval build-index
uv run marygenai retrieval inspect-index
uv run marygenai retrieval search --query "cannabidiol"
uv run marygenai mcp serve
uv run marygenai mcp serve-http
uv run marygenai viewer serve-api
```

The MCP surface provides:

- `search_studies` for lexical and structured candidate retrieval;
- `get_study` for full identity, evidence, uncertainty, and provenance;
- `get_facets` for bounded index counts;
- `get_search_capabilities` for supported filters and presentation rules.

The same query service backs all interfaces. DuckDB is opened with
`read_only=True`; the runtime receives no SQLite database, review state,
provider credentials, provider tools, or data-write tools.

The AWS Lambda gateway now deploys the Viewer route set at `/api/viewer/*`. It
reuses the same hash-verified 3,437-record S3 DuckDB snapshot as MCP but requires
a distinct bearer credential and rejects query-string tokens. The reviewed
Terraform apply created three routes, updated the API and Lambda in place, and
destroyed no resources. Authenticated remote smoke tests passed for metadata,
listing, detail, preferred source links, credential isolation, private-path
omission, no-store headers, the custom domain, and existing MCP initialization.
The Cloudflare website is not yet connected to this credentialed API.

MCP contract hardening now projects stored filesystem paths into opaque artifact
references without changing the index, and exposes a typed path-free manifest
in both local and Lambda runtimes. Regression tests cover search, detail, study
resources, and the manifest fallback used when the adjacent operator manifest
is intentionally absent from Lambda. The Lambda-only apply updated one resource
in place and destroyed none. Authenticated remote smoke tests confirmed zero
local-path occurrences, native manifest number/list types, unchanged 3,437-record
results, preserved preferred access URLs, and no Viewer regression.

The supported `web/` frontend provides:

- a public project website for physicians, researchers, professors, students,
  and scientific partners;
- paginated candidate search with URL-backed filters and deterministic sorting;
- explicit direct/tangential match, confidence, `needs_review`, and trust-state
  presentation;
- study detail with bibliographic identity, evidence, uncertainty, warnings,
  provenance, and preferred source-link support;
- loading, error, empty, unavailable, desktop, and mobile states;
- synthetic public fixtures when the complete local index is unavailable.

The frontend does not include SQLite, review queues, review decisions, private
legacy context, provider credentials, or index-write operations.

## Local Artifact Boundary

The complete pilot depends on ignored maintainer-local artifacts:

- candidate-classification runs;
- evaluation outputs;
- the source corpus;
- the generated DuckDB index and manifest;
- private legacy validation context.

These artifacts are not distributed in the repository. A fresh public clone can
run public source discovery and build new local corpora, but it cannot reproduce
the active 3,437-record index until a licensed public snapshot is published.

## Known Limitations

- Search is deterministic lexical matching, not semantic retrieval.
- The index is bounded and static; zero matches do not establish absence from
  the scientific literature.
- Condition and cannabinoid aliases are not yet a versioned ontology service.
- Rank and confidence are not clinical evidence strength or calibrated
  probabilities.
- Candidate study design and bibliographic publication type can disagree.
- Publication dates do not yet distinguish online-first, issue, print, and
  indexing dates throughout the contract.
- V3 does not reliably structure dose, route, formulation, comparator,
  duration, detailed age group, sample size, geography, outcome entity, or
  adverse-event entity.
- Some projected bibliographic identifiers have explicit unresolved conflicts.
- The runtime performs no live source lookup, URL-health check, citation
  traversal, related-study lookup, or full-text delivery.
- The private pilot uses shared access control and does not claim per-physician
  identity, scopes, or independent revocation.
- The committed frontend defaults to fictional demonstration records because
  the complete local index is not distributed.
- The active Cloudflare Worker serves the frontend as Static Assets and the
  synthetic Viewer remains the fallback when same-origin API routes are absent.
  The separate authenticated AWS API and immutable snapshot are available, but
  exposing real candidate records through Cloudflare still requires deliberate
  promotion of the server-side proxy plus access and licensing review.

## Next Workstreams

Maintainer-controlled candidate-data work proceeds in this order:

1. Preserve acceptance cases from realistic non-identifying questions against
   the deployed 3,437-record snapshot, including the two v3 grounding-review
   findings and known lexical-search sensitivity.
2. Exercise the Viewer against the combined immutable candidate index and
   decide the access boundary for an external environment.
3. Configure and test a new version of the existing Cloudflare Worker as the
   same-origin server-side proxy without exposing the Viewer bearer credential
   to browsers.
4. Review website access, repository links, hosting configuration, and the
   no-license boundary before enabling the real Viewer on the public site.
5. Expand the PubMed candidate slice only after technical, retrieval, grounding,
   provenance, cost, and regression gates pass.
6. Run bounded automated legacy-recovery campaigns, starting with official PMC
   failures and deterministic identity suggestions.
7. Rebuild and deliberately promote immutable candidate indexes without
   mutating review state.

The parallel curation-readiness track prepares:

1. a minimal field-level review contract;
2. annotation-tool import and export adapters;
3. training, calibration, and first production task packages;
4. reviewer identity, institutional affiliation, double-review, adjudication,
   and provenance rules;
5. a validated path from external responses to append-only MaryGenAI review
   decisions and later reviewed snapshots.

Realistic, non-identifying physician questions remain a continuous product
input. They should guide viewer filters, review fields, ranking changes, and
legacy-recovery priorities without blocking the controlled work above.

## Verification Baseline

At this snapshot:

- the GitHub repository is public;
- `main` is the default and only remote branch;
- GitHub secret scanning and push protection are enabled, with no open secret
  alerts at verification time;
- no software or data license is published;
- repository source, tests, documentation, infrastructure configuration, and
  lock files are tracked;
- generated data, private inputs, credentials, local databases, and deployment
  state are ignored.

Run the current local validation suite before changing this status:

```bash
uv run ruff check .
uv run pytest
```
