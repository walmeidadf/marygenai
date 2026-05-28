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

### UI Status Filters

The review UI should filter by `review_item.status` without changing the meaning
of any other status layer. A status filter is only an operational queue filter:
it answers "which workflow tasks should I show?", not "which publications are
reviewed knowledge?"

Recommended UI behavior:

- Default to `open` items for each queue.
- Offer explicit filters for `open`, `in_review`, `resolved`, `dismissed`, and
  `all`.
- Apply the same workflow-status filter to both `legacy_identity_review` and
  `publication_candidate_review`.
- Keep PubMed candidate filters such as `identity_status`, `cannabinoid_focus`,
  and `full_text_review_priority` visually separate from workflow-status
  filters.
- Label resolved items as workflow-resolved, not fully curated or reviewed
  evidence.

Do not reuse `document.review_state`,
`publication_candidate_discovery.identity_status`, or `review_decision.decision`
as if they were queue-list status filters. They answer different questions and
should remain separate in the UI.

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

### DOI-First Identity Review

Some legacy items can be confidently identified by DOI before the reviewer has a
PMID or PMCID. This is acceptable as an intermediate review state. A DOI is often
the strongest durable identifier available from a publisher page, citation page,
or DOI resolver.

When a reviewer confirms only the DOI:

1. Set `review_item.status` to `in_review`.
2. Save or draft a structured identity decision with the DOI and, when useful,
   the canonical DOI URL.
3. Leave PMID and PMCID empty when they have not been independently confirmed.
4. Add a rationale such as: "DOI confirmed from publisher/DOI landing page.
   PMID/PMCID deferred for batch identifier resolution."
5. Do not mark the item `resolved` until the identity is sufficient for the
   current workflow or a later identifier-resolution batch has completed.

Use only the DOI value in the DOI field, without the resolver URL prefix:

```text
DOI: 10.1016/j.biopha.2020.110624
Canonical URL: https://doi.org/10.1016/j.biopha.2020.110624
```

To find or confirm a DOI manually, prefer:

- the publisher landing page;
- the DOI resolver page at `https://doi.org/<doi>`;
- PubMed article pages when the DOI is listed;
- Crossref or another public citation source when publisher metadata is unclear.

For batch completion, DOI-to-PMID should use PubMed/E-utilities or another
PubMed-backed resolver. The PMC ID Converter is useful for PMID/DOI/PMCID
crosswalks, but "Identifier not found in PMC" usually means no PMCID was found;
it does not prove that the article lacks a PMID. PMCID should remain empty when
the article is not available in PubMed Central.

After a batch resolver adds or confirms PMID/PMCID:

- keep the original DOI review rationale as provenance;
- add the resolver method, timestamp, and source to the identifier provenance;
- apply `confirmed_identity` or `corrected_identity` only when the combined
  identifiers are sufficient to close the identity task;
- keep unresolved or ambiguous DOI-only cases in `in_review` or save an
  `unresolved` decision rather than forcing `resolved`.

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

Access and full-text enrichment can run in parallel with this review order for
prioritized candidates. Keep `needs_manual_identity_review` items out of file
retrieval until identity is checked, and keep all retrieved HTML, XML, PDFs,
parsed text, and extracted fields as candidate evidence until a human review step
accepts them.

## Manual Public Document Capture During Review

Reviewers sometimes open publisher, PubMed, PMC, Europe PMC, DOI, or repository
pages while deciding whether an item is relevant or whether an identity is
correct. If the reviewer finds a public document that is useful for curation, it
can be saved as local candidate evidence, but it must not be treated as reviewed
knowledge just because a human opened or downloaded it.

Save a public HTML, XML, or PDF artifact only when all of the following are true:

- The page or file is publicly reachable without private credentials,
  institutional access, or bypassing access controls.
- The source page indicates open access, a public repository copy, PMC/Europe
  PMC availability, or another lawful public access route.
- The artifact is relevant to the item being reviewed.
- The reviewer can record enough provenance: source URL, access date, source
  name, file type, observed access/license note when available, and why it was
  saved.

Preferred order for saved artifacts:

1. PMC or Europe PMC XML when available.
2. Stable public HTML when XML is not available.
3. PDF only when the PDF is clearly public/open or is a public repository copy
   and HTML/XML is unavailable or insufficient.

Manual captures should live under ignored `data/` paths and should be persisted
as candidate-evidence provenance before they are used for extraction. They should
not be committed to Git, should not alter prior JSONL snapshots, and should not
change `document.review_state` by themselves.

Suggested reviewer workflow:

1. Set the queue item to `in_review` before manual source inspection.
2. Open source links from the UI or from the item detail.
3. Confirm whether the source is public/open enough to save.
4. Save or queue the public artifact as candidate evidence with provenance.
5. Record a review note explaining what was accessed and why it matters.
6. Create a structured identity or candidate decision separately from the saved
   artifact.

Do not save documents found only through paid access, personal accounts, private
legacy files, institutional subscriptions, or browser sessions that another
contributor could not reproduce through a public route. If a relevant document is
not publicly downloadable, record the citation, DOI, landing page, or access
barrier as review evidence instead of saving the file.

## What Not To Do

- Do not mark PubMed candidates as reviewed knowledge just because they were
  discovered.
- Do not treat downloaded full text or PDFs as reviewed knowledge.
- Do not merge `needs_manual_identity_review` candidates into the new-candidate
  workflow without checking the legacy match.
- Do not edit or regenerate prior Initial Load JSONL snapshots while reviewing.
- Do not commit generated `data/` or `temp/` files.
- Do not treat citation metrics as more important than `cannabinoid_focus`.
