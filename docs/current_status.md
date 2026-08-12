# Current Status

Last documentation verification: 2026-08-12.

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
enqueued tokens. It remains local until explicit submission.

None of the 1,361 PubMed candidates is part of the existing 3,149-record MCP
snapshot.

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

1. Submit, watch, and evaluate the prepared second 100-document Batch for the
   frozen PubMed v3 slice. Then rebuild a combined v2+v3 candidate index and
   repeat MCP retrieval regression checks without mutating protected review
   state.
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
