# Roadmap

## Product Direction

MaryGenAI is building a continuously refreshed, inspectable, and eventually
human-reviewed scientific source-intelligence layer for cannabinoid medicine.
Physicians and researchers should be able to find candidate studies, understand
why they matched, inspect evidence and provenance, and open the original source.

The deployed read-only MCP pilot proves the first candidate-retrieval surface.
The next cycle must improve freshness, visibility, and curation readiness
without making the availability of external reviewers the critical path.

Candidate data and reviewed knowledge remain separate product layers:

```text
public discovery and lawful source acquisition
  -> source-quality validation
  -> AI-classified candidate evidence
  -> immutable candidate index, MCP, and Dataset Viewer
  -> independent human review when curators are available
  -> reviewed snapshot
```

## Now: Candidate-Data Growth And Product Readiness

### PubMed 2024+ Vertical Slice — First Expansion Complete

The first controlled expansion delivered a provider-free source-quality rollup,
an eight-document smoke canary, and three non-overlapping corrected-PMC slices.
The v2-v4 slices produced 291 strict-valid classifications. A
provenance-recorded inclusion gate removed three records with no structured
cannabinoid or exposure label, leaving 288 candidates. Local regression and
authenticated remote MCP tests passed before those candidates were combined
with the 3,149-record strict corpus and promoted as an immutable 3,437-record
private AWS snapshot.

The next expansion must start from explicit exclusions for every frozen prior
slice, preserve source and medical-scope gates, run only one provider Batch
sub-batch at a time unless limits are reconfirmed, and repeat the same technical,
grounding, provenance, cost, and retrieval regressions before promotion.

Human review is not required to create candidate records. New records must stay
`ai_classified_candidate` and `needs_review` until an explicit review workflow
promotes them.

### Dataset Viewer — Implemented, Exposure Controlled

The implemented read-only Viewer reuses the retrieval contract and supports:

- paginated table and text search;
- filters for condition, cannabinoid, study design, population, outcome, year,
  source readiness, confidence, and review state;
- visible candidate versus reviewed trust labels;
- study detail with identity, evidence, uncertainty, provenance, and preferred
  source links;
- snapshot version and documented limitations;
- no local paths, private legacy context, credentials, or protected review
  state.

The first Viewer may remain private or access-controlled. Public download and
dataset publication require an explicit data license and source-distribution
boundary.

### Public Website — Implemented

The website is oriented to physicians, professors, students, and research
partners. It explains:

- the literature-discovery problem;
- the implemented candidate dataset and MCP pilot;
- the discovery, source, classification, and review flow;
- the distinction between AI-classified candidates and reviewed knowledge;
- how universities and students can participate in curation;
- current dataset counts, limitations, and provenance;
- links to the Viewer, MCP information, documentation, and GitHub repository.

The website must describe implemented capabilities accurately and must not
claim that the candidate dataset is already human-reviewed or openly licensed.

## Parallel: Curation Readiness

Prepare the complete curation workflow while university participation is being
organized:

1. Freeze the minimum pilot field set and decision semantics.
2. Run a bounded annotation-tool integration spike.
3. Keep MaryGenAI as the system of record; external tools are task and response
   surfaces, not the authoritative reviewed store.
4. Build versioned export and validated import adapters.
5. Prepare reviewer guidelines, examples, training tasks, calibration tasks,
   and the first production package.
6. Define reviewer identity, institution, task assignment, draft/submitted
   state, double-review sampling, adjudication, and withdrawal rules.
7. Reject imports whose document identity, source hash, schema, or task version
   no longer matches the frozen task package.
8. Prevent automatic promotion from annotation response to reviewed knowledge.

When curators become available, activation should require onboarding and
calibration rather than new product design or infrastructure work.

## Next: Targeted Legacy Recovery

Treat legacy identity and source availability as separate backlogs.

### Identity

1. Generate deterministic or high-confidence identifier suggestions from PMID,
   PMCID, DOI, publisher identifiers, normalized title, and year.
2. Preserve every candidate value and source in provenance.
3. Apply only deterministic technical normalization automatically.
4. Send conflicts, ambiguous matches, and insufficient evidence to human review.
5. Use identity tasks as a bounded reviewer-onboarding track when useful.

### Source Recovery

1. Re-run bounded official PMC failure samples first.
2. Audit short-text artifacts before changing any quality threshold.
3. Try alternate official or lawful routes for high-value records.
4. Treat OCR and poor PDF text layers as a separate specialized campaign.
5. Defer blocked publisher routes unless physician questions demonstrate a
   specific coverage need.
6. Stop low-yield routes after a measured pilot rather than accumulating an
   unbounded historical obligation.

Recovery priority should follow physician-relevant coverage gaps and measured
source-ready yield, not only the number of outstanding records.

## Later: Reviewed And Licensed Public Baseline

1. Activate trained curators and run the first production review package.
2. Measure completion time, field-level agreement, abstention, correction, and
   adjudication burden.
3. Create append-only reviewed decisions with reviewer and source provenance.
4. Define the threshold for a record or field to enter a reviewed snapshot.
5. Select explicit software and data licenses and document source-distribution
   restrictions.
6. Publish a versioned baseline with a dataset card, schema, limitations,
   provenance, and Viewer.
7. Keep candidate and reviewed releases independently identifiable.

## Continuous Product Evaluation

Across all phases:

- collect realistic, non-identifying physician questions;
- preserve a repeatable retrieval acceptance benchmark;
- measure useful results, false positives, suspected false exclusions, source
  opening, safe wording, and missing filters;
- use observed value to prioritize enrichment and ranking changes;
- never treat retrieval rank or confidence as clinical evidence strength;
- never place patient-identifying data in the system.

## Achieved Gates

The completed 3,149-document campaign, qualified 288-record PubMed extension,
and deployed 3,437-record MCP snapshot demonstrated:

- resumable, provenance-complete candidate classification;
- strict schema validation and deterministic technical repair;
- evidence-backed candidate records and explicit uncertainty;
- an isolated read-only retrieval index;
- useful structured filters, source links, study detail, facets, and
  capabilities;
- hosted MCP access without exposing review state or provider tools;
- snapshot-only promotion that preserved every legacy candidate row and kept
  all records at `ai_classified_candidate` and `needs_review`.

These gates support continued candidate-data work. They do not establish a
human-reviewed public dataset.
