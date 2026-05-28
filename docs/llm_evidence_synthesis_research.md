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

### P5: Graph Or Relation Intermediate

Represent candidate entities and relations as a graph-like intermediate:
compound, target/receptor, condition, model/population, route, dose, comparator,
outcome, and adverse event. This may help future review and retrieval, but it is
too heavy before the extraction contract is more stable.

Priority: defer.

## Recommended POC Sequence

1. Keep `prepare-evidence-index` as the retrieval baseline.
2. Add `prepare-summary-packets` to create extractive spans and synthesis
   prompts without calling an LLM.
3. Run `run-summary-batch` on one narrow task, starting with
   `condition_organ_system_extraction` or `intervention_exposure`.
4. Compare summary outputs against the direct `run-task-batch` outputs for the
   same documents.
5. Only then test a high-tier model on adjudication or extraction.

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
