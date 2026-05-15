from __future__ import annotations

import re
from hashlib import sha256
from urllib.parse import unquote, urlparse

from marygenai.initial_load.files import normalize_title

PMID_RE = re.compile(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|/pubmed/)(\d+)", re.IGNORECASE)
PMCID_RE = re.compile(r"/pmc/articles/(PMC\d+)", re.IGNORECASE)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


def normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    host = host.lower().strip()
    return host[4:] if host.startswith("www.") else host


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme and not parsed.netloc:
        return url.strip()
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or parsed.path
    return parsed._replace(scheme=scheme, netloc=host, path=path, fragment="").geturl()


def extract_pmid(url: str | None) -> str | None:
    if not url:
        return None
    match = PMID_RE.search(unquote(url))
    return match.group(1) if match else None


def extract_pmcid(url: str | None) -> str | None:
    if not url:
        return None
    match = PMCID_RE.search(unquote(url))
    return match.group(1).upper() if match else None


def clean_doi(raw_doi: str) -> str:
    return raw_doi.rstrip(").,;]").lower()


def extract_doi(url: str | None) -> str | None:
    if not url:
        return None
    decoded_url = unquote(url)
    parsed = urlparse(decoded_url)
    if normalize_host(parsed.netloc) in {"doi.org", "dx.doi.org"}:
        path = parsed.path.strip("/")
        if path.startswith("10."):
            return clean_doi(path)

    match = DOI_RE.search(decoded_url)
    return clean_doi(match.group(0)) if match else None


def stable_document_id(
    *,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
    canonical_url: str | None,
    title: str | None,
    legacy_study_id: str,
) -> str:
    if pmid:
        return f"publication:pmid:{pmid}"
    if pmcid:
        return f"publication:pmcid:{pmcid}"
    if doi:
        return f"publication:doi:{sha256(doi.encode('utf-8')).hexdigest()[:16]}"
    if canonical_url:
        return f"publication:url:{sha256(canonical_url.encode('utf-8')).hexdigest()[:16]}"
    normalized_title = normalize_title(title)
    if normalized_title:
        return f"publication:title:{sha256(normalized_title.encode('utf-8')).hexdigest()[:16]}"
    return f"publication:legacy:{legacy_study_id}"
