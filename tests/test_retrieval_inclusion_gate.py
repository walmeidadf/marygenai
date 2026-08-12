from __future__ import annotations

from marygenai.retrieval.index import _requires_cannabinoid_exposure


def test_global_exposure_gate_applies_to_every_run() -> None:
    assert _requires_cannabinoid_exposure(
        "legacy-run",
        require_for_all_runs=True,
        required_run_ids=set(),
    )


def test_scoped_exposure_gate_preserves_unlisted_runs() -> None:
    scoped_run_ids = {"pubmed-v2", "pubmed-v3", "pubmed-v4"}

    assert not _requires_cannabinoid_exposure(
        "legacy-run",
        require_for_all_runs=False,
        required_run_ids=scoped_run_ids,
    )
    assert _requires_cannabinoid_exposure(
        "pubmed-v4",
        require_for_all_runs=False,
        required_run_ids=scoped_run_ids,
    )
