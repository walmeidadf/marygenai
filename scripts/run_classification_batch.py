#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

LIMIT: Final = 150
INPUT_PATH: Final = Path(
    "data/normalized/classification_corpus/20260617T142419Z_classification_corpus_records.jsonl"
)
BATCH_DIR: Final = Path("data/normalized/classification_batches")
RUN_ID_RE: Final = re.compile(r"['\"]run_id['\"]\s*:\s*['\"]([0-9TZ]+)['\"]")


def run_command(command: list[str], *, capture_output: bool = False) -> str:
    print(f"Running: {' '.join(command)}", flush=True)
    if not capture_output:
        subprocess.run(command, check=True)
        return ""

    completed = subprocess.run(
        command,
        check=True,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    return completed.stdout


def extract_run_id(output: str) -> str:
    match = RUN_ID_RE.search(output)
    if not match:
        raise RuntimeError("Could not extract run_id from prepare-batch output.")
    return match.group(1)


def require_artifact(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Expected artifact was not created: {path}")


def run_classification_batch(offset: int) -> None:
    prepare_output = run_command(
        [
            "uv",
            "run",
            "marygenai",
            "classification",
            "prepare-batch",
            "--limit",
            str(LIMIT),
            "--offset",
            str(offset),
            "--input-path",
            str(INPUT_PATH),
            "--dataset-split",
            "strict_classification_ready",
            "--model",
            "gpt-5.4-mini",
            "--max-source-chars",
            "12000",
            "--max-completion-tokens",
            "3000",
        ],
        capture_output=True,
    )
    run_id = extract_run_id(prepare_output)
    batch_input_path = BATCH_DIR / f"{run_id}_openai_batch_input.jsonl"
    manifest_path = BATCH_DIR / f"{run_id}_openai_batch_manifest.jsonl"
    submission_path = BATCH_DIR / f"{run_id}_openai_batch_submission.json"
    require_artifact(batch_input_path)
    require_artifact(manifest_path)

    print(f"Prepared run_id: {run_id}", flush=True)
    run_command(
        [
            "uv",
            "run",
            "marygenai",
            "classification",
            "submit-batch",
            "--batch-input-path",
            str(batch_input_path),
            "--manifest-path",
            str(manifest_path),
        ]
    )
    require_artifact(submission_path)

    run_command(
        [
            "uv",
            "run",
            "marygenai",
            "classification",
            "watch-batch",
            "--submission-path",
            str(submission_path),
            "--interval-seconds",
            "300",
            "--max-checks",
            "288",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare, submit, and watch one sequential classification Batch chunk.",
    )
    parser.add_argument(
        "offset",
        type=int,
        help="Zero-based offset in the strict_classification_ready dataset split.",
    )
    args = parser.parse_args()
    if args.offset < 0:
        parser.error("offset must be zero or greater")

    try:
        run_classification_batch(args.offset)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Batch workflow failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
