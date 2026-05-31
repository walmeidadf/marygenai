# LLM Evidence Synthesis Research Notes

These notes support the `llm_study_reclassification` POC and future experiments
around long scientific articles, chunking, synthesis, and structured extraction.
The project boundary remains unchanged: outputs are candidate evidence for human
review, not medical advice or reviewed knowledge.

## Question

For long cannabinoid studies, should the pipeline send selected original chunks
directly to an extraction model, or should it first build a short task-specific
evidence synthesis and then extract structured fields from that synthesis?

The working hypothesis is that longer source text can support better synthesis,
and a well-cited synthesis can make downstream structured extraction more
reliable. The risk is that free-form synthesis can erase uncertainty, introduce
unsupported facts, or make conflicts with the legacy English context harder to
audit.

## Reviewed Approaches

- Contextual compression in retrieval systems: retrieve broadly, then compress
  retrieved context before generation. LangChain documents this as a way to
  reduce irrelevant context while preserving source grounding.
- Document-summary retrieval: LlamaIndex provides document-summary indexes that
  summarize documents for retrieval and then use the underlying nodes for
  detailed access.
- Long-document refinement: LongRefiner proposes coarse-to-fine selection for
  long context, ranking and refining evidence before generation.
- Hierarchical chunk merging: context-aware hierarchical merging methods try to
  preserve local and global document structure instead of treating chunks as
  isolated fragments.
- Entity-based summarization: entity-centric approaches preserve salient entities
  and relationships during long-document summarization, which is relevant for
  cannabinoids, conditions, organs, receptors, route, dosage, and adverse events.
- Extract-then-evaluate methods for long summaries: work on summary evaluation
  shows that focused extraction before judgment can be more reliable than asking
  a model to reason over an entire long document in one pass.
- Grounded extraction from documents: document extraction systems such as LMDX
  emphasize grounding extracted fields in source text spans.
- GraphRAG and graph-style intermediate representations: graph approaches can be
  useful after entities and relations are stable, but they are heavier than the
  current POC needs.

## Hypotheses To Prioritize

### P0: Direct Narrow-Task Chunks

Use deterministic chunking plus task-specific retrieval, then ask the model to
extract one narrow task. This is the current baseline. It is cheap, auditable,
and keeps original text in the prompt. It can still fail when the selected chunks
contain too much context or when the task is semantically broad.

Priority: keep as the baseline for every comparison.

### P1: Extractive Compression Before Extraction

Select short verbatim spans from retrieved chunks before any LLM call. Use spans
as the atomic evidence units for synthesis and extraction. This reduces prompt
size while preserving auditability because every downstream claim can cite a
`span_id` and the original `chunk_id`.

Priority: first new POC layer. Low risk and useful even if synthesis fails.

### P2: Task-Specific Synthesis With Span Citations

Ask an LLM to produce a short synthesis for a single task, using only extractive
spans and requiring `span_id` citations for every claim. The synthesis should
include missing evidence, source limitations, and legacy alignment notes. The
downstream extraction step can then consume the synthesis plus cited spans rather
than a larger chunk packet.

Priority: first Groq experiment for the current hypothesis.

### P3: Entity-First Then Synthesis

Extract candidate entities first, such as cannabinoids, conditions, organ
systems, dosage, routes, receptors, comparators, species, and sample sizes. Then
summarize evidence around those entities. This may reduce generic clinical
inference, especially for studies where cannabis is background context rather
than the intervention or primary exposure.

Priority: next if P2 improves faithfulness but still over-infers entities.

### P4: High-Tier Adjudication Only

Use a higher-tier model for the hardest judgment tasks: study-design changes,
legacy conflicts, and final adjudication. Use cheaper models or deterministic
steps for retrieval, compression, and low-risk extraction candidates.

Priority: evaluate after the P1/P2 prompt shape is stable. A stronger model
should improve judgment, but it should not compensate for a vague task.

### P4a: High-Tier Extraction Comparison

Compare stronger hosted models on the same extractive spans before reserving
them only for final adjudication. This tests whether model capability improves
complex extraction tasks where role and context matter: cannabinoid as
intervention versus exposure versus population/background context, conservative
condition and organ-system extraction, and study-design verification against the
legacy English guardrail.

The comparison must keep the document sample, selected chunks, selected spans,
prompt version, and legacy context fixed across providers. Outputs remain
candidate evidence only and are evaluated with local grounding checks, error
counts, latency, unsupported evidence text counts, not-found/insufficient
evidence counts, and human-review flags.

Priority: run as a small side-by-side experiment after P2 packet generation, not
as a replacement for human review.

### P5: Graph Or Relation Intermediate

Represent candidate entities and relations as a graph-like intermediate:
compound, target/receptor, condition, model/population, route, dose, comparator,
outcome, and adverse event. This may help future review and retrieval, but it is
too heavy before the extraction contract is more stable.

Priority: defer.

### P6: Semantic Document Units Before Task Classification

The most promising recent POC path is not free-form synthesis. It is a two-stage
audit pipeline:

1. Convert source artifacts into literal cleaned document units: paragraphs,
   abstract text, tables, and figure captions.
2. Classify those units with short stable ids and candidate semantic labels.
3. Retrieve task-specific units for downstream classification.
4. Ask a robust model to classify one task family at a time, citing `unit_id`s
   and short verbatim evidence text.

This keeps the article text visible to the model without asking it to rewrite or
summarize the article. It also preserves reviewability because downstream
outputs cite the same unit ids that a human can inspect. The labels are retrieval
hints only, not truth.

In the 4-document OpenAI test set, the unit-classification stage produced 12
records across `condition_classification`, `cannabinoid_classification`, and
`study_classification` with no API errors. The first full run showed that the
model sometimes built `evidence_text` from multiple passages joined by ellipses,
which failed literal grounding. After the prompt required each `evidence_text`
to be one contiguous substring from one cited unit, grounding pass rate reached
1.0 for all three task families in the small sample.

Qualitative findings:

- The pipeline correctly surfaced likely legacy/source mismatches where selected
  article units did not mention cannabinoids despite cannabinoid claims in the
  legacy context.
- Study classification needed explicit guidance that randomized, controlled,
  double-blind, and open-label intervention trials are `human_clinical`, not
  `human_observational`.
- Legacy alignment needed an explicit rule: when the note says source units and
  legacy context describe different studies, populations, interventions, or
  conditions, `legacy_alignment.alignment` must be `conflicts`.
- The approach looks more useful than narrative synthesis for this stage because
  it narrows context while keeping original text and audit ids intact.

Priority: expand the same test to a larger, stratified document sample before
building a heavier retrieval store.

### P7: Hybrid Retrieval Store For Document Units

A vector or hybrid retrieval layer may help once the document-unit approach is
stable. The first local POC should prefer ChromaDB because it is lightweight for
experimentation; Qdrant remains a better candidate if the workflow needs a more
durable service with hybrid search and operational controls.

The store should contain only candidate preparation artifacts, not reviewed
knowledge. Each indexed unit should preserve `document_id`, `unit_id`,
`unit_type`, section, source artifact id/path, prompt version, candidate labels,
and literal text hash. Retrieval should be evaluated against deterministic
keyword/label selection before becoming part of the default classification path.

Embeddings can use an open model in this phase. The goal is not maximal semantic
recall yet; it is to estimate whether hybrid retrieval improves task-specific
unit selection enough to justify added complexity.

Priority: test after a larger document-unit classification run establishes
failure modes of deterministic unit selection.

### P8: Cost And Throughput Instrumentation

The next expansion should measure preparation and classification costs
separately:

- document-unit preparation count, prompt chars, rough token estimates, latency,
  and model/provider;
- unit-classification prompt chars, output size, latency, grounding pass rate,
  unsupported evidence count, and human-review flags;
- optional embedding count, embedding dimensions, embedding model, estimated
  embedding cost, and retrieval latency;
- task-level counts by provider/model and task family.

This does not need exact billing integration initially. Rough token/input-char
counts plus provider/model latency are enough to estimate scaling behavior and
compare robust-model preparation against cheaper narrow-task models later.

Priority: add before running a larger sample so the larger run is informative.

## Recommended POC Sequence

1. Keep `prepare-evidence-index` as the retrieval baseline.
2. Add `prepare-summary-packets` to create extractive spans and synthesis
   prompts without calling an LLM.
3. Run `run-summary-batch` on one narrow task, starting with
   `condition_organ_system_extraction` or `intervention_exposure`.
4. Compare summary outputs against the direct `run-task-batch` outputs for the
   same documents.
5. Run `compare-model-batch` for `intervention_exposure`,
   `condition_organ_system_extraction`, and `study_design_verification` on the
   same summary packets.
6. Use semantic document units as the current preferred branch for the next
   experiment: expand to a larger stratified sample, run preparation and
   task-family classification, and compare against legacy guardrails.
7. Add cost/throughput instrumentation before the larger run.
8. Test ChromaDB or Qdrant-style hybrid retrieval only after deterministic
   unit selection failure modes are visible.
9. Only then test a high-tier model on final adjudication.

## Evaluation Criteria

- Every synthesized claim cites at least one span.
- Cited spans preserve original `chunk_id`, artifact id, and artifact path.
- The synthesis explicitly marks missing evidence instead of filling gaps.
- Legacy English context is used as a guardrail and comparison baseline, not as
  absolute truth.
- Conflicts between source spans and legacy context are preserved for human
  review.
- The downstream extraction result has fewer unsupported conditions, organ
  systems, routes, doses, cannabinoids, and comparators than direct chunk
  extraction.

## References

- LangChain contextual compression:
  <https://www.langchain.com/blog/improving-document-retrieval-with-contextual-compression>
- LlamaIndex `DocumentSummaryIndex`:
  <https://docs.llamaindex.ai/en/latest/api_reference/indices/document_summary/>
- LongRefiner:
  <https://arxiv.org/abs/2505.10413>
- Context-Aware Hierarchical Merging for retrieval:
  <https://aclanthology.org/2025.findings-acl.289/>
- Entity-based long document summarization:
  <https://www.ideals.illinois.edu/items/131761>
- Less is More for long-document summary evaluation:
  <https://arxiv.org/abs/2309.07382>
- LMDX grounded document extraction:
  <https://arxiv.org/abs/2309.10952>
- Microsoft GraphRAG:
  <https://www.microsoft.com/en-us/research/project/graphrag/>
