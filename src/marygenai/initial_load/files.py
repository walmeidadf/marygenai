from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from marygenai.schemas import InputArtifact, OutputArtifact

LEGACY_TABLE_FILENAMES = {
    "studies": "Estudos-Grid view.csv",
    "cannabinoids": "Canabinoides-Grid view.csv",
    "medical_conditions": "Condicoes Medicas-Grid view.csv",
    "organ_systems": "Sistemas do Organismo-Grid view.csv",
    "terpenes": "Terpenos-Grid view.csv",
    "glossary_terms": "Glossario-Grid view.csv",
}


def ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    folded = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    normalized = ascii_fold(title)
    return re.sub(r"\s+", " ", normalized) or None


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_artifact(path: Path) -> InputArtifact:
    return InputArtifact(
        path=str(path),
        sha256=file_sha256(path),
        size_bytes=path.stat().st_size,
    )


def output_artifact(path: Path, record_count: int) -> OutputArtifact:
    return OutputArtifact(path=str(path), record_count=record_count, sha256=file_sha256(path))


def resolve_legacy_csv(base_dir: Path, expected_filename: str) -> Path:
    exact_path = base_dir / expected_filename
    if exact_path.exists():
        return exact_path

    expected_key = ascii_fold(expected_filename)
    candidates = [path for path in base_dir.glob("*.csv") if ascii_fold(path.name) == expected_key]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise ValueError(f"Ambiguous legacy CSV match for {expected_filename}: {candidates}")
    raise FileNotFoundError(f"Missing legacy CSV {expected_filename} under {base_dir}")


def resolve_legacy_tables(base_dir: Path) -> dict[str, Path]:
    return {
        table_name: resolve_legacy_csv(base_dir, filename)
        for table_name, filename in LEGACY_TABLE_FILENAMES.items()
    }


def read_csv_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [(index, row) for index, row in enumerate(reader, start=2)]


def clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,;\n]+", value)
    return [part.strip() for part in parts if part.strip()]


def parse_legacy_study_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return re.findall(r"\d+", value)


def first_present(row: dict[str, str], fields: Iterable[str]) -> str | None:
    for field in fields:
        value = clean_value(row.get(field))
        if value:
            return value
    return None
