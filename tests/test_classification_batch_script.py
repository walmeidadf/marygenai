from __future__ import annotations

import pytest

from scripts.run_classification_batch import extract_run_id


def test_extract_run_id_from_prepare_batch_output() -> None:
    output = "{'run_id': '20260720T133501Z', 'counts': {'batch_requests': 150}}"

    assert extract_run_id(output) == "20260720T133501Z"


def test_extract_run_id_rejects_unexpected_output() -> None:
    with pytest.raises(RuntimeError, match="Could not extract run_id"):
        extract_run_id("prepare-batch completed without a run identifier")
