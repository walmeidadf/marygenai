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
If a larger run has transient API timeouts, resume it by passing the prior
records file and `--retry-errors`; successful records seed the new merged index
and only previous error keys are called again.

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
The current strict evidence contract treats `evidence_text` as a quote field:
one short contiguous substring from exactly one cited unit, without ellipses or
joined passages. Any synthesis belongs in `evidence_note`. The local audit marks
`grounding_repair_needed` when a record needs a focused repair/adjudication pass.
This command also supports `--resume-records-path ... --retry-errors` so a
checkpointed run can retry transient error records without reclassifying
successful document/task/provider/model combinations.

Repair only locally failed unit-classification records:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py repair-unit-classification-batch --provider openai --records-path data/normalized/llm_study_reclassification/unit_classification/RUN_records.jsonl --semantic-index-path data/normalized/llm_study_reclassification/semantic_paragraph_index/RUN_merged_index.jsonl
```

The repair command is a narrow adjudication step, not an open-ended agent. It
loads only records marked `grounding_repair_needed`, selected document units,
and the local audit failures. It may correct evidence text/citations, downgrade
unsupported fields, and preserve legacy conflicts for human review. It writes
candidate repair records under
`data/normalized/llm_study_reclassification/unit_classification_repair/`.

Run one segment-specific unit pipeline per document:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py compare-segmented-unit-pipeline-batch --provider openai --pipeline auto --semantic-index-path data/normalized/llm_study_reclassification/semantic_paragraph_index/RUN_merged_index.jsonl --max-units 18 --document-id publication:pmcid:PMC10492088
```

This command uses the legacy English study type as a routing hint and runs one
of three contracts: `clinical_intervention`, `preclinical_mechanistic`, or
`evidence_synthesis`. It is intentionally narrower than the three-task unit
classifier: each output is a single candidate document-level record tailored to
the routed segment. The legacy English context is used as a guardrail and
alignment baseline, but not as a source unit for grounding. Source support must
come from selected document units with literal `evidence_text` quotes.

Repair only locally failed segmented-pipeline records:

```bash
uv run python pocs/llm_study_reclassification/reclassify_studies.py repair-segmented-unit-pipeline-batch --provider openai --records-path data/normalized/llm_study_reclassification/segmented_unit_pipeline/RUN_records.jsonl --semantic-index-path data/normalized/llm_study_reclassification/semantic_paragraph_index/RUN_merged_index.jsonl
```

This repair command is scoped to grounding and citation defects from segmented
pipeline records. It does not re-run open-ended extraction and does not treat
legacy context as source evidence.

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

Current local findings from the 30-document legacy-guided OpenAI POC:

- Semantic document-unit preparation stayed stable on the larger stratified
  sample: 70 windows, no API errors, and a basic paragraph-label audit pass rate
  of 1.0.
- The baseline unit classifier produced 90 records with no API errors, but 10
  unsupported evidence snippets. Most failures were evidence stitching, where
  the model joined separate source passages with ellipses.
- The stricter evidence contract reduced unsupported evidence snippets from 10
  to 4 on the same sample and same semantic index, but still produced 10 records
  marked `grounding_repair_needed` under the stricter local policy. Remaining
  failures are mostly long quote fields or residual ellipsis/omission behavior.
- Prompt changes help, but a focused repair/adjudication pass over only failed
  records is now the next comparison point before adding agentic retrieval or a
  vector/hybrid retrieval store.
- The first narrow repair/adjudication pass fixed 60% of strict grounding
  failures in both the 30-document balanced sample and the 40-document targeted
  stress sample. Remaining failures cluster around condition/cannabinoid records
  in synthetic/endocannabinoid, inflammation, animal, laboratory, and review
  contexts; these likely need a more structured segment-specific contract rather
  than a broader free-form agent.
- A first segmented pipeline run over 15 selected documents produced 15 records
  with no API or parsing errors. The initial grounding pass rate was 0.7333, with
  four records marked for repair. Three failures were quote-length policy
  violations; one was a schema/audit artifact caused by citing the legacy context
  inside `legacy_alignment`, which the contract now avoids by using
  `source_unit_ids` there. A one-document rerun of the affected preclinical case
  passed grounding after that contract fix.
- The 15-document segmented run used 71,187 OpenAI prompt tokens and 5,797
  completion tokens on `gpt-4.1`, averaging 4,746 prompt tokens, 387 completion
  tokens, and 5.6 seconds of model latency per document. At the observed size,
  this is a low-cost enough experiment to expand after quote-length repair is
  tested, but the cost still depends on selected unit count and article length.
- The first segmented repair run processed the four grounding failures from
  that 15-document run and fixed 4/4 records, with zero API/parsing errors,
  grounding pass rate 1.0, and no remaining `grounding_repair_needed` records.
  It used 22,591 OpenAI prompt tokens and 1,557 completion tokens, averaging
  5,648 prompt tokens, 389 completion tokens, and 3.7 seconds of model latency
  per repaired record. Combined with the original run, the 15-document segmented
  experiment used 93,778 prompt tokens and 7,354 completion tokens.
- A broader 30-document segmented run, balanced as 10 clinical intervention, 10
  preclinical/mechanistic, and 10 evidence-synthesis records, produced no API or
  parsing errors. Initial grounding pass rate was 0.9; the three failed records
  were repaired successfully by the segmented repair pass, leaving 30/30 final
  records passing local grounding and no remaining `grounding_repair_needed`
  records. The combined classification plus repair run used 137,636 OpenAI
  prompt tokens and 11,386 completion tokens.
- In the broader run, 16/30 final records still had `needs_human_review=true`.
  This mostly reflected insufficient or mismatched source units rather than
  unsupported quoted evidence: 6/10 evidence-synthesis records, 4/10 clinical
  intervention records, and 4/10 preclinical/mechanistic records were
  `not_found` after source-unit inspection. This is useful behavior for the POC:
  the pipeline is surfacing likely legacy/source mismatches and weak source
  extraction cases instead of forcing claims from the legacy context.

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
