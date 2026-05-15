from __future__ import annotations

import json
from pathlib import Path

from marygenai.initial_load.files import resolve_legacy_csv
from marygenai.initial_load.legacy_ontology import import_legacy_ontology
from marygenai.initial_load.legacy_studies import build_publication_candidate, import_legacy_studies
from marygenai.initial_load.pipeline import run_initial_load
from marygenai.persistence.sqlite import connect_sqlite, sqlite_database_path
from marygenai.storage import LocalStorage


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header), *[",".join(row) for row in rows]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_minimal_legacy_csvs(base_dir: Path) -> None:
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
            ]
        ],
    )
    write_csv(
        base_dir / "Canabinóides-Grid view.csv",
        ["Cabinóide", "tag", "Grupo de Canabinóide", "Descrição", "Nomes", "english", "Estudos"],
        [["Canabidiol", "cbd", "Fitocanabinoides", "CBD description", "CBD", "Cannabidiol", "1"]],
    )
    write_csv(
        base_dir / "Condições Médicas-Grid view.csv",
        ["Condição Médica", "tag", "Descrição da condição médica", "Outros nomes", "Estudos"],
        [["Dor", "pain", "Pain description", "Pain", "1"]],
    )
    write_csv(
        base_dir / "Sistemas do Organismo-Grid view.csv",
        ["Sistema do Organismo", "tag", "Descrição", "Sinônimos", "Estudos"],
        [["Sistema nervoso", "nervous-system", "Nervous system", "Neurologia", "1"]],
    )
    write_csv(
        base_dir / "Terpenos-Grid view.csv",
        ["Terpeno", "tag", "Sumário", "Outros Nomes", "english", "Estudos"],
        [["Mirceno", "myrcene", "Myrcene summary", "Myrcene", "Myrcene", "1"]],
    )
    write_csv(
        base_dir / "Glossário-Grid view.csv",
        ["Palavra em Português", "Significado em Português"],
        [["Afinidade", "Binding affinity"]],
    )


def test_resolve_legacy_csv_handles_decomposed_accents(tmp_path: Path) -> None:
    path = tmp_path / "Canabinóides-Grid view.csv"
    path.write_text("Cabinóide\nCBD\n", encoding="utf-8")

    assert resolve_legacy_csv(tmp_path, "Canabinoides-Grid view.csv") == path


def test_build_publication_candidate_extracts_identity() -> None:
    record = build_publication_candidate(
        row={
            "ID do Estudo": "1",
            "Título": "Título em português",
            "Título do artigo em inglês": "Cannabis Use Example.",
            "URL do estudo": "https://pubmed.ncbi.nlm.nih.gov/35319936/",
            "Ano de Publicação": "2022",
            "Tipo de Estudo": "Metanálise",
            "Resultado do Estudo": "Positivo",
        },
        row_number=2,
        source_file=Path("legacy.csv"),
        run_id="test-run",
    )

    assert record.document_id == "publication:pmid:35319936"
    assert record.pmid == "35319936"
    assert record.publication_year == 2022
    assert record.normalized_title == "cannabis use example"


def test_import_legacy_ontology_links_entities_to_documents(tmp_path: Path) -> None:
    create_minimal_legacy_csvs(tmp_path)
    source_records, publications, legacy_id_to_document_id = import_legacy_studies(
        studies_path=tmp_path / "Estudos-Grid view.csv",
        run_id="test-run",
    )
    ontology_sources, entities, links = import_legacy_ontology(
        table_paths={
            "cannabinoids": tmp_path / "Canabinóides-Grid view.csv",
            "medical_conditions": tmp_path / "Condições Médicas-Grid view.csv",
            "organ_systems": tmp_path / "Sistemas do Organismo-Grid view.csv",
            "terpenes": tmp_path / "Terpenos-Grid view.csv",
            "glossary_terms": tmp_path / "Glossário-Grid view.csv",
        },
        legacy_id_to_document_id=legacy_id_to_document_id,
        run_id="test-run",
    )

    assert len(source_records) == 1
    assert len(publications) == 1
    assert len(ontology_sources) == 5
    assert len(entities) == 5
    assert len(links) == 4
    assert {link.document_id for link in links} == {"publication:pmid:35319936"}


def test_run_initial_load_writes_jsonl_and_manifest(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_minimal_legacy_csvs(legacy_dir)

    result = run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )

    assert result.counts == {
        "source_records": 6,
        "publication_candidates": 1,
        "ontology_entities": 5,
        "document_ontology_links": 4,
    }
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "20260515T120000Z"
    assert manifest["status"] == "succeeded"
    assert (data_dir / "db").is_dir()


def test_sqlite_persistence_helper_prepares_database_parent(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)

    with connect_sqlite(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)

    assert database_path.exists()
