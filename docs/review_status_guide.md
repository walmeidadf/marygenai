# Review Status Guide

This guide explains the review states used by the local MaryGenAI MVP. It is
intended for reviewers and contributors who need to understand what each status
means before changing queue items or candidate records.

MaryGenAI currently has two review queues:

- `legacy_identity_review`: private maintainer-bootstrap records from the legacy
  dataset that need identity curation, usually because they lack strong
  identifiers such as PMID, PMCID, or DOI.
- `publication_candidate_review`: PubMed discoveries from the post-legacy
  enrichment workflow. These are candidate publications, not reviewed knowledge.

The most important rule is that workflow status, identity classification, and
reviewed knowledge are different things.

## Status Layers

MaryGenAI uses several related but separate status fields.

| Layer | Field | Applies to | Purpose |
| --- | --- | --- | --- |
| Queue workflow | `review_item.status` | Both review queues | Tracks where a human review task is in the local workflow. |
| Document review state | `document.review_state` | Publications and other documents | Marks whether the document still needs review before it can be treated as curated. |
| PubMed-baseline identity | `publication_candidate_discovery.identity_status` | PubMed candidate discoveries | Classifies the candidate's relationship to the baseline/legacy index. |
| Structured identity decision | `review_decision.decision` | Identity review tasks | Stores a reviewer decision separately from queue workflow status. |

Do not treat a queue item becoming `resolved` as proof that the publication is
fully curated knowledge. For PubMed candidates, `resolved` usually means the
candidate-review task has been handled, not that downstream enrichment fields
have been extracted, validated, and exported.

## Queue Workflow Status

The field `review_item.status` is shared by both `legacy_identity_review` and
`publication_candidate_review`.

| Status | Meaning | Reviewer action |
| --- | --- | --- |
| `open` | The item is waiting for review. | Pick it up only if no one else is reviewing it. |
| `in_review` | A reviewer has started working on the item. | Continue inspection, add notes, and create any needed structured decision. |
| `resolved` | The reviewer finished the task and the item should no longer appear in the open queue. | Use when the identity/candidate decision is sufficient for the current workflow. |
| `dismissed` | The item should not continue in the active workflow. | Use when it is not the same publication, not useful for the queue purpose, or should be excluded from this workflow. |

Status changes are operational. They update local SQLite only and do not rewrite
the ignored JSONL snapshots under `data/`.

Useful commands:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review list --queue publication_candidate_review
uv run marygenai review update <review_item_id> --status in_review --note "Review started"
```

## Legacy Identity Review

The `legacy_identity_review` queue exists because some private legacy records
are valuable but have weak publication identity. These records usually need a
reviewer to confirm or correct identifiers.

Typical reviewer questions:

- Is this legacy record the same publication as the candidate identity signals
  suggest?
- Can a PMID, PMCID, DOI, or canonical URL be confirmed?
- Should the item be resolved as a confirmed/corrected identity, dismissed as not
  the same publication, or left unresolved?

Structured identity decisions are stored in `review_decision` and are separate
from `review_item.status`.

| Decision | Meaning | Apply result |
| --- | --- | --- |
| `confirmed_identity` | The existing identity signals are correct. | Applying the decision sets the queue item to `resolved`. |
| `corrected_identity` | The reviewer found better identifiers or a better canonical URL. | Applying the decision sets the queue item to `resolved`. |
| `not_same_publication` | The candidate identity signals point to a different publication. | Applying the decision sets the queue item to `dismissed`. |
| `unresolved` | The reviewer inspected the item but could not decide. | Saved as provenance; applying it does not close the item. |

Useful commands:

```bash
uv run marygenai review show <review_item_id_or_document_id>
uv run marygenai review decision-create <review_item_id> \
  --reviewer reviewer@example.org \
  --decision confirmed_identity \
  --rationale "PMID and DOI confirmed against PubMed."
uv run marygenai review decision-apply <review_item_id>
uv run marygenai review decision-list <review_item_id_or_document_id>
```

## PubMed Candidate Review

The `publication_candidate_review` queue contains post-legacy PubMed discoveries.
These candidates are discovered and prioritized, but they are not reviewed
knowledge yet.

Typical reviewer questions:

- Is this PubMed record already represented in the baseline/legacy data?
- Is it relevant enough to enrich?
- Does it have direct cannabinoid focus or only indirect abstract-level signal?
- Should it move forward to access enrichment, full-text retrieval, and field
  extraction?

### PubMed Identity Status

The field `publication_candidate_discovery.identity_status` classifies the
candidate against the current baseline index.

| Identity status | Meaning | Queue behavior | Reviewer action |
| --- | --- | --- | --- |
| `in_legacy_exact` | The candidate has a strong exact identifier match to the baseline, such as DOI, PMCID, PMID, or canonical identity. | Kept in audit snapshots only; it should not create a new candidate-review task. | Usually no action as a new candidate. Use it as evidence that discovery is seeing known records. |
| `possible_legacy_match` | The candidate may match baseline data, but the signal is not strong enough to merge automatically. | Enters `publication_candidate_review`. | Compare metadata and decide whether it is already covered or should proceed as a new candidate. |
| `needs_manual_identity_review` | The candidate has a weak or fuzzy legacy match that must be checked by a human before enrichment proceeds. | Enters `publication_candidate_review`. | Review first. Do not enrich as a new publication until identity is clarified. |
| `new_candidate` | No meaningful baseline match was found. | Enters `publication_candidate_review`. | Triage relevance and decide whether it should be enriched. |

`identity_status` is not the same as `review_item.status`. A candidate can have
`identity_status='needs_manual_identity_review'` and still have
`review_item.status='open'`.

Useful API endpoint for identity triage:

```text
GET /publication-candidates?identity_status=needs_manual_identity_review&limit=20
```

## Prioritization Signals

The following fields are prioritization signals, not final review decisions.

### Cannabinoid Focus

`cannabinoid_focus` is the dominant prioritization signal for MVP review.

| Value | Meaning | Suggested priority |
| --- | --- | --- |
| `direct_title_or_indexed` | The title, PubMed indexing, or high-confidence metadata directly indicates cannabinoid relevance. | Highest first-pass priority. |
| `abstract_only` | Cannabinoid relevance appears only in abstract text or weaker metadata. | Review after direct-focus candidates. |
| `no_cannabinoid_signal` | The record was returned by a broad query but has no meaningful cannabinoid signal. | Usually low priority or dismissal candidate. |

### Full-Text Review Priority

`full_text_review_priority` estimates how useful and accessible the candidate may
be for downstream enrichment.

| Value | Meaning | Suggested action |
| --- | --- | --- |
| `high_auto_full_text` | High-value candidate with likely automatic full-text access, often through PMCID. | Best starting bucket for enrichment. |
| `high_manual_full_text` | High-value candidate, but full text likely requires manual access or resolver work. | Review after high automatic candidates. |
| `medium_auto_full_text` | Medium-value candidate with likely automatic access. | Useful after high-priority buckets. |
| `medium_manual_full_text` | Medium-value candidate requiring manual access. | Defer unless topic is strategically important. |
| `low` | Lower expected enrichment value or weaker access/relevance signal. | Review later or dismiss if not relevant. |

### Study Design

`study_design` is an extracted prioritization hint. For clinical evidence, the
usual MVP priority is:

1. `meta_analysis`
2. `systematic_review`
3. `randomized_controlled_trial`
4. `controlled_clinical_trial`
5. `cohort_study`
6. `case_control`
7. `case_series`
8. `case_report`

Study design should not override cannabinoid focus. A weakly relevant
meta-analysis is still less useful than a directly relevant trial or review.

## Recommended Review Order

For the current post-legacy PubMed workflow, use this order:

1. Review `publication_candidate_review` items with
   `identity_status='needs_manual_identity_review'`.
2. Review `direct_title_or_indexed` candidates with
   `full_text_review_priority='high_auto_full_text'`.
3. Review `direct_title_or_indexed` candidates with
   `full_text_review_priority='high_manual_full_text'`.
4. Review remaining `direct_title_or_indexed` candidates by study design and
   priority score.
5. Review `abstract_only` candidates after the direct-focus backlog is under
   control.
6. Dismiss or defer `no_cannabinoid_signal` unless there is a specific reason to
   keep the item.

## What Not To Do

- Do not mark PubMed candidates as reviewed knowledge just because they were
  discovered.
- Do not merge `needs_manual_identity_review` candidates into the new-candidate
  workflow without checking the legacy match.
- Do not edit or regenerate prior Initial Load JSONL snapshots while reviewing.
- Do not commit generated `data/` or `temp/` files.
- Do not treat citation metrics as more important than `cannabinoid_focus`.

