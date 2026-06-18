# Source Availability Assessment

## Decision

The private legacy-only corpus is large enough to validate classification and
retrieval, but it should not define the project's growth ceiling. Continuous
PubMed discovery is the preferred expansion path.

## Classification-Ready Definition

A classification-ready document has enough authentic source text to support
coarse retrieval labels such as study type, condition, cannabinoid role,
population, evidence context, and outcome domain.

Classification-ready does not require perfect table extraction, figure
interpretation, dosage reconstruction, or protocol reconstruction.

## Current Maintainer-Local Result

The June 2026 legacy-core source campaign produced:

- 6,491 operational documents with useful identity;
- 3,149 strict classification-ready documents after deduplication;
- 3,374 broader source-ready documents.

Strict readiness requires sufficient source length, scientific-section signal,
and a simple cannabinoid signal. Broader readiness does not require that simple
term detector to fire.

These counts describe ignored local artifacts. They are not committed public
datasets.

## Validated Source Lessons

- PMC OAI-PMH was the strongest official structured route.
- Digital PDF extraction recovered meaningful additional source text.
- NCBI ELink and OpenAlex were useful as access and identity augmentation.
- OCR applies to a small residual class.
- Metadata-only payloads are useful for discovery but not source-ready.
- HTTP success is not content validation.
- Challenge pages, JavaScript shells, malformed XML, and missing payloads must be
  separated from usable text.

## Operational Routing

Keep these states distinct:

- `usable_for_llm_classification`;
- `needs_reenrichment`;
- `source_triage_needed`;
- `identity_or_focus_review`;
- `not_enriched`.

Do not blindly retry the same failed source route. Preserve invalid artifacts for
audit and select a different strategy.

## Product Interpretation

Source readiness affects classification confidence and retrieval rank, but a
partial source may still support broad metadata retrieval. The system should
declare source limitations instead of converting them into unsupported precise
labels.

## Growth Path

1. Run explicit-window PubMed discovery.
2. Resolve and deduplicate identity.
3. Prioritize direct cannabinoid focus.
4. Enrich through official or source-declared routes.
5. Apply content-quality gates.
6. Add source-ready records to classification corpora.
7. Publish reproducible public snapshots when licensing permits.

## Safety Boundary

Source availability does not imply evidence quality, clinical applicability, or
treatment recommendation. It only describes whether the project has enough
authentic material for the intended retrieval and classification task.
