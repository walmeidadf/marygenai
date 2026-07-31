# Official Workflows

The supported public interface is the `marygenai` package CLI. Commands in
historical experiments are not public APIs.

## Setup

```bash
uv sync --extra dev
uv run marygenai info
uv run marygenai --help
```

Configuration belongs in an ignored `.env` file. Never commit credentials,
generated data, raw source payloads, PDFs, or private legacy exports.

## Read-Only Retrieval And MCP Workflow

Build the isolated candidate index from all twenty-four completed strict-corpus
runs, the classification corpus, and their latest evaluation reports:

```bash
uv run marygenai retrieval build-index
```

Inspect build provenance, limitations, capabilities, and top facets:

```bash
uv run marygenai retrieval inspect-index
```

Export explicit projected-identity conflicts to an ignored manual-adjudication
CSV without applying decisions or mutating SQLite:

```bash
uv run marygenai retrieval export-identity-conflicts \
  --classification-run-id <classification_run_id>
```

The export writes one row per conflicting identifier, candidate values and
provenance, plus empty `decision_status`, `selected_value`,
`decision_rationale`, `reviewer`, and `reviewed_at` columns. Supported decision
status values are recorded in the adjacent summary JSON. Applying decisions is
a separate workflow and requires explicit authorization.

Run a local search through the same query service used by MCP:

```bash
uv run marygenai retrieval search \
  --condition "Dravet syndrome" \
  --cannabinoid Cannabidiol \
  --population pediatric_humans \
  --outcome-domain efficacy \
  --outcome-domain safety
```

Serve the closed local index to an MCP host over stdio:

```bash
uv run marygenai mcp serve
```

Generate a temporary pilot token and serve the same tools over local stateless
Streamable HTTP:

```bash
uv run marygenai mcp generate-access-token \
  --output-path data/private/mcp-dev-access-token.json
export MARYGENAI_MCP_BEARER_TOKEN_SHA256=<reported_sha256>
uv run marygenai mcp serve-http
```

The plaintext token must remain outside repository files and logs. HTTP
authentication prefers the `Authorization: Bearer` header. Query credentials
remain disabled locally unless `--allow-query-token` is explicit. The optional
output file is ignored, created with mode `0600`, and never overwritten.

Build the Linux deployment ZIP without embedding the candidate index:

```bash
uv run marygenai deployment build-lambda
```

Prepare the Terraform dev environment:

```bash
cd infra/terraform
terraform init
terraform fmt -check
terraform validate
terraform plan
```

Terraform uploads the ignored DuckDB and manifest to a private versioned S3
bucket under content-addressed keys. Lambda verifies the DuckDB SHA-256, copies
it to `/tmp`, and opens it with `read_only=True`. Review a saved plan before any
apply. The infrastructure does not use CloudFormation. The custom domain uses an
ACM certificate with external Cloudflare DNS validation; follow the two-stage
bootstrap in `infra/terraform/README.md` before creating the application CNAME.

The AWS dev environment sets `allow_query_token=true` for compatibility with
the maintainer's current Claude and ChatGPT connector dialogs. Use
`https://mcp-server.marygenai.com/mcp?key=<pilot-token>` with empty Claude OAuth
fields or ChatGPT `No Auth`. The server still verifies the key; the platform
label only means there is no platform-managed OAuth handshake. Treat the entire
URL as a secret. Prefer `Authorization: Bearer <pilot-token>` when a client can
configure fixed request headers.

The generated DuckDB index and manifest remain ignored under
`data/normalized/retrieval_indexes/`. Build and runtime do not open or mutate
MaryGenAI SQLite, review queues, review decisions, or reviewed knowledge. The
runtime opens DuckDB with `read_only=True` and exposes no provider or network
tool. See `docs/mcp_retrieval_contract.md` for the contract and
`docs/mcp_clinical_retrieval_research.md` for clinical acceptance questions and
the future backlog.

## Public Source Workflow

Initialize local operational storage:

```bash
uv run marygenai db init
```

Discover PubMed candidates for an explicit window:

```bash
uv run marygenai pubmed-discovery run \
  --datetype pdat \
  --mindate 2024/01/01 \
  --maxdate 2024/01/31 \
  --retmax 100
```

Run month-by-month discovery:

```bash
uv run python scripts/pubmed_monthly_backfill.py \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --retmax 200
```

Enrich prioritized candidates and audit locally persisted artifacts:

```bash
uv run marygenai access-enrichment run --limit 50
uv run marygenai access-enrichment audit-artifacts
```

The enrichment command may write artifacts and operational candidate state as
documented by the command. Classification and corpus commands must not mutate
SQLite or review state.

## Classification Workflow

Build a deduplicated corpus and stratified sample:

```bash
uv run marygenai classification-corpus rollup --sample-size 30
```

Inspect prompt packets without calling a model:

```bash
uv run marygenai classification build-prompt-packets \
  --limit 5 \
  --max-source-chars 6000 \
  --target-model-provider openai \
  --target-model-name gpt-5.4-mini
```

Validate the schema with deterministic mock output:

```bash
uv run marygenai classification run-smoke --limit 5
```

Profile the actual downloaded corpus and prepare a small v4 retrieval-field
validation sample without calling a model:

```bash
uv run marygenai classification profile-retrieval-fields --sample-size 12
```

The report distinguishes downloaded, source-ready, strict, and broader records.
It uses normalized English legacy context only as a comparison guardrail and
writes ignored artifacts under `data/normalized/classification_evaluations/`.

Run the deterministic metadata/parser baseline on the frozen worklist:

```bash
uv run marygenai classification extract-retrieval-metadata \
  --input-path <retrieval_field_validation_sample.jsonl>
```

This command generates source-backed candidates for sample size and scope,
route, country mentions, population/species, and explicit study-design signals.
It does not treat regex matches as reviewed values, call an LLM, or mutate
SQLite.

Build the same-document broad-v4 versus selective field-family comparison:

```bash
uv run marygenai classification build-v4-comparison-packets \
  --sample-path <retrieval_field_validation_sample.jsonl> \
  --parser-records-path <retrieval_metadata_parser_records.jsonl> \
  --limit 8 \
  --target-model-provider openai \
  --target-model-name gpt-5.4-mini
```

This local-only command writes versioned prompt packets, field-routing records,
schema-valid mocks, assembled mock candidate records, and an efficiency report
under `data/normalized/classification_evaluations/`.
Token counts use the declared `chars_divided_by_4.v1` heuristic. Cost projections
use configurable input and output rates and maximum completion limits; they are
not provider usage or billing records. No provider call is available through
this command.

Selective packets request only fields routed as
`semantic_resolution_required`. Other fields remain visibly
`insufficient_evidence`, `not_applicable`, or deterministically resolved. The
semantic response schema contains only field decisions, evidence IDs,
categorical confidence, and uncertainty; identity and provenance are assembled
locally.

Without `--manifest-path`, the command deterministically balances direct-signal
source strategies and includes metadata-only and no-signal contrasts. It writes
the selected documents to a frozen JSONL manifest. Pass that artifact back
through `--manifest-path` so later broad and selective executions use exactly
the same documents regardless of input ordering.

Build a deterministic study-design benchmark candidate set:

```bash
uv run marygenai classification build-validation-benchmark \
  --sample-size 48 \
  --input-path <classification_corpus_records.jsonl>
```

The command uses explicit document-title evidence, stratifies by design rule,
preserves normalized English legacy comparison and source provenance, and writes
ignored JSONL and summary artifacts under
`data/normalized/classification_evaluations/`. Every row remains
`needs_review`; the output is not reviewed ground truth and the command does not
call an LLM or mutate SQLite.

Evaluate reviewed benchmark decisions:

```bash
uv run marygenai classification evaluate-validation-benchmark \
  --candidates-path <study_design_benchmark_candidates.jsonl> \
  --decisions-path <study_design_benchmark_review_decisions.jsonl>
```

The evaluator validates candidate identity, source hashes, decision semantics,
and reviewer provenance. It reports category, subtype, and category-plus-subtype
accuracy; per-label precision, recall, and F1; legacy-reference agreement; and
error patterns. Metrics apply only to the reviewed sample and are not
automatically corpus-wide accuracy estimates.

Freeze a separate 40-document holdout before changing the rules:

```bash
uv run marygenai classification build-validation-holdout \
  --input-path <classification_corpus_records.jsonl> \
  --exclude-decisions-path <reviewed_development_decisions.jsonl>
```

The default holdout composition is 20 exact rule/legacy agreements, 10 new
disagreements, five records without normalized English legacy reference, and
five titles matching multiple design rules. The holdout must remain unreviewed
until the next rule version is frozen.

Apply the versioned deterministic source-text rules:

```bash
uv run marygenai classification apply-study-design-rules \
  --input-path <benchmark_or_holdout_candidates.jsonl>
```

Rule v2 uses explicit source phrases to refine double-blind trials,
interventional versus observational pilots, and ecological observational
analyses that consume survey-derived data. It verifies source hashes, preserves
candidate identity and original labels in provenance, and does not call an LLM
or mutate SQLite.

Evaluate an existing run without calling a model:

```bash
uv run marygenai classification evaluate \
  --records-path <candidate_classification_records.jsonl> \
  --errors-path <candidate_classification_errors.jsonl> \
  --raw-responses-path <candidate_classification_raw_responses.jsonl> \
  --summary-path <candidate_classification_summary.json> \
  --input-path <classification_sample_records.jsonl> \
  --legacy-context-path <legacy_english_context_records.jsonl>
```

The evaluation writes ignored reports, disagreements, exact and
extraction-tolerant evidence-grounding checks, documents requiring rerun, and a
targeted rerun input under
`data/normalized/classification_evaluations/`. It separates technical validity,
retrieval utility, and inference quality. It also writes versioned
`retrieval_confidence.v1` records with base, broad-recall, and high-precision
heuristic ranking scores.

Run a bounded provider-backed validation:

```bash
uv run marygenai classification run-smoke \
  --limit 5 \
  --input-path <classification_sample_records.jsonl> \
  --no-dry-run \
  --provider openai \
  --model gpt-5.4-mini \
  --max-source-chars 6000 \
  --max-completion-tokens 3000
```

Provider-backed output is candidate evidence. It is written under ignored
`data/normalized/classification_runs/` and does not become reviewed knowledge.

Run a small broad/v3 cost-and-quality validation only after maintainer
authorization:

```bash
uv run marygenai classification run-smoke \
  --limit 50 \
  --input-path <classification_corpus_records.jsonl> \
  --dataset-split strict_classification_ready \
  --no-dry-run \
  --provider openai \
  --model gpt-5.4-mini \
  --max-source-chars 12000 \
  --max-completion-tokens 3000
```

The command currently accepts at most 100 records. Use it for targeted
validation or reruns, not for the already-completed first candidate base. Batch
execution is the supported path for larger tranches.

Evaluate the canary before any larger run:

```bash
uv run marygenai classification evaluate \
  --records-path <candidate_classification_records.jsonl> \
  --errors-path <candidate_classification_errors.jsonl> \
  --raw-responses-path <candidate_classification_raw_responses.jsonl> \
  --summary-path <candidate_classification_summary.json> \
  --input-path <classification_corpus_records.jsonl> \
  --legacy-context-path <legacy_english_context_records.jsonl>
```

Any provider validation must report real provider usage and cost, strict-valid records,
errors and retries, latency, evidence grounding, legacy-reference agreement
where available, and projected cost for the strict classification-ready corpus.
Do not proceed to additional paid classification unless the maintainer approves
the run scope and any required credit top-up.

Prepare a Batch-compatible input file locally, without upload or provider calls:

```bash
uv run marygenai classification prepare-batch \
  --limit 150 \
  --offset 0 \
  --input-path <classification_corpus_records.jsonl> \
  --dataset-split strict_classification_ready \
  --model gpt-5.4-mini \
  --max-source-chars 12000 \
  --max-completion-tokens 3000
```

This command writes ignored artifacts under
`data/normalized/classification_batches/`:

- `<run_id>_openai_batch_input.jsonl`;
- `<run_id>_openai_batch_manifest.jsonl`;
- `<run_id>_openai_batch_prepare_summary.json`;
- `<run_id>_openai_batch_prepare_errors.jsonl`.

Each batch input line contains `custom_id`, `method`, `url`, and `body`, with
`url=/v1/chat/completions`. The manifest maps `custom_id` back to the MaryGenAI
document, packet, source hash, model, and provenance. Use `--offset` with
`--limit` to prepare non-overlapping chunks after the dataset split filter has
been applied. Remote upload, batch creation, status polling, and result
conversion require a separate explicit maintainer authorization.

Batch requests are constrained by provider-side enqueued-token limits. The
preparation command estimates input tokens from request body characters, adds
the max completion ceiling, and blocks locally when the result exceeds the
default 1,800,000-token guard. For the current broad/v3 prompt shape and
`gpt-5.4-mini` organization limit of 2,000,000 enqueued tokens observed on
2026-07-10, use about 150 records per submitted Batch and submit only one
sub-batch at a time.

The first 500-document strict classification-ready tranche is complete using
offsets 0, 150, 300, and 450. It produced 500/500 strict-valid candidate records
after deterministic technical repairs. To continue with the next 500 records,
use offsets 500, 650, 800, and 950 with limits 150, 150, 150, and 50,
respectively. The measured Batch cost for the first 500 was about USD 2.52, or
about USD 0.00504 per document. See
`docs/2026-07-11_batch_and_mcp_handoff.md` before continuing Batch work.

Submit a prepared mini-Batch only after reviewing the local input and manifest:

```bash
uv run marygenai classification submit-batch \
  --batch-input-path <openai_batch_input.jsonl> \
  --manifest-path <openai_batch_manifest.jsonl>
```

This uploads the JSONL through the OpenAI Files API with `purpose=batch`,
creates a remote Batch for `/v1/chat/completions`, and writes a local submission
record. It does not mutate SQLite or reviewed knowledge. The API key must have
permission to write batch files and create/read batches; restricted keys without
Files API write scope cannot submit Batch inputs.

If a completed Batch contains remote request failures, prepare a retry containing
only the failed `custom_id` values from the downloaded error file:

```bash
uv run marygenai classification prepare-batch-retry \
  --batch-input-path <original_openai_batch_input.jsonl> \
  --manifest-path <original_openai_batch_manifest.jsonl> \
  --error-output-path <original_openai_batch_error_output.jsonl>
```

Review the reported counts, then submit the generated retry input and manifest
with `submit-batch`. Retry preparation rewrites run-scoped custom IDs, records
the original custom ID and error artifact in provenance, and excludes successful
requests.

Retrieve status and, when complete, download and convert results:

```bash
uv run marygenai classification retrieve-batch \
  --submission-path <openai_batch_submission.json>
```

To reconvert an already-downloaded output after a deterministic technical
repair, without a provider call:

```bash
uv run marygenai classification convert-batch-output \
  --run-id <run_id> \
  --batch-id <batch_id> \
  --manifest-path <openai_batch_manifest.jsonl> \
  --output-path <openai_batch_output.jsonl>
```

If the remote Batch has completed, the command downloads output and error files
under `data/normalized/classification_batches/`, converts successful responses
into the standard candidate-classification artifacts under
`data/normalized/classification_runs/`, and preserves raw responses for the
normal evaluator. If the Batch is still running, the command writes only a
status snapshot and can be re-run later.

For unattended execution, prefer the watcher:

```bash
uv run marygenai classification watch-batch \
  --submission-path <openai_batch_submission.json> \
  --interval-seconds 300 \
  --max-checks 288
```

The watcher polls remote status, writes a local watch log, and calls the same
retrieve-and-convert path as soon as the Batch reaches a terminal status. With
the default five-minute interval and 288 checks, it can monitor a full 24-hour
completion window. It does not mutate SQLite, review queues, review decisions,
or reviewed knowledge.

For the standard 150-record sequential workflow, the thin orchestration script
accepts only the dataset offset and runs prepare, submit, and watch in order:

```bash
uv run python scripts/run_classification_batch.py 1400
```

The script extracts the generated run ID from `prepare-batch`, verifies the
expected local artifacts before each remote step, and preserves the same
one-sub-batch-at-a-time operating rule.

Provider-side Batch and File objects expose `expires_at` timestamps. Treat those
timestamps as the authoritative retrieval deadline for a specific run and keep
`watch-batch` running when possible so completed outputs are copied into local
ignored artifacts before the provider-side retention window closes.

During conversion, deterministic technical schema repair may add required
`missing_or_uncertain_fields` markers when a candidate response already contains
an empty retrieval list or `cannot_determine` value but omitted the required
uncertainty marker. This repair is provenance-recorded and does not change
scientific field values.

## Read-Only MCP Prototype Workflow

The first MCP milestone should be read-only over ignored local candidate
classification artifacts. It must not mutate SQLite review queues, review
decisions, or reviewed knowledge.

The initial remote MCP demo uses the completed 3,149-document strict corpus.
Sixty records have explicit projected-identity conflicts and require careful
handling in physician-facing acceptance tests. All records remain candidate
evidence.

Initial MCP capabilities should support:

- structured study search with filters for condition, cannabinoid, study
  design, evidence context, population, outcome domain, direction, confidence,
  source readiness, and review state;
- study detail lookup by `document_id`;
- evidence-span inspection with source identity and hashes;
- facet listing for demo and reviewer triage;
- explanation of candidate classification provenance and uncertainty.

The MCP surface must label AI output as candidate evidence and avoid medical
advice or treatment recommendations.

## Maintainer Bootstrap

These commands require private legacy inputs under `temp/legacy/`:

```bash
uv run marygenai initial-load setup-data
uv run marygenai initial-load run
uv run marygenai initial-load persist
```

Public contributors should use public source discovery until reviewed public
snapshots become available.

## Review Workflow

Review commands intentionally operate on SQLite workflow state:

```bash
uv run marygenai review queues
uv run marygenai review list --queue legacy_identity_review
uv run marygenai review show <review_item_id_or_document_id>
uv run marygenai review-api serve --host 127.0.0.1 --port 8000
uv run marygenai review-ui serve --host 127.0.0.1 --port 8000
```

See [Review Status Guide](review_status_guide.md) before changing queue or
decision state.

## Validation

```bash
uv run ruff check .
uv run pytest
```
