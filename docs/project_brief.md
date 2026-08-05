# Project Brief

MaryGenAI is a public scientific source-intelligence and
candidate-classification research project for cannabinoid medicine.

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

The first external product is an implemented read-only MCP pilot. It lets a
research assistant filter and rank candidate studies by condition, cannabinoid,
study type, population, outcomes, source quality, and classification
confidence, while linking every result back to the original publication and
supporting evidence.

## Trust Boundary

AI classifications are probabilistic retrieval metadata. Human-reviewed
knowledge remains a separate, higher trust level. MaryGenAI does not provide
medical advice or treatment recommendations.

The private maintainer bootstrap is used locally as a trusted validation anchor.
It is not distributed publicly. Future reviewed public snapshots should become
the reproducible baseline for contributors.

## Current Milestone

The current milestone is candidate-data growth and product readiness without
making the availability of external curators the critical path.

The pilot exposes 3,149/3,149 strict-valid candidate records from twenty-four
classification runs through an isolated DuckDB index and stateless Streamable
HTTP on AWS. Hosted ChatGPT and Claude connectors have completed end-to-end
tests. The records preserve evidence spans, uncertainty, source identity,
access URLs, and provenance, and remain candidate evidence rather than reviewed
knowledge.

Near-term work should:

- prepare and evaluate a bounded PubMed 2024+ classification canary before
  expanding the candidate index;
- build a read-only Dataset Viewer with useful filters, study detail, provenance,
  source links, and visible candidate-versus-reviewed state;
- publish a community-oriented website for physicians, professors, students,
  and research partners;
- complete the curation contract, annotation-tool adapter, reviewer materials,
  and validated import path before university curators are available;
- run targeted automated legacy recovery only where measured source-ready yield
  or retrieval coverage justifies it;
- use realistic, non-identifying physician questions continuously to guide
  retrieval, enrichment, and presentation priorities.

Human review remains required for reviewed knowledge, but candidate discovery,
source validation, classification, evaluation, and immutable index refresh can
continue independently with explicit `ai_classified_candidate` and
`needs_review` states.

See [Current Status](current_status.md), [Product Value](product_value.md),
[MVP Plan](mvp_plan.md), and [Roadmap](roadmap.md).

## Non-Goals

- diagnosis or treatment recommendation;
- replacing clinical appraisal of source studies;
- claiming that model confidence is a calibrated probability;
- presenting AI-classified records as human-reviewed;
- supporting historical standalone POC commands as public APIs;
- committing private inputs or generated source artifacts.
