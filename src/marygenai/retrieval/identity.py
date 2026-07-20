from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

IdentifierType = Literal["pmid", "pmcid", "doi"]

_PMID = re.compile(r"^\d{5,9}$")
_PMCID = re.compile(r"^PMC\d+$", re.IGNORECASE)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_FRONTIERS_FULL = re.compile(r"^(10\.3389/[^?#\s]+?)/full(?:[?#].*)?$", re.IGNORECASE)
_PUBMED_URL = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{5,9})(?:/|$)", re.IGNORECASE)
_PMC_URL = re.compile(r"(?:articles/|identifier=oai:pubmedcentral\.nih\.gov:)(PMC?\d+)", re.I)
_DOI_URL = re.compile(r"doi\.org/(10\.\d{4,9}/[^?#\s]+)", re.I)


def normalize_identifier(kind: IdentifierType, value: Any) -> tuple[str | None, str | None]:
    """Normalize a structured bibliographic identifier conservatively."""
    if value is None:
        return None, None
    raw = unquote(str(value)).strip().strip("<>\"'")
    if not raw:
        return None, None
    if kind == "pmid":
        raw = re.sub(r"^(?:PMID:|https?://pubmed\.ncbi\.nlm\.nih\.gov/)", "", raw, flags=re.I)
        value = raw.rstrip("/")
        return (value, "trim_prefix_and_slash.v1") if _PMID.fullmatch(value) else (None, None)
    if kind == "pmcid":
        raw = re.sub(r"^https?://pmc\.ncbi\.nlm\.nih\.gov/articles/", "", raw, flags=re.I)
        value = raw.rstrip("/").upper()
        return (value, "uppercase_and_trim_route.v1") if _PMCID.fullmatch(value) else (None, None)

    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw, flags=re.I).lower()
    frontiers = _FRONTIERS_FULL.fullmatch(value)
    if frontiers:
        return frontiers.group(1), "frontiers_full_route_suffix.v1"
    value = value.rstrip(".,;)")
    return (value, "lowercase_and_trim_punctuation.v1") if _DOI.fullmatch(value) else (None, None)


def _artifact_record(
    *,
    source_kind: str,
    source_artifact_path: str,
    extraction_method: str,
    raw_value: Any,
    normalization_rule: str | None,
) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "source_artifact_path": source_artifact_path,
        "extraction_method": extraction_method,
        "raw_value": str(raw_value),
        "normalization_rule": normalization_rule,
    }


def _extract_article_metadata(path: Path) -> list[tuple[IdentifierType, str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")[:500_000]
    article_meta_match = re.search(r"<article-meta\b.*?</article-meta>", text, re.I | re.S)
    article_meta = article_meta_match.group(0) if article_meta_match else ""
    found: list[tuple[IdentifierType, str, str]] = []
    for kind in ("pmid", "pmcid", "doi"):
        article_id_pattern = rf'<article-id[^>]+pub-id-type=["\']{kind}["\'][^>]*>([^<]+)'
        for match in re.finditer(article_id_pattern, article_meta, re.IGNORECASE):
            found.append((kind, match.group(1), "nxml_article_id"))
        patterns = (
            (
                rf'<meta[^>]+name=["\']citation_{kind}["\'][^>]+content=["\']([^"\']+)',
                "html_citation_meta",
            ),
            (
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_{kind}["\']',
                "html_citation_meta",
            ),
        )
        for pattern, method in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                found.append((kind, match.group(1), method))
    return found


def _identity_from_url(url: str | None) -> list[tuple[IdentifierType, str, str]]:
    if not url:
        return []
    found: list[tuple[IdentifierType, str, str]] = []
    for kind, pattern in (("pmid", _PUBMED_URL), ("pmcid", _PMC_URL), ("doi", _DOI_URL)):
        match = pattern.search(unquote(url))
        if match:
            value = match.group(1)
            if kind == "pmcid" and not value.upper().startswith("PMC"):
                value = f"PMC{value}"
            found.append((kind, value, "structured_url"))
    return found


def _load_cached_identity(
    data_dir: Path, document_ids: set[str]
) -> dict[str, list[tuple[IdentifierType, Any, str, str]]]:
    found: dict[str, list[tuple[IdentifierType, Any, str, str]]] = defaultdict(list)
    router_dir = data_dir / "normalized/official_source_fetch_router"
    for path in sorted(router_dir.glob("*_records.jsonl")):
        with path.open(encoding="utf-8", errors="ignore") as file:
            for line in file:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                document_id = row.get("document_id")
                if document_id not in document_ids:
                    continue
                strategy = row.get("strategy") or "routing_record"
                for kind in ("pmid", "pmcid", "doi"):
                    if row.get(kind):
                        found[document_id].append(
                            (kind, row[kind], str(path), f"{strategy}_{kind}")
                        )
                raw_path = row.get("raw_json_path")
                resolved_raw = data_dir.parent / raw_path if raw_path else None
                if resolved_raw and resolved_raw.exists():
                    try:
                        payload = json.loads(resolved_raw.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    identifiers = payload.get("ids") or {}
                    for kind in ("pmid", "pmcid", "doi"):
                        if identifiers.get(kind):
                            found[document_id].append(
                                (
                                    kind,
                                    identifiers[kind],
                                    str(resolved_raw),
                                    f"{strategy}_ids_object",
                                )
                            )
                source_artifact = row.get("raw_xml_path")
                resolved_source = data_dir.parent / source_artifact if source_artifact else None
                if resolved_source and resolved_source.exists():
                    for kind, value, method in _extract_article_metadata(resolved_source):
                        found[document_id].append(
                            (
                                kind,
                                value,
                                str(resolved_source),
                                f"{strategy}_{method}",
                            )
                        )
    return found


def project_bibliographic_identities(
    *,
    data_dir: Path,
    corpus: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a local-only identity projection without changing source artifacts."""
    document_ids = {row["document_id"] for row in candidates}
    cached = _load_cached_identity(data_dir, document_ids)
    projections: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        document_id = candidate["document_id"]
        corpus_row = corpus[document_id]
        values: dict[IdentifierType, dict[str, list[dict[str, Any]]]] = {
            "pmid": defaultdict(list),
            "pmcid": defaultdict(list),
            "doi": defaultdict(list),
        }

        def add(
            kind: IdentifierType,
            raw: Any,
            source_kind: str,
            path: str,
            method: str,
            destination: dict[IdentifierType, dict[str, list[dict[str, Any]]]] = values,
        ) -> None:
            normalized, rule = normalize_identifier(kind, raw)
            if normalized is None:
                return
            provenance = _artifact_record(
                source_kind=source_kind,
                source_artifact_path=path,
                extraction_method=method,
                raw_value=raw,
                normalization_rule=rule,
            )
            if provenance not in destination[kind][normalized]:
                destination[kind][normalized].append(provenance)

        for kind in ("pmid", "pmcid", "doi"):
            if corpus_row.get(kind):
                add(
                    kind,
                    corpus_row[kind],
                    "classification_corpus",
                    "classification_corpus",
                    f"corpus_{kind}",
                )
        for field in ("canonical_url", "source_url"):
            for kind, raw, method in _identity_from_url(corpus_row.get(field)):
                add(
                    kind, raw, "classification_corpus", "classification_corpus", f"{field}_{method}"
                )
        source_path = Path(candidate["source_text_path"])
        resolved_source = (
            source_path if source_path.is_absolute() else data_dir.parent / source_path
        )
        for kind, raw, method in _extract_article_metadata(resolved_source):
            add(kind, raw, "primary_article_metadata", str(source_path), method)
        for kind, raw, path, method in cached.get(document_id, []):
            add(kind, raw, "cached_enrichment_metadata", path, method)

        identifiers: list[dict[str, Any]] = []
        projected: dict[str, str | None] = {}
        conflicts: list[dict[str, Any]] = []
        for kind in ("pmid", "pmcid", "doi"):
            candidates_by_value = values[kind]
            status = (
                "accepted"
                if len(candidates_by_value) == 1
                else "conflict"
                if candidates_by_value
                else "unavailable"
            )
            value = next(iter(candidates_by_value)) if status == "accepted" else None
            projected[kind] = value
            candidate_values = [
                {"value": item, "provenance": provenance}
                for item, provenance in sorted(candidates_by_value.items())
            ]
            identifiers.append(
                {
                    "identifier_type": kind,
                    "value": value,
                    "status": status,
                    "candidate_values": candidate_values,
                }
            )
            if status == "conflict":
                conflicts.append({"identifier_type": kind, "candidate_values": candidate_values})

        urls = build_identity_urls(corpus_row, projected)
        projections[document_id] = {
            **projected,
            "status": "conflict" if conflicts else "consistent",
            "identifiers": identifiers,
            "conflicts": conflicts,
            "identity_urls": urls,
            "preferred_access_url": choose_preferred_access_url(urls),
        }
    return projections


def build_identity_urls(
    corpus_row: dict[str, Any], projected: dict[str, str | None]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    derived = (
        (
            "pmcid",
            "PMC full text",
            "pmc_full_text",
            lambda v: f"https://pmc.ncbi.nlm.nih.gov/articles/{v}/",
        ),
        ("pmid", "PubMed", "pubmed", lambda v: f"https://pubmed.ncbi.nlm.nih.gov/{v}/"),
        ("doi", "DOI", "doi", lambda v: f"https://doi.org/{v}"),
    )
    for kind, label, url_kind, builder in derived:
        value = projected.get(kind)
        if value:
            rows.append(
                {
                    "label": label,
                    "url": builder(value),
                    "url_kind": url_kind,
                    "physician_facing": True,
                    "derived_from": {"identifier_type": kind, "value": value},
                }
            )
    for field, label, url_kind in (
        ("canonical_url", "Canonical source", "canonical"),
        ("source_url", "Acquisition source", "source"),
    ):
        url = corpus_row.get(field)
        if url and not any(item["url"] == url for item in rows):
            machine = "/api/oai/" in url or "webservices/rest" in url or "api.openalex.org" in url
            rows.append(
                {
                    "label": label,
                    "url": url,
                    "url_kind": url_kind,
                    "physician_facing": not machine,
                    "derived_from": None,
                }
            )
    return rows


def choose_preferred_access_url(urls: list[dict[str, Any]]) -> dict[str, Any] | None:
    priorities = ("pmc_full_text", "pubmed", "doi", "canonical", "source")
    for kind in priorities:
        for row in urls:
            if row["url_kind"] == kind and row["physician_facing"]:
                return {**row, "selection_rule": f"preferred_physician_facing_{kind}.v1"}
    return None
