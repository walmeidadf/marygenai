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

1. Evaluate realistic, non-identifying physician questions and source-opening
   behavior.
2. Turn accepted questions into repeatable retrieval benchmarks covering useful
   results, false positives, suspected false exclusions, safe wording, and
   access links.
3. Improve ranking, query diagnostics, and direct-versus-tangential
   presentation where evaluation evidence justifies it.
4. Establish repeatable incremental PubMed discovery, source acquisition,
   classification, immutable index rebuild, and deliberate promotion.
5. Enrich bibliographic dates and types, identifier conflicts, URL quality,
   aliases, and the highest-value missing clinical retrieval fields.
6. Define the licensing and review boundary for a reproducible public data
   snapshot.

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
