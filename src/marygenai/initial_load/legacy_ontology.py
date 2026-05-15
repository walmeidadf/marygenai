from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marygenai.initial_load.files import (
    clean_value,
    first_present,
    normalize_title,
    parse_legacy_study_ids,
    read_csv_rows,
    split_list,
    stable_hash,
)
from marygenai.schemas import DocumentOntologyLink, LegacySourceRecord, OntologyEntity, Provenance


@dataclass(frozen=True)
class OntologyTableConfig:
    table_name: str
    entity_type: str
    label_fields: tuple[str, ...]
    english_label_fields: tuple[str, ...] = ()
    slug_field: str | None = "tag"
    alias_fields: tuple[str, ...] = ()
    description_fields: tuple[str, ...] = ()
    studies_field: str = "Estudos"


ONTOLOGY_TABLES = {
    "cannabinoids": OntologyTableConfig(
        table_name="cannabinoids",
        entity_type="cannabinoid",
        label_fields=("Cabinóide",),
        english_label_fields=("english",),
        alias_fields=("Nomes", "Ligantes"),
        description_fields=("Descrição", "Propriedades"),
    ),
    "medical_conditions": OntologyTableConfig(
        table_name="medical_conditions",
        entity_type="medical_condition",
        label_fields=("Condição Médica",),
        english_label_fields=("Condição Médica em inglês",),
        alias_fields=("Outros nomes", "Condições", "Família de Doenças"),
        description_fields=("Descrição da condição médica", "Diretrizes"),
    ),
    "organ_systems": OntologyTableConfig(
        table_name="organ_systems",
        entity_type="organ_system",
        label_fields=("Sistema do Organismo",),
        english_label_fields=("Sistema de Órgãos em inglês",),
        alias_fields=("Sinônimos", "Especialidades"),
        description_fields=("Sinópse da Pesquisa", "Descrição", "Diretrizes"),
    ),
    "terpenes": OntologyTableConfig(
        table_name="terpenes",
        entity_type="terpene",
        label_fields=("Terpeno",),
        english_label_fields=("english",),
        alias_fields=("Outros Nomes", "Descrição do Aroma", "Fontes Naturais"),
        description_fields=("Sumário", "Propriedades e Efeitos"),
    ),
    "glossary_terms": OntologyTableConfig(
        table_name="glossary_terms",
        entity_type="glossary_term",
        label_fields=("Palavra em Português",),
        slug_field=None,
        description_fields=("Significado em Português",),
        studies_field="",
    ),
}


def build_ontology_source_record(
    *,
    table_name: str,
    row: dict[str, str],
    row_number: int,
    source_file: Path,
    run_id: str,
) -> LegacySourceRecord:
    row_hash = stable_hash(row)
    return LegacySourceRecord(
        source_record_id=f"legacy_cannadocs:{table_name}:{row_hash[:16]}",
        source_table=table_name,
        row_number=row_number,
        payload_hash=row_hash,
        raw_payload=row,
        provenance=Provenance(
            source="legacy_cannadocs",
            source_file=str(source_file),
            source_row_number=row_number,
            method="legacy_initial_load",
            run_id=run_id,
        ),
    )


def build_entity(
    *,
    config: OntologyTableConfig,
    row: dict[str, str],
    row_number: int,
    source_file: Path,
    run_id: str,
) -> OntologyEntity:
    canonical_label = first_present(row, config.label_fields)
    if not canonical_label:
        raise ValueError(f"Missing ontology label in {source_file} row {row_number}")

    slug = clean_value(row.get(config.slug_field)) if config.slug_field else None
    label_key = slug or normalize_title(canonical_label) or stable_hash(row)[:16]
    entity_id = f"ontology:{config.entity_type}:{label_key}"
    descriptions = {
        field: value
        for field in config.description_fields
        if (value := clean_value(row.get(field)))
    }

    aliases: list[str] = []
    for field in config.alias_fields:
        aliases.extend(split_list(row.get(field)))
    aliases = sorted({alias for alias in aliases if alias != canonical_label})

    return OntologyEntity(
        entity_id=entity_id,
        entity_type=config.entity_type,  # type: ignore[arg-type]
        canonical_label=canonical_label,
        canonical_label_en=first_present(row, config.english_label_fields),
        slug=slug,
        aliases=aliases,
        descriptions=descriptions,
        legacy_fields={key: value for key, value in row.items() if clean_value(value)},
        provenance=Provenance(
            source="legacy_cannadocs",
            source_file=str(source_file),
            source_row_number=row_number,
            method="legacy_initial_load",
            run_id=run_id,
        ),
    )


def build_links(
    *,
    entity: OntologyEntity,
    config: OntologyTableConfig,
    row: dict[str, str],
    legacy_id_to_document_id: dict[str, str],
    row_number: int,
    source_file: Path,
    run_id: str,
) -> list[DocumentOntologyLink]:
    if not config.studies_field:
        return []

    links: list[DocumentOntologyLink] = []
    for legacy_study_id in parse_legacy_study_ids(row.get(config.studies_field)):
        document_id = legacy_id_to_document_id.get(legacy_study_id)
        if not document_id:
            continue
        link_hash = stable_hash(
            {
                "document_id": document_id,
                "entity_id": entity.entity_id,
                "legacy_study_id": legacy_study_id,
            }
        )
        links.append(
            DocumentOntologyLink(
                link_id=f"document_ontology_link:{link_hash[:24]}",
                document_id=document_id,
                legacy_study_id=legacy_study_id,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                evidence_text=(
                    f"{config.table_name}.Estudos contains legacy study id {legacy_study_id}"
                ),
                provenance=Provenance(
                    source="legacy_cannadocs",
                    source_file=str(source_file),
                    source_row_number=row_number,
                    method="legacy_initial_load",
                    run_id=run_id,
                ),
            )
        )
    return links


def import_legacy_ontology(
    *,
    table_paths: dict[str, Path],
    legacy_id_to_document_id: dict[str, str],
    run_id: str,
) -> tuple[list[LegacySourceRecord], list[OntologyEntity], list[DocumentOntologyLink]]:
    source_records: list[LegacySourceRecord] = []
    entities: list[OntologyEntity] = []
    links: list[DocumentOntologyLink] = []

    for table_name, config in ONTOLOGY_TABLES.items():
        source_file = table_paths[table_name]
        for row_number, row in read_csv_rows(source_file):
            source_records.append(
                build_ontology_source_record(
                    table_name=table_name,
                    row=row,
                    row_number=row_number,
                    source_file=source_file,
                    run_id=run_id,
                )
            )
            entity = build_entity(
                config=config,
                row=row,
                row_number=row_number,
                source_file=source_file,
                run_id=run_id,
            )
            entities.append(entity)
            links.extend(
                build_links(
                    entity=entity,
                    config=config,
                    row=row,
                    legacy_id_to_document_id=legacy_id_to_document_id,
                    row_number=row_number,
                    source_file=source_file,
                    run_id=run_id,
                )
            )

    return source_records, entities, links
