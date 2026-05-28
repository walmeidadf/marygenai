from __future__ import annotations

import sqlite3
from pathlib import Path

from marygenai.initial_load.persist import (
    identity_review_priority,
    legacy_study_design_rank,
    persist_initial_load,
)
from marygenai.initial_load.pipeline import run_initial_load
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.schemas import CanonicalPublicationCandidate
from marygenai.storage import LocalStorage
from tests.test_initial_load import create_minimal_legacy_csvs, write_csv


def legacy_publication(
    study_type: str,
    *,
    url: str = "https://example.org/study",
) -> CanonicalPublicationCandidate:
    from marygenai.initial_load.legacy_studies import build_publication_candidate

    return build_publication_candidate(
        row={
            "ID do Estudo": "priority-test",
            "Título": "Legacy title",
            "Título do artigo em inglês": "Priority Test Publication",
            "URL do estudo": url,
            "Ano de Publicação": "2024",
            "Tipo de Estudo": study_type,
            "Resultado do Estudo": "Inconclusive",
        },
        row_number=2,
        source_file=Path("legacy.csv"),
        run_id="test-run",
    )


def create_identity_review_legacy_csvs(base_dir: Path) -> None:
    create_minimal_legacy_csvs(base_dir)
    write_csv(
        base_dir / "Estudos-Grid view.csv",
        [
            "ID do Estudo",
            "Título",
            "Principais Conclusões",
            "Tipo de Estudo",
            "Resultado do Estudo",
            "Tamanho da Amostra do Estudo",
            "Título do artigo em inglês",
            "Países do estudo",
            "Ano de Publicação",
            "Domínio onde estudo foi publicado",
            "URL do estudo",
        ],
        [
            [
                "1",
                "Título em português",
                "Findings",
                "Metanálise",
                "Positivo",
                "10",
                "Cannabis Study",
                "Brazil",
                "2024",
                "nlm.nih.gov",
                "https://pubmed.ncbi.nlm.nih.gov/35319936/",
            ],
            [
                "2",
                "Estudo sem identificador externo",
                "Findings",
                "Ensaio Clínico",
                "Inconclusivo",
                "20",
                "Cannabinoid Trial Without Stable Identifier",
                "Brazil",
                "2023",
                "example.org",
                "https://example.org/cannabinoid-trial",
            ],
        ],
    )


def scalar(connection: sqlite3.Connection, query: str) -> int:
    value = connection.execute(query).fetchone()
    assert value is not None
    return int(value[0])


def test_legacy_study_design_rank_uses_evidence_hierarchy() -> None:
    assert legacy_study_design_rank("Metanálise") == ("meta_analysis", 80)
    assert legacy_study_design_rank("Revisão Sistemática") == ("systematic_review", 70)
    assert legacy_study_design_rank("Ensaio Clínico Randomizado") == (
        "randomized_controlled_trial",
        60,
    )
    assert legacy_study_design_rank("Ensaio Clínico") == (
        "controlled_clinical_trial",
        50,
    )
    assert legacy_study_design_rank("Relato de Caso") == ("case_report", 10)
    assert legacy_study_design_rank("Narrative overview") == (None, 0)


def test_identity_review_priority_uses_legacy_study_type_before_identity_tiebreak() -> None:
    meta_weak = legacy_publication("Metanálise", url="")
    trial_strong = legacy_publication("Ensaio Clínico")

    meta_tier, meta_score = identity_review_priority(meta_weak)
    trial_tier, trial_score = identity_review_priority(trial_strong)

    assert meta_tier == "legacy_study_type:meta_analysis|identity:title_only"
    assert trial_tier == (
        "legacy_study_type:controlled_clinical_trial|identity:canonical_url_and_title"
    )
    assert meta_score > trial_score


def test_initialize_schema_creates_core_tables(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)

    with connect_sqlite(database_path) as connection:
        schema_version = initialize_schema(connection)
        second_schema_version = initialize_schema(connection)
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert schema_version == 4
    assert second_schema_version == 4
    assert {
        "run_manifest",
        "source_record",
        "document",
        "document_identity",
        "publication",
        "ontology_entity",
        "document_ontology_link",
        "review_item",
        "review_decision",
        "publication_candidate_discovery",
        "access_enrichment_artifact",
    }.issubset(table_names)


def test_persist_initial_load_is_idempotent(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_identity_review_legacy_csvs(legacy_dir)
    run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )

    first_result = persist_initial_load(storage=LocalStorage(data_dir))
    second_result = persist_initial_load(storage=LocalStorage(data_dir))

    assert first_result == second_result
    with connect_sqlite(sqlite_database_path(data_dir)) as connection:
        assert scalar(connection, "SELECT COUNT(*) FROM run_manifest") == 1
        assert scalar(connection, "SELECT COUNT(*) FROM source_record") == 7
        assert scalar(connection, "SELECT COUNT(*) FROM document") == 2
        assert scalar(connection, "SELECT COUNT(*) FROM publication") == 2
        assert scalar(connection, "SELECT COUNT(*) FROM ontology_entity") == 5
        assert scalar(connection, "SELECT COUNT(*) FROM document_ontology_link") == 4
        assert scalar(connection, "SELECT COUNT(*) FROM review_item") == 1


def test_persist_initial_load_loads_jsonl_fixture(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_identity_review_legacy_csvs(legacy_dir)
    run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )

    result = persist_initial_load(storage=LocalStorage(data_dir), run_id="20260515T120000Z")

    assert result["publication_candidates"] == 2
    with connect_sqlite(sqlite_database_path(data_dir)) as connection:
        run = connection.execute(
            "SELECT status FROM run_manifest WHERE run_id = ?",
            ("20260515T120000Z",),
        ).fetchone()
        title = connection.execute(
            """
            SELECT primary_title
            FROM document
            WHERE document_id = 'publication:pmid:35319936'
            """
        ).fetchone()

    assert run == ("succeeded",)
    assert title == ("Cannabis Study",)


def test_persist_initial_load_creates_legacy_identity_review_queue(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_identity_review_legacy_csvs(legacy_dir)
    run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )

    persist_initial_load(storage=LocalStorage(data_dir))

    with connect_sqlite(sqlite_database_path(data_dir)) as connection:
        rows = connection.execute(
            """
            SELECT queue_type, priority_tier, status, document.primary_title
            FROM review_item
            JOIN document USING (document_id)
            ORDER BY document.primary_title
            """
        ).fetchall()

    assert rows == [
        (
            "legacy_identity_review",
            "legacy_study_type:controlled_clinical_trial|identity:canonical_url_and_title",
            "open",
            "Cannabinoid Trial Without Stable Identifier",
        )
    ]


def test_legacy_identity_review_queue_orders_by_study_type_priority(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_minimal_legacy_csvs(legacy_dir)
    write_csv(
        legacy_dir / "Estudos-Grid view.csv",
        [
            "ID do Estudo",
            "Título",
            "Principais Conclusões",
            "Tipo de Estudo",
            "Resultado do Estudo",
            "Tamanho da Amostra do Estudo",
            "Título do artigo em inglês",
            "Países do estudo",
            "Ano de Publicação",
            "Domínio onde estudo foi publicado",
            "URL do estudo",
        ],
        [
            [
                "1",
                "Legacy clinical trial",
                "Findings",
                "Ensaio Clínico",
                "Inconclusive",
                "20",
                "Simple Clinical Trial Without Stable Identifier",
                "Brazil",
                "2023",
                "example.org",
                "https://example.org/simple-trial",
            ],
            [
                "2",
                "Legacy meta analysis",
                "Findings",
                "Metanálise",
                "Positive",
                "20",
                "Meta Analysis Without Stable Identifier",
                "Brazil",
                "2023",
                "example.org",
                "",
            ],
        ],
    )
    run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )

    persist_initial_load(storage=LocalStorage(data_dir))

    with connect_sqlite(sqlite_database_path(data_dir)) as connection:
        rows = connection.execute(
            """
            SELECT document.primary_title, review_item.priority_tier, review_item.priority_score
            FROM review_item
            JOIN document USING (document_id)
            ORDER BY review_item.priority_score DESC
            """
        ).fetchall()

    assert rows == [
        (
            "Meta Analysis Without Stable Identifier",
            "legacy_study_type:meta_analysis|identity:title_only",
            8060.0,
        ),
        (
            "Simple Clinical Trial Without Stable Identifier",
            "legacy_study_type:controlled_clinical_trial|identity:canonical_url_and_title",
            5080.0,
        ),
    ]
