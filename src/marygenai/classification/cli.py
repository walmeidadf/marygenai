from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.classification.benchmark import (
    apply_study_design_rules_to_candidates,
    build_study_design_holdout,
    build_study_design_validation_benchmark,
    evaluate_study_design_benchmark,
)
from marygenai.classification.evaluation import evaluate_classification_run
from marygenai.classification.pipeline import (
    CLASSIFICATION_DATASET_SPLITS,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_SOURCE_CHARS,
    build_classification_prompt_packets,
    prepare_openai_batch_requests,
    retrieve_and_convert_openai_batch,
    run_classification_smoke,
    submit_openai_batch,
    watch_openai_batch,
)
from marygenai.classification.retrieval_baseline import (
    run_retrieval_metadata_baseline,
)
from marygenai.classification.retrieval_profile import profile_retrieval_fields
from marygenai.classification.v4_packets import (
    DEFAULT_INPUT_COST_PER_MILLION,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_COST_PER_MILLION,
    DEFAULT_PROVIDER,
    build_v4_comparison_packets,
)
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Run candidate classification validation workflows.")
console = Console()


@app.callback()
def main() -> None:
    """Run candidate classification commands."""


@app.command("run-smoke")
def run_smoke(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=100, help="Maximum sample records to validate."),
    ] = 5,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification sample or corpus JSONL path."),
    ] = None,
    dataset_split: Annotated[
        str | None,
        typer.Option(
            "--dataset-split",
            help=(
                "Optional corpus split filter. Supported values: "
                f"{', '.join(sorted(CLASSIFICATION_DATASET_SPLITS))}."
            ),
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            min=0,
            help="Skip this many source-ready records after applying the dataset split filter.",
        ),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Use deterministic mock outputs."),
    ] = True,
    provider: Annotated[
        str,
        typer.Option("--provider", help="Provider for --no-dry-run. Currently only openai."),
    ] = "openai",
    model: Annotated[
        str,
        typer.Option("--model", help="Model for --no-dry-run."),
    ] = DEFAULT_OPENAI_MODEL,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = 6_000,
    max_completion_tokens: Annotated[
        int,
        typer.Option("--max-completion-tokens", min=500, max=8_000),
    ] = DEFAULT_MAX_COMPLETION_TOKENS,
) -> None:
    """Validate candidate classification schema on a tiny local sample."""
    settings = get_settings()
    result = run_classification_smoke(
        storage=LocalStorage(settings.data_dir),
        limit=limit,
        input_path=input_path,
        dry_run=dry_run,
        provider=provider,
        model=model,
        max_source_chars=max_source_chars,
        max_completion_tokens=max_completion_tokens,
        dataset_split=dataset_split,
        offset=offset,
    )
    console.print(result)


@app.command("build-prompt-packets")
def build_prompt_packets(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=100, help="Maximum sample records to packetize."),
    ] = 5,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification sample or corpus JSONL path."),
    ] = None,
    dataset_split: Annotated[
        str | None,
        typer.Option(
            "--dataset-split",
            help=(
                "Optional corpus split filter. Supported values: "
                f"{', '.join(sorted(CLASSIFICATION_DATASET_SPLITS))}."
            ),
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            min=0,
            help="Skip this many source-ready records after applying the dataset split filter.",
        ),
    ] = 0,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_provider: Annotated[
        str | None,
        typer.Option("--target-model-provider", help="Provider planned for later real run."),
    ] = None,
    target_model_name: Annotated[
        str | None,
        typer.Option("--target-model-name", help="Model planned for later real run."),
    ] = None,
) -> None:
    """Build prompt packets for inspection without calling an LLM."""
    settings = get_settings()
    result = build_classification_prompt_packets(
        storage=LocalStorage(settings.data_dir),
        limit=limit,
        input_path=input_path,
        max_source_chars=max_source_chars,
        target_model_provider=target_model_provider,
        target_model_name=target_model_name,
        dataset_split=dataset_split,
        offset=offset,
    )
    console.print(result)


@app.command("prepare-batch")
def prepare_batch(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=50_000, help="Maximum records to prepare."),
    ] = 50,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification sample or corpus JSONL path."),
    ] = None,
    dataset_split: Annotated[
        str | None,
        typer.Option(
            "--dataset-split",
            help=(
                "Optional corpus split filter. Supported values: "
                f"{', '.join(sorted(CLASSIFICATION_DATASET_SPLITS))}."
            ),
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            min=0,
            help="Skip this many source-ready records after applying the dataset split filter.",
        ),
    ] = 0,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = DEFAULT_PROMPT_SOURCE_CHARS,
    model: Annotated[
        str,
        typer.Option("--model", help="OpenAI model to place in each batch request."),
    ] = DEFAULT_OPENAI_MODEL,
    max_completion_tokens: Annotated[
        int,
        typer.Option("--max-completion-tokens", min=500, max=8_000),
    ] = DEFAULT_MAX_COMPLETION_TOKENS,
) -> None:
    """Prepare OpenAI Batch JSONL locally without uploading or calling a model."""
    settings = get_settings()
    result = prepare_openai_batch_requests(
        storage=LocalStorage(settings.data_dir),
        limit=limit,
        input_path=input_path,
        dataset_split=dataset_split,
        offset=offset,
        max_source_chars=max_source_chars,
        model=model,
        max_completion_tokens=max_completion_tokens,
    )
    console.print(result)


@app.command("submit-batch")
def submit_batch(
    batch_input_path: Annotated[
        Path,
        typer.Option("--batch-input-path", help="Prepared OpenAI Batch input JSONL path."),
    ],
    manifest_path: Annotated[
        Path,
        typer.Option("--manifest-path", help="Prepared MaryGenAI batch manifest JSONL path."),
    ],
    completion_window: Annotated[
        str,
        typer.Option("--completion-window", help="OpenAI Batch completion window."),
    ] = "24h",
) -> None:
    """Upload a prepared Batch file and create a remote OpenAI Batch."""
    settings = get_settings()
    try:
        result = submit_openai_batch(
            storage=LocalStorage(settings.data_dir),
            batch_input_path=batch_input_path,
            manifest_path=manifest_path,
            completion_window=completion_window,
        )
    except RuntimeError as exc:
        console.print({"error": str(exc)})
        raise typer.Exit(1) from exc
    console.print(result)


@app.command("retrieve-batch")
def retrieve_batch(
    submission_path: Annotated[
        Path,
        typer.Option("--submission-path", help="Local OpenAI Batch submission JSON path."),
    ],
    manifest_path: Annotated[
        Path | None,
        typer.Option("--manifest-path", help="Override manifest path for conversion."),
    ] = None,
) -> None:
    """Retrieve remote Batch status, download completed outputs, and convert records."""
    settings = get_settings()
    try:
        result = retrieve_and_convert_openai_batch(
            storage=LocalStorage(settings.data_dir),
            submission_path=submission_path,
            manifest_path=manifest_path,
        )
    except RuntimeError as exc:
        console.print({"error": str(exc)})
        raise typer.Exit(1) from exc
    console.print(result)


@app.command("watch-batch")
def watch_batch(
    submission_path: Annotated[
        Path,
        typer.Option("--submission-path", help="Local OpenAI Batch submission JSON path."),
    ],
    manifest_path: Annotated[
        Path | None,
        typer.Option("--manifest-path", help="Override manifest path for conversion."),
    ] = None,
    interval_seconds: Annotated[
        int,
        typer.Option(
            "--interval-seconds",
            min=30,
            help="Seconds to wait between remote Batch status checks.",
        ),
    ] = 300,
    max_checks: Annotated[
        int,
        typer.Option(
            "--max-checks",
            min=1,
            help="Maximum status checks before stopping if the Batch is still non-terminal.",
        ),
    ] = 288,
) -> None:
    """Poll a remote Batch and retrieve outputs as soon as it reaches a terminal state."""
    settings = get_settings()
    try:
        result = watch_openai_batch(
            storage=LocalStorage(settings.data_dir),
            submission_path=submission_path,
            manifest_path=manifest_path,
            interval_seconds=interval_seconds,
            max_checks=max_checks,
        )
    except RuntimeError as exc:
        console.print({"error": str(exc)})
        raise typer.Exit(1) from exc
    console.print(result)


@app.command("build-validation-benchmark")
def build_validation_benchmark(
    sample_size: Annotated[
        int,
        typer.Option(
            "--sample-size",
            min=1,
            max=200,
            help="Maximum title-explicit benchmark candidates to select.",
        ),
    ] = 48,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification corpus records JSONL."),
    ] = None,
) -> None:
    """Build study-design benchmark candidates without calling a model."""
    settings = get_settings()
    result = build_study_design_validation_benchmark(
        storage=LocalStorage(settings.data_dir),
        input_path=input_path,
        sample_size=sample_size,
    )
    console.print(result)


@app.command("build-validation-holdout")
def build_validation_holdout(
    exclude_decisions_path: Annotated[
        Path,
        typer.Option(
            "--exclude-decisions-path",
            help="Reviewed development decisions to exclude from the holdout.",
        ),
    ],
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification corpus records JSONL."),
    ] = None,
) -> None:
    """Freeze a 40-record study-design holdout without calling a model."""
    settings = get_settings()
    result = build_study_design_holdout(
        storage=LocalStorage(settings.data_dir),
        input_path=input_path,
        exclude_decisions_path=exclude_decisions_path,
    )
    console.print(result)


@app.command("evaluate-validation-benchmark")
def evaluate_validation_benchmark(
    candidates_path: Annotated[
        Path,
        typer.Option("--candidates-path", help="Benchmark candidate records JSONL."),
    ],
    decisions_path: Annotated[
        Path,
        typer.Option("--decisions-path", help="Reviewed benchmark decisions JSONL."),
    ],
) -> None:
    """Evaluate deterministic study-design candidates against reviewed labels."""
    settings = get_settings()
    result = evaluate_study_design_benchmark(
        storage=LocalStorage(settings.data_dir),
        candidates_path=candidates_path,
        decisions_path=decisions_path,
    )
    console.print(result)


@app.command("apply-study-design-rules")
def apply_study_design_rules(
    input_path: Annotated[
        Path,
        typer.Option("--input-path", help="Study-design benchmark candidates JSONL."),
    ],
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Optional explicit output run identifier."),
    ] = None,
) -> None:
    """Apply deterministic study-design rule v2 to candidate records."""
    settings = get_settings()
    result = apply_study_design_rules_to_candidates(
        storage=LocalStorage(settings.data_dir),
        input_path=input_path,
        run_id=run_id,
    )
    console.print(result)


@app.command("evaluate")
def evaluate(
    records_path: Annotated[
        Path | None,
        typer.Option("--records-path", help="Candidate classification records JSONL."),
    ] = None,
    errors_path: Annotated[
        Path | None,
        typer.Option("--errors-path", help="Candidate classification errors JSONL."),
    ] = None,
    raw_responses_path: Annotated[
        Path | None,
        typer.Option("--raw-responses-path", help="Provider raw responses JSONL."),
    ] = None,
    summary_path: Annotated[
        Path | None,
        typer.Option("--summary-path", help="Candidate classification run summary JSON."),
    ] = None,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Original classification sample or corpus JSONL."),
    ] = None,
    legacy_context_path: Annotated[
        Path | None,
        typer.Option(
            "--legacy-context-path",
            help="Normalized English legacy context JSONL.",
        ),
    ] = None,
    estimated_cost_usd: Annotated[
        float | None,
        typer.Option(
            "--estimated-cost-usd",
            min=0,
            help="Optional externally calculated run cost for reporting.",
        ),
    ] = None,
) -> None:
    """Evaluate a candidate classification run without calling a model."""
    settings = get_settings()
    result = evaluate_classification_run(
        storage=LocalStorage(settings.data_dir),
        records_path=records_path,
        errors_path=errors_path,
        raw_responses_path=raw_responses_path,
        summary_path=summary_path,
        input_path=input_path,
        legacy_context_path=legacy_context_path,
        estimated_cost_usd=estimated_cost_usd,
    )
    console.print(result)


@app.command("profile-retrieval-fields")
def profile_retrieval_field_coverage(
    corpus_path: Annotated[
        Path | None,
        typer.Option("--corpus-path", help="Classification corpus records JSONL."),
    ] = None,
    legacy_context_path: Annotated[
        Path | None,
        typer.Option(
            "--legacy-context-path",
            help="Normalized English legacy context JSONL used only as a guardrail.",
        ),
    ] = None,
    sample_size: Annotated[
        int,
        typer.Option(
            "--sample-size",
            min=1,
            max=100,
            help="Size of the deterministic retrieval-field validation sample.",
        ),
    ] = 12,
) -> None:
    """Profile retrieval fields and build a local v4 validation sample."""
    settings = get_settings()
    result = profile_retrieval_fields(
        storage=LocalStorage(settings.data_dir),
        corpus_path=corpus_path,
        legacy_context_path=legacy_context_path,
        sample_size=sample_size,
    )
    console.print(result)


@app.command("extract-retrieval-metadata")
def extract_retrieval_metadata(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input-path",
            help="Retrieval-field validation sample JSONL.",
        ),
    ],
) -> None:
    """Extract deterministic retrieval metadata candidates without an LLM."""
    settings = get_settings()
    result = run_retrieval_metadata_baseline(
        storage=LocalStorage(settings.data_dir),
        input_path=input_path,
    )
    console.print(result)


@app.command("build-v4-comparison-packets")
def build_v4_packets(
    sample_path: Annotated[
        Path,
        typer.Option("--sample-path", help="Frozen retrieval-field validation sample JSONL."),
    ],
    parser_records_path: Annotated[
        Path,
        typer.Option("--parser-records-path", help="Deterministic parser records JSONL."),
    ],
    manifest_path: Annotated[
        Path | None,
        typer.Option(
            "--manifest-path",
            help="Optional frozen comparison manifest JSONL from a previous local gate.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=5, max=10, help="Same documents used by both strategies."),
    ] = 8,
    target_model_provider: Annotated[
        str,
        typer.Option("--target-model-provider"),
    ] = DEFAULT_PROVIDER,
    target_model_name: Annotated[
        str,
        typer.Option("--target-model-name"),
    ] = DEFAULT_MODEL,
    input_cost_per_million: Annotated[
        float,
        typer.Option("--input-cost-per-million", min=0),
    ] = DEFAULT_INPUT_COST_PER_MILLION,
    output_cost_per_million: Annotated[
        float,
        typer.Option("--output-cost-per-million", min=0),
    ] = DEFAULT_OUTPUT_COST_PER_MILLION,
) -> None:
    """Build broad and selective v4 packets, mocks, and cost estimates locally."""
    settings = get_settings()
    result = build_v4_comparison_packets(
        storage=LocalStorage(settings.data_dir),
        sample_path=sample_path,
        parser_records_path=parser_records_path,
        manifest_path=manifest_path,
        limit=limit,
        provider=target_model_provider,
        model=target_model_name,
        input_cost_per_million=input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
    )
    console.print(result)
