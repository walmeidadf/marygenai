# LLM Study Reclassification POC

This POC prepares candidate study reclassification and extraction records for
human review. It starts from the identity-confirmed English legacy cohort,
prefers previously persisted full-text artifacts, includes legacy English
context as a guardrail, and writes auditable JSONL outputs.

For full-text studies, the runner builds a small evidence packet instead of
sending an arbitrary full-text prefix. NXML/HTML payloads are split into
deterministic section chunks, scored with a local lexical retrieval pass for
study design, sample/model, conditions, cannabinoids, dosage, comparators,
results, and safety terms, then passed to the LLM with stable `chunk_id`
markers. LLM outputs remain candidate evidence and should cite chunk ids in
`field_evidence_chunks` when supporting important fields.

The outputs are candidate evidence only. This POC does not validate identity,
does not mutate SQLite, and does not update reviewed knowledge, review queues,
review items, review decisions, or document review state.

## Run

Prepare an adaptive evidence index without calling Groq:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py prepare-evidence-index --limit 20
```

The index decides the context strategy for each candidate:

- `full_text_compact` for full texts that fit the direct prompt budget.
- `section_keyword_chunks` for larger studies that need local chunk retrieval.
- `large_section_keyword_chunks` for very large studies where embeddings may be
  useful in a later pass.
- `abstract_metadata` or `legacy_context_only` when full text is unavailable.

Explore smaller task prompts before choosing a model:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py prepare-task-packets --limit 10
```

The task sequence is:

1. `study_design_verification`
2. `population_model_sample`
3. `condition_organ_system_extraction`
4. `intervention_exposure`
5. `outcomes_safety`
6. `legacy_adjudication`

The first and last tasks are marked as `high_tier_recommended` because they are
where schema discipline and judgment against the legacy guardrail matter most.

Prepare extractive spans plus synthesis prompts before extraction:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py prepare-summary-packets --task condition_organ_system_extraction --limit 5
```

This command tests the long-document hypothesis documented in
`docs/llm_evidence_synthesis_research.md`: for large studies, first compress
retrieved chunks into short verbatim spans, then ask for a task-specific synthesis
with required `span_id` citations. The synthesis remains intermediate candidate
evidence, not reviewed knowledge.

Summary batch records include a local `span_grounding_audit` that checks whether
cited span ids exist and whether each `field_support[*].evidence_text` is a
verbatim substring of the cited spans. Failed grounding does not discard the
record; it marks the output as candidate evidence that needs human review.

If `GROQ_API_KEY` is present, run a small synthesis batch:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py run-summary-batch --task condition_organ_system_extraction --limit 3
```

Compare providers on the same deterministic evidence spans:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py compare-model-batch --task intervention_exposure --limit 5 --provider groq,openai --dry-run
uv run python pocs/llm_study_reclassification/reclassify_studies.py compare-model-batch --task condition_organ_system_extraction --limit 5 --provider groq,openai --dry-run
```

The model comparison commands support `groq`, `openai`, `anthropic`, and
`cerebras` through direct HTTP calls with keys loaded from the environment or
`.env`:

- `GROQ_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `CEREBRAS_API_KEY`

The default models are `llama-3.3-70b-versatile` for Groq, `gpt-4.1` for
OpenAI, `claude-3-5-sonnet-latest` for Anthropic, and `gpt-oss-120b` for
Cerebras. Use `--model` when running one provider, or
`--model-overrides openai:gpt-4.1-mini,cerebras:MODEL_NAME` for a multi-provider
run.

The comparison command currently accepts these high-judgment extraction tasks:

- `intervention_exposure`
- `condition_organ_system_extraction`
- `study_design_verification`

It writes normalized candidate evidence and per-run summary JSON under:

- `data/normalized/llm_study_reclassification/model_comparison/`
- `data/raw/llm_study_reclassification/`

Each record preserves `document_id`, `task_name`, provider, model, prompt
version, selected span ids, selected chunk ids, source artifact ids/paths,
legacy context id, rough prompt size, latency when available, and local grounding
audit metrics. Previous non-dry-run records are skipped by
document/task/provider/model unless `--retry-errors` is used.

Prepare a semantic document-unit index from literal cleaned article text:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py compare-semantic-paragraph-index --provider openai --document-id publication:url:05c015f9550941da --window-paragraphs 10 --overlap-paragraphs 2 --max-windows-per-document 3
```

This command does not paraphrase the article and does not send raw HTML to the
model. It removes obvious boilerplate, maps cleaned paragraphs, abstract text,
table text, and figure captions into short ids such as `p0001`, classifies
overlapping windows, audits ids and labels, then writes a merged candidate index
under `data/normalized/llm_study_reclassification/semantic_paragraph_index/`.
Tables and figure captions are mapped only as text units for future enrichment;
the POC does not interpret images, plots, or graphical content visually. The
labels are candidate retrieval metadata only, not reviewed knowledge.
Run summaries include preparation throughput metrics by provider/model: prompt
characters, rough input tokens, output size when a model was called, latency,
records with errors, and paragraph-label audit pass rates.

Window size is intentionally empirical. Current runs should monitor audit pass
rate, evidence-term support, downstream extraction quality against the legacy
English guardrail, latency, and human review burden before choosing a default
chunk size. Robust large-context models are the preferred first-pass preparation
tools in this experiment; Groq and Cerebras remain useful candidates for later,
more specific or final classification steps after context has been narrowed.

Classify study-level task families from selected document units:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py compare-unit-classification-batch --provider openai --task all --document-id publication:url:05c015f9550941da --max-units 18
```

This command tests the next pipeline stage after semantic indexing. It selects
literal document units for `condition_classification`,
`cannabinoid_classification`, and `study_classification`, optionally using a
merged semantic index as retrieval hints. The model must cite `unit_id`s and
short verbatim evidence text. Outputs are written under
`data/normalized/llm_study_reclassification/unit_classification/`; prompt
previews and raw responses are written under
`data/raw/llm_study_reclassification/`. These records remain candidate evidence
for human review and do not update reviewed knowledge.
Run summaries include classification throughput metrics by task/provider/model:
prompt characters, rough input tokens, output size when available, latency,
grounding pass rates, unsupported evidence counts, records with errors, and
`needs_human_review` counts.

Current local findings from the 4-document OpenAI POC:

- Semantic document units plus task-family classification looked more useful
  than narrative synthesis for the next pipeline branch.
- Requiring each `evidence_text` to be one contiguous verbatim substring from one
  cited unit eliminated grounding failures caused by ellipsis-joined evidence in
  the small test.
- The classifier surfaced likely legacy/source mismatches when selected article
  units did not support cannabinoid claims from the legacy context.
- The next run should use a larger stratified sample and record preparation,
  classification, latency, rough token, and optional embedding metrics before
  deciding whether to add ChromaDB or Qdrant-style hybrid retrieval.

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py run --dry-run --limit 5
```

If `GROQ_API_KEY` is present in the environment or `.env`, the same command
without `--dry-run` calls Groq:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py run --limit 5
```

Outputs are written under ignored paths:

- `data/normalized/llm_study_reclassification/`
- `data/raw/llm_study_reclassification/`

## Research Notes

The synthesis/chunking research notes live in
`docs/llm_evidence_synthesis_research.md`. The prioritized POC sequence is:

1. Direct narrow-task chunks as the baseline.
2. Extractive compression into auditable spans.
3. Task-specific synthesis with span citations.
4. Entity-first extraction if synthesis still over-infers.
5. High-tier model adjudication for hard conflicts only.
