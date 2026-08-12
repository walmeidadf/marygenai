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

The private development environment may enable the explicit query-token
compatibility mode for hosts that cannot configure fixed request headers.
Bearer authentication remains preferred. Never commit or publish a complete
secret-bearing connector URL, and do not treat shared pilot access as
per-physician authentication.

The generated DuckDB index and manifest remain ignored under
`data/normalized/retrieval_indexes/`. Build and runtime do not open or mutate
MaryGenAI SQLite, review queues, review decisions, or reviewed knowledge. The
runtime opens DuckDB with `read_only=True` and exposes no provider or network
tool. See `docs/mcp_retrieval_contract.md` for the contract and
`docs/mcp_clinical_retrieval_research.md` for clinical acceptance questions and
the future backlog.

## Website And Dataset Viewer Workflow

The frontend requires Node.js 22.13 or newer. Run the public website and
synthetic Dataset Viewer demonstration without any private data:

```bash
cd web
npm install
npm run dev
```

The demonstration fixtures are fictional, versioned, and labeled in the
interface. They are not scientific publications or a distributable copy of the
maintainer-local candidate index.

To use one existing immutable DuckDB index, start the read-only Viewer API:

```bash
uv run marygenai viewer serve-api \
  --index-path data/normalized/retrieval_indexes/marygenai_candidate_retrieval_v1.duckdb
```

Then start the frontend in another terminal with the server-side proxy enabled:

```bash
cd web
MARYGENAI_VIEWER_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The API reuses the retrieval models and `RetrievalService`. It opens DuckDB with
`read_only=True`, excludes local source paths from web responses, and does not
receive SQLite, protected review state, provider credentials, or write tools.

Validate the frontend independently:

```bash
cd web
npm run lint
npm test
npm run build
```

The Sites-compatible frontend configuration is not proof of publication. Do not
create a hosted site, publish a candidate index, or claim redistribution rights
without explicit authorization and a reviewed exposure boundary.

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

Audit the already discovered PubMed 2024+ candidates, freeze the deterministic
source-valid canary, and prepare prompt packets without a provider call:

```bash
uv run marygenai classification-corpus prepare-pubmed-canary \
  --target-size 100 \
  --corpus-version pubmed_2024plus_canary.v1 \
  --max-source-chars 12000 \
  --target-model-provider openai \
  --target-model-name gpt-5.4-mini
```

The command opens SQLite read-only, verifies protected-state snapshots before
and after the run, and writes ignored quality records, exclusions, extracted
text, frozen manifest/corpus records, and prompt packets. The current local v1
gate admits eight documents, not 100, because most persisted open artifacts do
not verify the candidate identity. Do not lower the identity gate to fill the
target.

Build a PMID-based identity-repair overlay for a bounded set of source failures:

```bash
uv run marygenai classification-corpus repair-pubmed-source-identities \
  --target-size 150 \
  --no-apply
```

This command makes a free PubMed EFetch request, writes ignored raw XML,
normalized repair records, errors, summary, and a corrected-PMC reenrichment
worklist under `data/normalized/pubmed_canary/identity_repairs/`. It rejects
`--apply`, opens SQLite read-only/query-only, and verifies protected state before
and after execution. It does not call an LLM or persist identity changes.

The first run resolved 150/150 candidates with no errors. Every persisted PMCID
changed, 149 corrected official PMCIDs entered the reenrichment worklist, and
one no-PMCID record was routed to Europe PMC or Unpaywall.

Fetch corrected Europe PMC XML, apply the identity/content and human medical
scope gates, and freeze the immutable v2 corpus without calling a model:

```bash
uv run marygenai classification-corpus prepare-pubmed-canary-v2 \
  --target-size 100 \
  --prepare-prompt-packets \
  --max-source-chars 12000 \
  --target-model-name gpt-5.4-mini
```

The command consumes the ignored PMID-resolved worklist, uses the corrected
official PMCID, caches open Europe PMC full-text XML under ignored `data/`, and
refuses to replace a frozen manifest or corpus with different bytes. It excludes
veterinary-only, clearly non-medical, and titles without a human medical or
public-health signal. SQLite and protected review state are checked before and
after the run.

The first v2 run evaluated 105 source artifacts and selected 100 documents.
Five evaluated artifacts failed source identity or content quality. A cached
rerun reproduced the manifest and corpus hashes exactly.

For later non-overlapping slices, use the generic command and explicitly exclude
every prior frozen manifest:

```bash
uv run marygenai classification-corpus prepare-pubmed-canary-slice \
  --target-size 100 \
  --worklist-path <expanded_identity_reenrichment_worklist.jsonl> \
  --exclude-manifest-path <prior_frozen_manifest.jsonl> \
  --corpus-version pubmed_2024plus_canary.v3 \
  --prepare-prompt-packets \
  --max-source-chars 12000 \
  --target-model-name gpt-5.4-mini
```

`--exclude-manifest-path` is repeatable. Excluded document IDs are rejected
before network acquisition, recorded in the source-quality report, and tested
for deterministic non-overlap. The first v3 slice selected 100 new documents,
had zero overlap with v2, and reproduced its frozen hashes from cache.

For cannabinoid-focused retrieval canaries, apply the post-classification
inclusion gate when building the index:

```bash
uv run marygenai retrieval build-index \
  --output-path <qualified_canary.duckdb> \
  --records-path <candidate_classification_records.jsonl> \
  --corpus-path <combined_corpus_records.jsonl> \
  --evaluation-report-path <classification_evaluation_report.json> \
  --require-cannabinoid-exposure
```

The option excludes classifications with an empty structured
`cannabinoids_or_exposures` list. It writes an adjacent ignored exclusions JSONL
with document identity, reason, uncertainty, confidence, review state, and
provenance. It does not delete classification records or mutate SQLite. The
default remains unchanged for non-cannabinoid or diagnostic index builds.

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

The strict classification-ready corpus is complete. Twenty-four runs, including
targeted retries, produced 3,149/3,149 strict-valid candidate records with
evidence spans. Do not continue the historical offsets as though more strict
records remain. A new provider-backed run requires explicit authorization and
an intentionally new or changed corpus. Preserve the observed operating limit
of about 150 records per sequential Batch for the current prompt shape. Review
[Current Status](current_status.md) before further classification work.

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

## Read-Only MCP Pilot Workflow

The implemented MCP pilot is read-only over ignored local candidate
classification artifacts and a content-addressed remote copy of the generated
index. It must not mutate SQLite review queues, review decisions, or reviewed
knowledge.

The initial remote MCP demo uses the completed 3,149-document strict corpus.
Sixty records have explicit projected-identity conflicts and require careful
handling in physician-facing acceptance tests. All records remain candidate
evidence.

Current MCP capabilities support:

- structured study search with filters for condition, cannabinoid, study
  design, evidence context, population, outcome domain, direction, confidence,
  source readiness, and review state;
- study detail lookup by `document_id`;
- evidence-span inspection with source identity and hashes;
- facet listing for demo and reviewer triage;
- explanation of candidate classification provenance and uncertainty.

The MCP surface must label AI output as candidate evidence and avoid medical
advice or treatment recommendations.

Hosted ChatGPT and Claude connectors completed end-to-end pilot tests. Their
hosts translate Portuguese scientific concepts to the primarily English index.
Search responses carry a presentation contract that requires bounded
zero-result wording, preferred physician-facing links, detail inspection before
detailed evidence claims, and separation of direct from tangential matches. See
[Current Status](current_status.md) for the next workstreams.

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
