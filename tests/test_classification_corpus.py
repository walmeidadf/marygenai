from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification_corpus.pipeline import write_corpus_rollup
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def long_source_text(*, cannabinoid: bool) -> str:
    terms = "cannabis cannabidiol " if cannabinoid else ""
    section_text = "Abstract Introduction Methods Results Discussion Conclusion "
    return (terms + section_text + "pain clinical trial source text ") * 180


def create_minimal_corpus_inputs(data_dir: Path) -> None:
    publication = {
        "document_id": "publication:pmid:1",
        "legacy_study_id": "1",
        "primary_title": "Cannabis pain clinical trial",
        "publication_year": 2024,
        "pmid": "1",
        "pmcid": "PMC1",
        "doi": "10.1000/test",
        "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/1",
        "legacy_study_type": "Clinical Trial",
        "legacy_result": "Positive",
        "provenance": {"run_id": "input-run", "method": "test"},
    }
    write_jsonl(
        data_dir / "normalized/publications/20260515T120000Z_publication_candidates.jsonl",
        [publication],
    )
    write_jsonl(
        data_dir / "normalized/ontology/ontology_mappings/20260515T120000Z_ontology_entities.jsonl",
        [
            {
                "entity_id": "ontology:condition:pain",
                "entity_type": "medical_condition",
                "canonical_label": "Dor",
                "canonical_label_en": "Pain",
            },
            {
                "entity_id": "ontology:cannabinoid:cbd",
                "entity_type": "cannabinoid",
                "canonical_label": "Canabidiol",
                "canonical_label_en": "Cannabidiol",
            },
        ],
    )
    write_jsonl(
        data_dir
        / "normalized/ontology/ontology_mappings/20260515T120000Z_document_ontology_links.jsonl",
        [
            {
                "document_id": "publication:pmid:1",
                "entity_id": "ontology:condition:pain",
                "entity_type": "medical_condition",
            },
            {
                "document_id": "publication:pmid:1",
                "entity_id": "ontology:cannabinoid:cbd",
                "entity_type": "cannabinoid",
            },
        ],
    )

    broader_text_path = data_dir / "processed/official_source_fetch_router/pmc_oai/pub1.txt"
    broader_text_path.parent.mkdir(parents=True, exist_ok=True)
    broader_text_path.write_text(long_source_text(cannabinoid=False), encoding="utf-8")
    strict_text_path = data_dir / "processed/official_source_fetch_router/unpaywall_pdf/pub1.txt"
    strict_text_path.parent.mkdir(parents=True, exist_ok=True)
    strict_text_path.write_text(long_source_text(cannabinoid=True), encoding="utf-8")
    strict_raw_path = data_dir / "raw/official_source_fetch_router/unpaywall_pdf/pub1.pdf"
    strict_raw_path.parent.mkdir(parents=True, exist_ok=True)
    strict_raw_path.write_bytes(b"%PDF test")

    write_jsonl(
        data_dir
        / "normalized/official_source_fetch_router/"
        "20260601T120000Z_official_source_fetch_pmc_oai_acquire_records.jsonl",
        [
            {
                "document_id": "publication:pmid:1",
                "strategy": "pmc_oai",
                "url": "https://example.org/pmc",
                "final_url": None,
                "text_path": str(broader_text_path),
                "raw_xml_path": None,
                "extracted_text_chars": len(broader_text_path.read_text(encoding="utf-8")),
                "scientific_section_hit_count": 6,
                "cannabinoid_term_hit_count": 0,
                "failure_reason": None,
                "provenance": {"run_id": "source-run-a"},
            }
        ],
    )
    write_jsonl(
        data_dir
        / "normalized/official_source_fetch_router/"
        "20260601T120001Z_official_source_fetch_unpaywall_pdf_acquire_records.jsonl",
        [
            {
                "document_id": "publication:pmid:1",
                "strategy": "unpaywall_pdf",
                "url": "https://example.org/pdf",
                "final_url": None,
                "text_path": str(strict_text_path),
                "raw_xml_path": str(strict_raw_path),
                "extracted_text_chars": len(strict_text_path.read_text(encoding="utf-8")),
                "scientific_section_hit_count": 6,
                "cannabinoid_term_hit_count": 2,
                "failure_reason": None,
                "provenance": {"run_id": "source-run-b"},
            }
        ],
    )


def test_write_corpus_rollup_dedupes_and_writes_sample(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    create_minimal_corpus_inputs(data_dir)

    result = write_corpus_rollup(
        storage=LocalStorage(data_dir),
        run_id="20260615T120000Z",
        sample_size=1,
    )

    records_path = Path(result["records_path"])
    summary_path = Path(result["summary_path"])
    sample_path = Path(result["sample_paths"]["records"])
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sample = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 1
    assert records[0]["source_strategy"] == "unpaywall_pdf"
    assert records[0]["source_ready"] is True
    assert records[0]["classification_ready"] is True
    assert records[0]["classification_dataset_split"] == "strict_classification_ready"
    assert records[0]["trust_level"] == "source_text_available"
    assert records[0]["medical_condition_labels"] == ["Pain"]
    assert summary["counts"]["classification_ready"] == 1
    assert sample[0]["corpus_record"]["document_id"] == "publication:pmid:1"
    assert sample[0]["provenance"]["does_not_call_llm"] is True
