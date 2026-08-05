# Current Status

Last documentation verification: 2026-08-05.

## Product State

MaryGenAI has an implemented read-only candidate-retrieval pilot. The
maintainer-local classification campaign produced 3,149 strict-valid candidate
records with evidence spans. An isolated DuckDB index exposes those records
through the CLI, MCP stdio, stateless Streamable HTTP, and a private AWS
development deployment.

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

These 773 artifacts have not yet passed a new classification-corpus quality
rollup. None of the 1,361 PubMed candidates is part of the existing 3,149-record
MCP snapshot.

## Implemented Surface

The supported CLI includes:

```bash
uv run marygenai retrieval build-index
uv run marygenai retrieval inspect-index
uv run marygenai retrieval search --query "cannabidiol"
uv run marygenai mcp serve
uv run marygenai mcp serve-http
```

The MCP surface provides:

- `search_studies` for lexical and structured candidate retrieval;
- `get_study` for full identity, evidence, uncertainty, and provenance;
- `get_facets` for bounded index counts;
- `get_search_capabilities` for supported filters and presentation rules.

The same query service backs all interfaces. DuckDB is opened with
`read_only=True`; the runtime receives no SQLite database, review state,
provider credentials, provider tools, or data-write tools.

## Local Artifact Boundary

The complete pilot depends on ignored maintainer-local artifacts:

- candidate-classification runs;
- evaluation outputs;
- the source corpus;
- the generated DuckDB index and manifest;
- private legacy validation context.

These artifacts are not distributed in the repository. A fresh public clone can
run public source discovery and build new local corpora, but it cannot reproduce
the existing 3,149-record index until a licensed public snapshot is published.

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

## Next Workstreams

Maintainer-controlled candidate-data work proceeds in this order:

1. Build and evaluate a bounded PubMed 2024+ source-quality and classification
   canary from direct-focus records with open XML/HTML.
2. Build a read-only Dataset Viewer over the candidate retrieval contract, with
   explicit candidate/reviewed state and no private artifact exposure.
3. Publish a physician-, professor-, and student-oriented project website that
   explains the current dataset, MCP, trust boundary, and collaboration path.
4. Expand the PubMed candidate slice only after technical, retrieval, grounding,
   provenance, cost, and regression gates pass.
5. Run bounded automated legacy-recovery campaigns, starting with official PMC
   failures and deterministic identity suggestions.
6. Rebuild and deliberately promote immutable candidate indexes without
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
