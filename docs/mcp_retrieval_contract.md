# Read-Only MCP Retrieval Contract

## Status

This document describes the implemented MaryGenAI retrieval-index and MCP
contract over the active private 3,437-record snapshot: 3,149 strict
classification-ready records plus 288 qualified PubMed candidates.

`search_studies` uses `candidate_retrieval_api.v3`, an agent-compact result
contract. Search carries only the fields needed to shortlist records; complete
bibliographic provenance and candidate-classification detail remain available
through `get_study`. API v3 was promoted to the private AWS pilot on
2026-08-21 without changing the immutable retrieval snapshot.

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
6. the `marygenai` CLI and a local MCP stdio server over the same query service;
7. an optional stateless Streamable HTTP application;
8. an AWS dev deployment with API Gateway, Lambda, and a private immutable
   DuckDB snapshot in S3.

The build does not open or mutate MaryGenAI SQLite, review queues, review
decisions, or reviewed knowledge. The MCP runtime has no provider, review, or
persistence tools and performs no outbound source-network calls.

## Supported Commands

Build the default 3,149-document index:

```bash
uv run marygenai retrieval build-index
```

Inspect manifest, capabilities, and top facets:

```bash
uv run marygenai retrieval inspect-index
```

Export explicit identity conflicts for manual adjudication without applying
decisions:

```bash
uv run marygenai retrieval export-identity-conflicts \
  --classification-run-id <classification_run_id>
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

Serve MCP over local stateless Streamable HTTP:

```bash
uv run marygenai mcp generate-access-token \
  --output-path data/private/mcp-dev-access-token.json
export MARYGENAI_MCP_BEARER_TOKEN_SHA256=<reported_sha256>
uv run marygenai mcp serve-http
```

The HTTP runtime uses JSON responses and stateless MCP sessions. A temporary
pilot token is accepted through the preferred `Authorization: Bearer` header.
Query credentials are disabled by default and require an explicit runtime flag.
The private development pilot may enable exactly one query credential for hosts
that cannot configure fixed request headers. Other credential query fields,
duplicate keys, and simultaneous header/query credentials are rejected. This
compatibility gate is not the final multi-client authorization design and does
not provide per-physician identity, scopes, or independent revocation.

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

The indexed source and candidate metadata are primarily English. MCP server
instructions, tool descriptions, the generated input schema, and
`get_search_capabilities.language_contract` direct the host to translate a
non-English question into concise English retrieval terms and structured filter
labels before calling search. Identifiers and quoted source evidence must remain
unchanged. The host should synthesize the final answer in the user's language.
For example, a Portuguese question about "síndrome de Dravet e canabidiol"
should query `Dravet syndrome` and `cannabidiol`, while the final explanation
may remain in Portuguese.

Search responses and capabilities expose a machine-readable
`presentation_contract`. MCP hosts must:

- describe returned records as AI-classified candidate matches, not validated
  relevant studies;
- interpret zero results only as no candidate records retrieved from the
  current index for the effective query, never as evidence that the scientific
  literature contains no such studies;
- include `results[].preferred_access_url` whenever citing a returned record;
- call `get_study` for shortlisted records before making detailed evidence
  claims;
- distinguish direct matches from tangential matches using the question,
  effective query, title, candidate metadata, match explanation, and detailed
  source evidence.

The server assigns a deterministic lexical `direct` or `tangential` match kind.
`direct` means every effective query term matched the title, condition labels,
or cannabinoid/exposure labels. A match only in design, context, population,
outcome, or direction metadata is `tangential`. This is an inspectable search
explanation, not a clinical relevance classification; the host must still
compare shortlisted records with the user's question and study detail.
For filter-only searches, at least one condition or cannabinoid/exposure filter
anchors a `direct` match; searches constrained only by non-core metadata are
`tangential`. Unfiltered browsing retains `direct` as a neutral default.

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
- one search trace containing query terms, requested and applied filters,
  host-declared unsupported dimensions, and explicit relaxations;
- per-result title, year, compact accepted identifiers, condition and exposure
  labels, the main retrieval facets, classification and retrieval-confidence
  bands, uncertainty fields, and review state;
- one bounded extractive evidence preview of at most 320 characters when
  candidate evidence is available;
- deterministic match kind and field-level reasons;
- the deterministic preferred physician-facing access URL and a study-detail
  resource URI;
- one response-level candidate-evidence trust boundary;
- the host presentation contract for candidate wording, zero-result scope,
  preferred access links, study-detail inspection, and tangential matches.

Search deliberately omits original identity, identifier-candidate provenance,
the full classification object, repeated trust language, and model/prompt
provenance. `get_study` is the audit-complete interface for those fields. The
MCP tools return typed models so discovery exposes concrete output schemas
rather than generic free-form objects.

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
- an opaque source-artifact reference and the source text SHA-256;
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
limits, ranking semantics, language and host-translation requirements, included
classification runs, and v3 schema gaps.

The public manifest uses stable JSON types for counts, lists, and trust fields
in both local and AWS runtimes. It omits index, corpus, input-file, evaluation,
and exclusion paths. Exact paths remain private internal provenance. Path-shaped
fields retained for schema compatibility contain non-resolvable
`artifact-ref://sha256/...` values on the MCP surface.

## MCP Resources

- `marygenai://index/manifest` returns the index build manifest;
- `marygenai://index/capabilities` returns search capabilities;
- `marygenai://studies/{document_id}` returns complete study detail.

## Safety And Privacy

All tools declare read-only, non-destructive, idempotent, closed-world MCP
annotations. Enforcement comes from the isolated index and DuckDB read-only
runtime, not from annotations alone.

In the AWS dev runtime, Lambda can read exactly one content-addressed DuckDB
object. It verifies SHA-256 before replacing the warm `/tmp` copy. The private
deployment manifest is uploaded for operator provenance but is not copied next
to the runtime index. The MCP transport projection and typed public manifest
prevent stored build-host paths from being returned by tools or resources.

The public custom hostname terminates with an ACM certificate on API Gateway.
Cloudflare remains the external DNS provider and is configured manually. The
first smoke test uses a DNS-only application CNAME; proxying and WAF controls
are a later independent hardening step.

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

## Known Pilot Limits

- The active index covers 3,437 candidates: 3,149 strict classification-ready
  documents plus 288 qualified PubMed candidates.
- Sixty documents expose explicit projected-identity conflicts. Fifty-nine
  entered with the final offset and require source-routing or identity review.
- Bibliographic `publication_year` does not yet distinguish online-first,
  journal-issue, indexing, and print publication dates.
- Candidate study-design categories may disagree with authoritative
  bibliographic publication types. Both meanings must remain separate rather
  than silently overwriting one another.
- An external source may disagree with the currently projected DOI or another
  identifier after an index build. The current closed snapshot does not perform
  live reconciliation or URL-health checks.
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
  through the current MCP pilot.

The research and backlog behind these limits are preserved in
`docs/mcp_clinical_retrieval_research.md`.
