# Project Brief

MaryGenAI is an open-source scientific source-intelligence and
candidate-classification engine for cannabinoid medicine.

## Problem

Relevant literature is distributed across publication indexes, repositories,
publisher pages, PDFs, and inconsistent metadata. Physicians and researchers
spend time locating studies before they can assess them. General-purpose AI tools
can help search, but they need a structured, provenance-aware scientific source
layer.

## Proposed Solution

MaryGenAI continuously:

1. discovers candidate documents;
2. resolves publication identity;
3. enriches metadata and source-access paths;
4. prepares usable source text;
5. adds evidence-backed candidate classifications;
6. exposes structured records for retrieval by humans and AI tools.

The intended first external product is a read-only MCP interface. It should let a
research assistant filter and rank studies by condition, cannabinoid, study type,
population, outcomes, source quality, and classification confidence, while
linking every result back to the original publication and supporting evidence.

## Trust Boundary

AI classifications are probabilistic retrieval metadata. Human-reviewed
knowledge remains a separate, higher trust level. MaryGenAI does not provide
medical advice or treatment recommendations.

The private maintainer bootstrap is used locally as a trusted validation anchor.
It is not distributed publicly. Future reviewed public snapshots should become
the reproducible baseline for contributors.

## Current Milestone

The current milestone is to turn the first candidate-classified base into a
read-only retrieval/MCP demonstration for medical-team feedback and human-review
recruitment.

The project now has a local 500-document strict classification-ready Batch
tranche with 500/500 strict-valid candidate records, source evidence spans,
uncertainty, and provenance. Those records remain candidate evidence, not
reviewed knowledge.

Near-term work should stabilize:

- the deduplicated classification corpus;
- candidate-classification schema and prompt;
- confidence and uncertainty semantics;
- evaluation metrics for technical validity, retrieval utility, and inference
  quality;
- a repeatable path from PubMed discovery to source-ready candidate records;
- a read-only retrieval index and MCP server over candidate records.

See [Product Value](product_value.md), [MVP Plan](mvp_plan.md), and
[Roadmap](roadmap.md). The current Batch/MCP handoff is documented in
[2026-07-11 Batch And MCP Handoff](2026-07-11_batch_and_mcp_handoff.md).

## Non-Goals

- diagnosis or treatment recommendation;
- replacing clinical appraisal of source studies;
- claiming that model confidence is a calibrated probability;
- presenting AI-classified records as human-reviewed;
- supporting historical standalone POC commands as public APIs;
- committing private inputs or generated source artifacts.
