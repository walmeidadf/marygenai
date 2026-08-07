from __future__ import annotations

from typing import Any

import httpx

EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_ARTICLE_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PMC_ARTICLE_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/articles"
UNPAYWALL_BASE_URL = "https://api.unpaywall.org/v2"


class EuropePmcClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def search_by_pmid_or_doi(self, *, pmid: str | None, doi: str | None) -> dict[str, Any] | None:
        if pmid:
            query = f"EXT_ID:{pmid} AND SRC:MED"
        elif doi:
            query = f'DOI:"{doi}"'
        else:
            return None
        response = self.client.get(
            EUROPE_PMC_SEARCH_URL,
            params={"query": query, "format": "json", "resultType": "core", "pageSize": 1},
        )
        response.raise_for_status()
        return response.json()

    def fetch_full_text_xml(self, *, source: str, identifier: str) -> bytes:
        response = self.client.get(
            f"{EUROPE_PMC_ARTICLE_BASE_URL}/{source}/{identifier}/fullTextXML"
        )
        response.raise_for_status()
        return response.content

    def fetch_full_text_xml_by_pmcid(self, pmcid: str) -> bytes:
        response = self.client.get(
            f"{EUROPE_PMC_ARTICLE_BASE_URL}/{pmcid}/fullTextXML"
        )
        response.raise_for_status()
        return response.content


class PmcClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def fetch_nxml(self, pmcid: str) -> bytes:
        response = self.client.get(f"{PMC_ARTICLE_BASE_URL}/{pmcid}/?report=xml")
        response.raise_for_status()
        return response.content

    def fetch_html(self, pmcid: str) -> bytes:
        response = self.client.get(f"{PMC_ARTICLE_BASE_URL}/{pmcid}/")
        response.raise_for_status()
        return response.content


class UnpaywallClient:
    def __init__(self, *, email: str, timeout_seconds: float = 30.0) -> None:
        self.email = email
        self.client = httpx.Client(base_url=UNPAYWALL_BASE_URL, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def get_by_doi(self, doi: str) -> dict[str, Any]:
        response = self.client.get(f"/{doi}", params={"email": self.email})
        if response.status_code == 404:
            return {"doi": doi, "not_found": True}
        response.raise_for_status()
        return response.json()
