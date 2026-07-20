# Read-Only MCP Retrieval Contract

## Status

This document describes the first implemented MaryGenAI retrieval-index and MCP
contract over the current 1,400-document broad/v3 candidate tranche.

The interface returns AI-classified candidate evidence. It does not return
reviewed clinical truth, medical advice, or treatment recommendations.

## Architecture

The supported data flow is:

1. ignored candidate-classification JSONL artifacts;
2. the ignored classification corpus for bibliographic identity;
3. ignored evaluation artifacts for retrieval confidence and grounding-review
   worklists;
4. an isolated ignored DuckDB retrieval index;
5. a query service that opens DuckDB with `read_only=True`;
6. the `marygenai` CLI and a local MCP stdio server over the same query service.

The build does not open or mutate MaryGenAI SQLite, review queues, review
decisions, or reviewed knowledge. The MCP runtime has no provider, network,
review, or persistence tools.

## Supported Commands

Build the default 1,400-document index:

```bash
uv run marygenai retrieval build-index
```

Inspect manifest, capabilities, and top facets:

```bash
uv run marygenai retrieval inspect-index
```

Run a local query through the MCP-equivalent retrieval contract:

```bash
uv run marygenai retrieval search \
  --condition "Dravet syndrome" \
  --cannabinoid Cannabidiol \
  --population pediatric_humans \
  --outcome-domain efficacy \
  --outcome-domain safety
```

Serve MCP over stdio:

```bash
uv run marygenai mcp serve
```

The default ignored index is:

```text
data/normalized/retrieval_indexes/marygenai_candidate_retrieval_v1.duckdb
```

An adjacent ignored manifest records input paths and hashes, build identity,
included runs, document count, limitations, and trust language.

## MCP Tools

### `search_studies`

Input is a `SearchRequest` with:

- optional local keyword `query`;
- optional `question_type` for host context;
- structured filters;
- a list of clinical dimensions the host could not represent;
- result limit from 1 to 50;
- an opaque cursor.

The first implementation applies question type as context only, not as a hidden
filter or ranking adjustment.

Supported structured filter families are:

- medical conditions;
- cannabinoids or exposures;
- study-design categories and subtypes;
- evidence contexts;
- population categories;
- intervention or exposure roles;
- outcome domains;
- overall directions;
- classification-confidence categories;
- review states;
- publication-year bounds;
- whether candidate uncertainty is declared.

Every multi-value facet group declares `match=any` or `match=all`. Filter groups
are combined with AND. Matching uses deterministic case-folded alias keys. No
filter is silently relaxed.

The response includes:

- total matches and returned count;
- opaque next cursor;
- query terms;
- requested and applied filters;
- host-declared unsupported dimensions;
- an empty `relaxations` list in v1;
- compact source identity and candidate retrieval metadata;
- original corpus identity and the separate projected bibliographic identity;
- identifier-level provenance, explicit conflicts, labeled identity URLs, and
  the deterministic preferred physician-facing access URL;
- classification and retrieval confidence with separate semantics;
- declared uncertainty and review state;
- deterministic match explanations;
- a study-detail resource URI;
- the candidate-evidence trust boundary.

Results are ordered by retrieval-confidence heuristic, publication year, and
stable document identity. The retrieval-confidence value is not a calibrated
probability or clinical evidence strength.

### `get_study`

Returns one complete candidate record with:

- original corpus identity and projected bibliographic identity;
- every PMID, PMCID, and DOI candidate with source artifact, extraction method,
  raw value, normalization rule, and conflict status;
- labeled PubMed, PMC full-text, DOI, canonical, and acquisition URLs;
- a deterministic `preferred_access_url` that never prefers a machine endpoint;
- source text path and SHA-256;
- source trust level;
- every v3 candidate field and evidence span;
- missing or uncertain fields and warnings;
- grounding-review worklist status and flagged spans;
- retrieval-confidence record;
- model, prompt, schema and extractor versions;
- technical repair and Batch provenance;
- index build identity;
- review state and trust boundary.

`not_flagged_for_review` means only that the evaluator did not place a span on
the grounding-review worklist. It is not a human-review claim.

## Bibliographic Identity And Access Links

`original_corpus_identity` preserves the source corpus values unchanged.
`projected_identity` is derived locally from structured corpus fields,
primary-article HTML/NXML metadata, source-routing records, and cached
enrichment metadata. The projection does not update SQLite, candidate records,
review state, or reviewed knowledge.

An identifier is projected only when all accepted local evidence normalizes to
one value. Multiple distinct normalized values produce `status=conflict`, a
null projected value, and explicit candidate values with provenance. Source
precedence never resolves a conflict silently. The narrow
`frontiers_full_route_suffix.v1` rule removes `/full` only from DOI-shaped
Frontiers article routes.

`identity_urls` labels PubMed, PMC full-text, DOI resolver, canonical, and
source-acquisition links. `preferred_access_url` selects the first available
physician-facing link in this order: PMC full text, PubMed, DOI, canonical, then
source. PMC OAI and other machine acquisition endpoints remain visible for
provenance but are never preferred. The contract does not claim URL health,
open-access status, or full-text availability without supporting provenance.

## Remaining MCP Tools

### `get_facets`

Returns canonical facet counts over the filtered set before pagination. Original
candidate labels remain unchanged in study detail.

### `get_search_capabilities`

Returns supported filters, cardinalities, match modes, question types, cursor
limits, ranking semantics, included classification runs, and v3 schema gaps.

## MCP Resources

- `marygenai://index/manifest` returns the index build manifest;
- `marygenai://index/capabilities` returns search capabilities;
- `marygenai://studies/{document_id}` returns complete study detail.

## Safety And Privacy

All tools declare read-only, non-destructive, idempotent, closed-world MCP
annotations. Enforcement comes from the isolated index and DuckDB read-only
runtime, not from annotations alone.

An MCP host should not send a patient record or directly identifying patient
data. It should translate a physician's question into the smallest set of
non-identifying scientific retrieval dimensions needed for the search.

Every response states:

```json
{
  "trust_level": "ai_classified_candidate",
  "review_state": "needs_review",
  "requires_human_review": true,
  "medical_advice": false
}
```

## Known V1 Limits

- The index covers a bounded 1,400-document tranche, not the complete corpus.
- V3 does not reliably structure dose, route, formulation, comparator, duration,
  study period, detailed age group, sex or gender, sample size, country,
  comorbidity, outcome entity, or adverse-event entity.
- Condition and exposure alias handling is conservative and is not yet a
  versioned ontology-expansion service.
- Keyword search is local lexical matching over title and candidate metadata;
  it is not semantic retrieval.
- Question type does not yet select validated Clinical Query-style evidence
  filters.
- No citations, references, related-study graph, or full-text content is exposed
  through MCP v1.

The research and backlog behind these limits are preserved in
`docs/mcp_clinical_retrieval_research.md`.
