from __future__ import annotations

import sqlite3
from pathlib import Path

from marygenai.initial_load.persist import persist_initial_load
from marygenai.initial_load.pipeline import run_initial_load
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.storage import LocalStorage
from tests.test_initial_load import create_minimal_legacy_csvs, write_csv


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


def test_initialize_schema_creates_core_tables(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)

    with connect_sqlite(database_path) as connection:
        schema_version = initialize_schema(connection)
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert schema_version == 1
    assert {
        "run_manifest",
        "source_record",
        "document",
        "document_identity",
        "publication",
        "ontology_entity",
        "document_ontology_link",
        "review_item",
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
            "canonical_url_and_title",
            "open",
            "Cannabinoid Trial Without Stable Identifier",
        )
    ]
