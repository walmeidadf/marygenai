from __future__ import annotations

import json
from pathlib import Path

from marygenai.analytics.base_status import build_base_status_report
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path


def create_analytics_database(tmp_path: Path) -> Path:
    database_path = sqlite_database_path(tmp_path)
    with connect_sqlite(database_path) as connection:
        initialize_schema(connection)
        connection.execute(
            """
            INSERT INTO run_manifest (
                run_id, job_type, source, started_at, completed_at, status,
                software_version, input_artifacts_json, output_artifacts_json,
                counts_json, errors_json, notes_json, manifest_path, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-run",
                "initial_load",
                "legacy_cannadocs",
                "2026-05-25T00:00:00+00:00",
                "2026-05-25T00:00:00+00:00",
                "succeeded",
                "test",
                "{}",
                "{}",
                "{}",
                "[]",
                "[]",
                None,
                "2026-05-25T00:00:00+00:00",
            ),
        )
        _insert_legacy_publication(
            connection,
            legacy_id="1",
            document_id="publication:pmid:111",
            title="Cannabis pain meta analysis",
            study_type="Metanálise",
            result="Positivo",
            conditions="Dor, Náusea",
            url="https://pubmed.ncbi.nlm.nih.gov/111/",
            pmid="111",
            pmcid="PMC111",
            doi=None,
        )
        _insert_legacy_publication(
            connection,
            legacy_id="2",
            document_id="publication:url:science-direct",
            title="Clinical trial for pain",
            study_type="Ensaio Clínico",
            result="Inconclusivo",
            conditions="Dor",
            url="https://www.sciencedirect.com/science/article/abs/pii/S123456789",
            pmid=None,
            pmcid=None,
            doi=None,
        )
        connection.execute(
            """
            INSERT INTO review_item (
                review_item_id, queue_type, document_id, priority_tier, priority_score,
                assignee, status, batch_run_id, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "review_item:science-direct",
                "legacy_identity_review",
                "publication:url:science-direct",
                "identity:canonical_url_and_title",
                10.0,
                None,
                "open",
                "test-run",
                "{}",
                "2026-05-25T00:00:00+00:00",
                "2026-05-25T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO access_enrichment_artifact (
                artifact_id, document_id, source, artifact_type, access_class, url, license,
                payload_path, payload_sha256, payload_size_bytes, raw_payload_json,
                errors_json, provenance_json, run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "artifact:pmc",
                "publication:pmid:111",
                "pmc",
                "pmc_nxml",
                "open_access_green",
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC111/",
                None,
                "data/example.xml",
                "abc",
                100,
                "{}",
                "[]",
                "{}",
                "test-run",
                "2026-05-25T00:00:00+00:00",
            ),
        )
    return database_path


def _insert_legacy_publication(
    connection,
    *,
    legacy_id: str,
    document_id: str,
    title: str,
    study_type: str,
    result: str,
    conditions: str,
    url: str,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
) -> None:
    raw_payload = {
        "ID do Estudo": legacy_id,
        "Título": f"Título {legacy_id}",
        "Título do artigo em inglês": title,
        "Principais Conclusões": "Strong finding",
        "Tipo de Estudo": study_type,
        "Resultado do Estudo": result,
        "Ano de Publicação": "2024",
        "URL do estudo": url,
        "Condições Médicas": conditions,
        "Canabinoides": "CBD",
        "Tamanho da Amostra do Estudo": "25",
    }
    connection.execute(
        """
        INSERT INTO source_record (
            source_record_id, source, source_table, legacy_id, row_number, payload_hash,
            raw_payload_json, provenance_json, run_id, error_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"legacy_cannadocs:studies:{legacy_id}",
            "legacy_cannadocs",
            "studies",
            legacy_id,
            int(legacy_id),
            f"hash-{legacy_id}",
            json.dumps(raw_payload),
            "{}",
            "test-run",
            None,
        ),
    )
    connection.execute(
        """
        INSERT INTO document (
            document_id, document_type, primary_title, publication_year, canonical_url,
            pmid, pmcid, doi, lifecycle_state, review_state, provenance_json, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            "publication",
            title,
            2024,
            url,
            pmid,
            pmcid,
            doi,
            "active",
            "trusted_legacy_reference",
            "{}",
            "test-run",
        ),
    )
    connection.execute(
        """
        INSERT INTO publication (
            document_id, title_pt, title_en, normalized_title, legacy_study_id,
            legacy_study_type, legacy_result, legacy_reference_values_json, journal,
            authors_json, publication_types_json, language, abstract
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            raw_payload["Título"],
            title,
            title.casefold(),
            legacy_id,
            study_type,
            result,
            json.dumps(raw_payload),
            None,
            "[]",
            "[]",
            None,
            None,
        ),
    )


def test_base_status_report_counts_legacy_identity_and_access(tmp_path: Path) -> None:
    database_path = create_analytics_database(tmp_path)

    report = build_base_status_report(database_path, top=10)

    assert report["overview"]["legacy_study_source_rows"] == 2
    assert report["overview"]["legacy_unique_documents"] == 2
    assert report["overview"]["sqlite_documents"] == 2
    assert report["bibliographic_identity"]["with_pmid"]["count"] == 1
    assert report["bibliographic_identity"]["without_strong_identifier"]["count"] == 1
    assert report["canonical_url"]["science_direct_abs_pii"] == 1
    assert report["legacy_descriptive_evidence"]["strong_descriptive_evidence"]["count"] == 2
    assert report["access_open_download"]["documents_with_open_access_artifact"] == 1
    assert report["access_open_download"]["legacy_documents_with_pmcid_open_access_inference"] == 1


def test_base_status_report_summarizes_conditions(tmp_path: Path) -> None:
    database_path = create_analytics_database(tmp_path)

    report = build_base_status_report(database_path, condition="Dor")

    assert report["conditions"]["filter"] == "Dor"
    assert report["conditions"]["items"] == [
        {
            "condition": "Dor",
            "total_studies": 2,
            "study_type_counts": {"Metanálise": 1, "Ensaio Clínico": 1},
            "meta_analysis": 1,
            "clinical_meta_analysis": 0,
            "clinical_trial": 1,
            "double_blind_clinical_trial": 0,
            "with_pmid_pmcid_or_doi": 1,
            "with_pmcid": 1,
            "with_open_access_artifact": 1,
        }
    ]


def test_base_status_report_respects_top_condition_limit(tmp_path: Path) -> None:
    database_path = create_analytics_database(tmp_path)

    report = build_base_status_report(database_path, top=1)

    assert [item["condition"] for item in report["conditions"]["items"]] == ["Dor"]


def test_base_status_report_adds_english_legacy_reference(tmp_path: Path) -> None:
    database_path = create_analytics_database(tmp_path)
    english_path = tmp_path / "identity_confirmed_for_triage.jsonl"
    english_records = [
        {
            "context_id": "context:1",
            "document_id": "publication:pmid:111",
            "identity_confirmation_status": "trusted_legacy_reference_no_identity_queue",
            "title": "Cannabis pain meta analysis",
            "publication_year": 2024,
            "type_of_study": "Meta-analysis",
            "study_result": "Positive",
            "study_sample_size": "25",
            "key_findings": ["Strong finding"],
            "pmid": "111",
            "pmcid": "PMC111",
            "doi": None,
            "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/111/",
            "source_filenames": [
                "medical-condition-thc-cbd-for-chronic-pain-studies-1.html",
                "by-organ-system-thc-cbd-for-nervous-system-studies-1.html",
            ],
            "list_fields": {
                "Cannabinoids Studied": ["Cannabidiol (CBD)"],
                "Study Location(s)": ["United States"],
                "Terpenes Studied": ["Myrcene"],
                "Receptors Studied": ["CB1"],
            },
            "text_fields": {"Dosage": ["10 mg"]},
        }
    ]
    english_path.write_text(
        "\n".join(json.dumps(record) for record in english_records) + "\n",
        encoding="utf-8",
    )

    report = build_base_status_report(
        database_path,
        legacy_english_path=english_path,
        condition="Chronic Pain",
    )

    reference = report["legacy_english_reference"]
    assert reference["available"] is True
    assert reference["total_records"] == 1
    assert reference["field_coverage"]["cannabinoids"]["count"] == 1
    assert reference["access_progress"]["pmcid_candidates"]["count"] == 1
    assert reference["access_progress"]["pmcid_candidates_remaining"] == 0
    assert reference["top_pathologies"] == [{"value": "Chronic Pain", "count": 1}]
    assert reference["top_organ_systems"] == [{"value": "Nervous System", "count": 1}]
    assert reference["top_cannabinoids"] == [{"value": "Cannabidiol (CBD)", "count": 1}]
