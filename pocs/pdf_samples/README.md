# PDF Samples POC

Goal: test a small full-text and PDF sample set to measure extraction value,
access difficulty, and future processing-stack needs.

This POC is intentionally small. It does not create a broad PDF pipeline and does
not crawl publisher sites. It fetches only the records listed in
`sample_manifest.json`.

## Run

```bash
uv run python pocs/pdf_samples/sample_full_text.py run
```

Optional LLM-assisted extraction can be tested after a local or remote provider is
configured:

```bash
uv run python pocs/pdf_samples/sample_full_text.py run \
  --llm-provider ollama \
  --llm-model llama3.1:8b
```

or:

```bash
uv run python pocs/pdf_samples/sample_full_text.py run \
  --llm-provider groq \
  --llm-model llama-3.1-8b-instant \
  --source-record-id 164
```

Environment:

- `OLLAMA_BASE_URL` defaults to `http://localhost:11434` when `--llm-provider
  ollama` is used.
- `GROQ_API_KEY` is required when `--llm-provider groq` is used.

Use `--source-record-id` or `--limit` for LLM tests. Full-manifest LLM runs are
too slow locally and can hit remote rate limits.

POC 6b uses the already saved text samples and does not refetch source documents:

```bash
uv run python pocs/pdf_samples/extract_evidence.py run \
  --source-record-id 340 \
  --source-record-id 164 \
  --source-record-id 43
```

Provider comparisons can be added one at a time:

```bash
uv run python pocs/pdf_samples/extract_evidence.py run \
  --source-record-id 340 \
  --source-record-id 164 \
  --source-record-id 43 \
  --provider groq \
  --groq-model llama-3.1-8b-instant \
  --prompt-max-chars 3500 \
  --delay-seconds 12
```

OpenRouter free models can be tested through either the router or an explicit free
model id:

```bash
uv run python pocs/pdf_samples/extract_evidence.py run \
  --source-record-id 164 \
  --provider openrouter \
  --openrouter-model openrouter/free \
  --prompt-max-chars 3500
```

POC 6c keeps the same runner but writes review-ready rows and uses field-specific
section ranking before remote provider calls:

```bash
uv run python pocs/pdf_samples/extract_evidence.py run \
  --source-record-id 340 \
  --source-record-id 164 \
  --source-record-id 43
```

## Inputs

- `pocs/pdf_samples/sample_manifest.json`: fixed 10-record mixed sample selected
  from link resolver and access enrichment outputs.

Sample categories:

- 4 direct PMC HTML records;
- 4 Europe PMC HTML/PDF candidates, with fallback to Europe PMC full-text XML or
  PMC HTML when Europe PMC rendered HTML is not useful;
- 2 Unpaywall PDF candidates.

## Outputs

- `data/raw/pdf_samples/*`: raw HTML, XML, and selected supplemental PDFs;
- `data/processed/pdf_samples/*`: extracted text samples;
- `data/normalized/pdf_samples/*_pdf_sample_records.jsonl`: field-level
  extraction candidates;
- `data/normalized/pdf_samples/*_pdf_sample_summary.json`: run summary.
- `data/normalized/pdf_samples/*_poc6b_evidence_records.jsonl`: POC 6b
  normalized candidate evidence records;
- `data/normalized/pdf_samples/*_poc6b_evidence_summary.json`: POC 6b comparison
  summary.
- `data/normalized/pdf_samples/*_poc6c_evidence_records.jsonl`: POC 6c
  section-ranked normalized candidate evidence records;
- `data/normalized/pdf_samples/*_poc6c_review_export.jsonl`: field-level rows for
  human review, with review provenance placeholders;
- `data/normalized/pdf_samples/*_poc6c_evidence_summary.json`: POC 6c comparison
  and review-export summary.

Every field extraction is marked `needs_review`. The heuristic extractor is a
candidate finder, not a source of reviewed truth.

## Current Completed Run

Run id: `20260513T215843Z`

Command:

```bash
uv run python pocs/pdf_samples/sample_full_text.py run
```

Result:

| Metric | Count |
| --- | ---: |
| Sample records | 10 |
| Selected HTML sources | 8 |
| Selected XML sources | 1 |
| Records without usable text | 1 |
| Supplemental PDFs downloaded | 1 |
| Records with errors or fallbacks | 5 |
| Field extraction candidates | 58 |
| Fields requiring human review | 58 |

Fields with at least one evidence candidate:

| Field | Records |
| --- | ---: |
| route of administration | 9 |
| adverse events | 8 |
| population details | 8 |
| dosage | 7 |
| study design | 7 |
| treatment duration | 6 |
| protocol/intervention details | 5 |
| arms/comparators/control groups | 2 |

## Learnings

- HTML or XML should be preferred over PDF for extraction. Direct PMC HTML worked
  well for the four PMC records.
- Europe PMC rendered article pages are not reliable fetch targets for this use
  case. They returned JavaScript-dependent pages with only a short browser warning
  in this run. Europe PMC full-text XML worked for one record, while PMC HTML was
  the useful fallback for the other Europe PMC candidates with `PMCID`.
- Unpaywall PDF candidates are useful for access discovery, but publisher-hosted
  PDFs may still block automated access. One Wiley candidate returned 403 for both
  DOI landing and PDF URLs.
- DOI landing pages can sometimes provide useful HTML before PDF parsing is
  needed. The LWW pain overview produced useful HTML and its Unpaywall PDF
  candidate was saved as a supplemental artifact.
- Keyword extraction is useful for surfacing candidate evidence, but it is too
  noisy for final normalized fields. It can confuse neighboring evidence,
  especially for route, adverse events, and study design. LLM-assisted extraction
  should be tested next against the same text samples.
- Local `qwen3:8b` through Ollama was fast enough to produce several outputs, but
  it did not reliably follow strict JSON instructions on long article contexts.
  It is better suited for a first extraction/summarization pass than for final
  schema-conformant output.
- Groq produced higher-quality structured JSON in a single-record test, but the
  free tier hit `429 Too Many Requests` when multiple records were sent back to
  back. Groq tests should run one record at a time or with a delay.
- Human review remains mandatory. This POC produced candidate evidence with
  provenance, confidence, and review state, but no field should enter the knowledge
  base as reviewed without HITL validation.

## POC 6b Current Run

POC 6b added strict Pydantic models for candidate snippets and normalized evidence
fields, plus a runner that reads `data/processed/pdf_samples` and supports
`--source-record-id`.

Primary comparison:

- run id: `20260513T230004Z`;
- records: `340`, `164`, `43`;
- providers: heuristic baseline and Groq `llama-3.1-8b-instant`;
- prompt size: 3,500 selected section characters per record;
- delay: 12 seconds between calls;
- normalized fields: 40;
- provider errors: 0;
- review state: 40 / 40 fields marked `needs_review`.

Observed provider behavior:

- heuristic baseline is fast and reproducible, but still chooses neighboring
  evidence for some fields, especially route, population, adverse events, and
  study design;
- Ollama `qwen3:8b` produced useful candidates for record `164`, but returned
  non-object JSON for records `340` and `43`;
- Groq produced parseable JSON for all three target records when prompts were
  section-selected and delayed; the returned headers showed token limits were the
  binding constraint, with remaining tokens reaching `0` on the third call;
- OpenRouter `openrouter/free` produced parseable candidates for record `164`,
  but was slower than Groq in this run;
- OpenRouter explicit free model `openai/gpt-oss-20b:free` returned truncated JSON
  for record `164`, and `qwen/qwen3-coder:free` hit `429 Too Many Requests`.

The useful architecture is therefore two-stage and defensive: LLMs may prefill
candidate evidence, but Pydantic validation decides what enters normalized POC
outputs, and every accepted field remains a human-review item.

## Next Improvements

- Add an explicit PDF text parser only after HTML/XML extraction gaps are better
  understood.
- Compare the POC 6c review export with a real reviewer workflow before choosing
  Label Studio, spreadsheet review, or a custom review UI.
- Add section-aware table extraction for dosage, arms, and adverse events.
- Expand to the remaining saved POC 6 records only after the review export shape
  proves ergonomic.
