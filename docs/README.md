# Documentation Index

MaryGenAI documentation is organized by purpose so readers can distinguish the
current product contract from plans and historical evidence.

## Start Here

1. [Project README](../README.md) — purpose, boundaries, setup, and public entry
   points.
2. [Current Status](current_status.md) — verified implementation snapshot,
   limitations, and next workstreams.
3. [Product Value](product_value.md) — intended users, value proposition,
   uncertainty, quality, and safety boundaries.
4. [Architecture](architecture.md) — supported modules, data layers, and trust
   boundaries.
5. [Official Workflows](official_workflows.md) — supported CLI operations.

## Product And Planning

- [Project Brief](project_brief.md)
- [MVP Plan](mvp_plan.md)
- [Roadmap](roadmap.md)
- [Source Availability Assessment](source_availability_assessment.md)

These documents describe direction and priorities. Planned capabilities are not
guarantees of current implementation.

## Retrieval And MCP

- [Read-Only MCP Retrieval Contract](mcp_retrieval_contract.md)
- [MCP Clinical Retrieval Research](mcp_clinical_retrieval_research.md)

The retrieval contract describes the implemented v1 interface. The clinical
research document includes evaluation questions and a future backlog.

## Classification

- [Classification Architecture](classification_architecture.md)
- [Classification Dataset And Contract](classification_dataset_plan.md)
- [Classification Data Dictionary](classification_data_dictionary.md)
- [Candidate Classification V4 Plan](classification_v4_plan.md)

The dataset contract documents the supported v3 candidate schema. The data
dictionary and v4 plan describe a future target and are explicitly not the
current public schema.

## Sources, Ontology, And Review

- [Data Sources](data_sources.md)
- [Ontology Notes](ontology.md)
- [Ontology Artifact Directory](../ontology/README.md)
- [Review Status Guide](review_status_guide.md)

Deployment operators should also read the
[Terraform environment guide](../infra/terraform/README.md).

## Historical Project Memory

- [Decision Log](decisions.md) — adopted product and architecture decisions,
  including superseded historical context.
- [Experimental Findings](experimental_findings.md) — durable observations from
  local experiments and pilot validation.

Historical counts, prices, provider limits, and interface observations are
time-stamped evidence, not current guarantees. Use
[Current Status](current_status.md) for the active operating snapshot.

## Publication Boundary

The repository intentionally excludes generated corpora, downloaded source
documents, PDFs, local databases, review state, private legacy exports,
credentials, deployment state, and secret-bearing access URLs. Public docs may
describe their schemas and provenance but must not imply that those artifacts
are included in a clone.

No software or data license has been published yet. See the
[License section](../README.md#license) before reusing repository content.
