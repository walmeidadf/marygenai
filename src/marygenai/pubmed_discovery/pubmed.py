from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from lxml import etree

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CANNABINOID_QUERY = (
    '("cannabis"[Title/Abstract] OR "cannabinoid"[Title/Abstract] OR '
    '"cannabinoids"[Title/Abstract] OR "cannabidiol"[Title/Abstract] OR '
    '"CBD"[Title/Abstract] OR "THC"[Title/Abstract] OR '
    '"tetrahydrocannabinol"[Title/Abstract])'
)
STRONG_EVIDENCE_QUERY = (
    '("systematic review"[Publication Type] OR "meta-analysis"[Publication Type] OR '
    '"randomized controlled trial"[Publication Type] OR '
    '"controlled clinical trial"[Publication Type] '
    'OR randomized[Title/Abstract] OR randomised[Title/Abstract] OR controlled[Title/Abstract] '
    'OR "double-blind"[Title/Abstract] OR placebo[Title/Abstract])'
)
PRIORITY_AREAS = {
    "pain": '("pain"[Title/Abstract] OR "chronic pain"[Title/Abstract])',
    "epilepsy": '("epilepsy"[Title/Abstract] OR "seizure"[Title/Abstract])',
    "adverse_effects": (
        '("adverse effects"[Title/Abstract] OR "adverse events"[Title/Abstract] '
        'OR safety[Title/Abstract])'
    ),
    "dependence": '("dependence"[Title/Abstract] OR addiction[Title/Abstract])',
    "anxiety": '("anxiety"[Title/Abstract] OR anxiolytic[Title/Abstract])',
    "cancer": '("cancer"[Title/Abstract] OR oncology[Title/Abstract] OR tumor[Title/Abstract])',
    "inflammation": (
        '("inflammation"[Title/Abstract] OR inflammatory[Title/Abstract] '
        'OR anti-inflammatory[Title/Abstract])'
    ),
}
QUERY_BATCHES = {
    "strong_evidence_all": f"{CANNABINOID_QUERY} AND {STRONG_EVIDENCE_QUERY}",
    **{
        f"strong_evidence_{area}": (
            f"{CANNABINOID_QUERY} AND {STRONG_EVIDENCE_QUERY} AND {area_query}"
        )
        for area, area_query in PRIORITY_AREAS.items()
    },
}
STUDY_DESIGN_RANKS = {
    "case_report": 10,
    "case_series": 20,
    "case_control": 30,
    "cohort_study": 40,
    "controlled_clinical_trial": 50,
    "randomized_controlled_trial": 60,
    "systematic_review": 70,
    "meta_analysis": 80,
}


@dataclass(frozen=True)
class PubMedRecord:
    pmid: str
    doi: str | None
    pmcid: str | None
    title: str | None
    abstract: str | None
    journal: str | None
    publication_date: str | None
    publication_status: str | None
    publication_types: list[str]
    mesh_terms: list[str]
    authors: list[str]
    languages: list[str]
    chemicals: list[str]
    keywords: list[str]
    article_ids: dict[str, str]
    provenance: dict[str, Any]


class PubMedClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        email: str | None,
        tool: str = "marygenai_pubmed_discovery",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.email = email
        self.tool = tool
        self.client = httpx.Client(base_url=EUTILS_BASE_URL, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = {"tool": self.tool, **extra}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    def search(
        self,
        query: str,
        *,
        retmax: int,
        sort: str,
        datetype: str | None = None,
        mindate: str | None = None,
        maxdate: str | None = None,
    ) -> dict[str, Any]:
        params = {"db": "pubmed", "term": query, "retmode": "json", "retmax": retmax, "sort": sort}
        if datetype:
            params["datetype"] = datetype
        if mindate:
            params["mindate"] = mindate
        if maxdate:
            params["maxdate"] = maxdate
        response = self.client.get("/esearch.fcgi", params=self.params(params))
        response.raise_for_status()
        return response.json()["esearchresult"]

    def fetch_xml(self, pmids: list[str]) -> str:
        response = self.client.get(
            "/efetch.fcgi",
            params=self.params({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}),
        )
        response.raise_for_status()
        return response.text


def pubmed_canonical_url(pmid: str) -> str:
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"


def parse_pubmed_xml(xml_text: str, *, query: str, fetched_at: str) -> list[PubMedRecord]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    return [
        parse_pubmed_article(article, query=query, fetched_at=fetched_at)
        for article in root.xpath(".//PubmedArticle")
    ]


def parse_pubmed_article(article: etree._Element, *, query: str, fetched_at: str) -> PubMedRecord:
    pmid = text_or_none(article.find(".//MedlineCitation/PMID"))
    if not pmid:
        raise ValueError("PubMed article is missing a PMID.")
    article_ids = parse_article_ids(article)
    return PubMedRecord(
        pmid=pmid,
        doi=parse_doi(article),
        pmcid=article_ids.get("pmc"),
        title=all_text(article.find(".//Article/ArticleTitle")),
        abstract="\n".join(node_texts(article, ".//Article/Abstract/AbstractText")) or None,
        journal=all_text(article.find(".//Article/Journal/Title")),
        publication_date=parse_publication_date(article),
        publication_status=all_text(article.find(".//PubmedData/PublicationStatus")),
        publication_types=node_texts(article, ".//Article/PublicationTypeList/PublicationType"),
        mesh_terms=node_texts(
            article,
            ".//MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName",
        ),
        authors=[
            author_name
            for author in article.xpath(".//Article/AuthorList/Author")
            if (author_name := parse_author(author))
        ],
        languages=node_texts(article, ".//Article/Language"),
        chemicals=node_texts(article, ".//MedlineCitation/ChemicalList/Chemical/NameOfSubstance"),
        keywords=node_texts(article, ".//MedlineCitation/KeywordList/Keyword"),
        article_ids=article_ids,
        provenance={
            "source": "pubmed",
            "method": "ncbi_eutils_esearch_efetch",
            "query": query,
            "fetched_at": fetched_at,
        },
    )


def text_or_none(node: etree._Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value or None


def all_text(node: etree._Element | None) -> str | None:
    if node is None:
        return None
    value = " ".join(" ".join(node.itertext()).split())
    return value or None


def node_texts(root: etree._Element, xpath: str) -> list[str]:
    return [value for node in root.xpath(xpath) if (value := all_text(node))]


def parse_author(author: etree._Element) -> str | None:
    collective_name = text_or_none(author.find("CollectiveName"))
    if collective_name:
        return collective_name
    last_name = text_or_none(author.find("LastName"))
    fore_name = text_or_none(author.find("ForeName"))
    initials = text_or_none(author.find("Initials"))
    if last_name and fore_name:
        return f"{fore_name} {last_name}"
    if last_name and initials:
        return f"{initials} {last_name}"
    return last_name


def parse_publication_date(article: etree._Element) -> str | None:
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        year = text_or_none(article_date.find("Year"))
        month = text_or_none(article_date.find("Month"))
        day = text_or_none(article_date.find("Day"))
        if year and month and day:
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year = text_or_none(pub_date.find("Year"))
    medline_date = text_or_none(pub_date.find("MedlineDate"))
    if not year:
        return medline_date
    parts = [year]
    if month := text_or_none(pub_date.find("Month")):
        parts.append(month)
    if day := text_or_none(pub_date.find("Day")):
        parts.append(day)
    return "-".join(parts)


def parse_doi(article: etree._Element) -> str | None:
    for location_id in article.xpath(".//ELocationID[@EIdType='doi']"):
        if value := text_or_none(location_id):
            return value
    return parse_article_ids(article).get("doi")


def parse_article_ids(article: etree._Element) -> dict[str, str]:
    article_ids: dict[str, str] = {}
    for article_id in article.xpath(".//ArticleIdList/ArticleId"):
        id_type = article_id.get("IdType")
        value = text_or_none(article_id)
        if id_type and value:
            article_ids[id_type] = value
    return article_ids


def cannabinoid_focus(record: PubMedRecord) -> str:
    terms = (
        "cannabis",
        "cannabinoid",
        "cannabinoids",
        "cannabidiol",
        "tetrahydrocannabinol",
        "marijuana",
        "thc",
        "cbd",
    )
    title = (record.title or "").lower()
    indexed_text = " ".join([*record.mesh_terms, *record.chemicals, *record.keywords]).lower()
    abstract = (record.abstract or "").lower()
    if any(term in title for term in terms) or any(term in indexed_text for term in terms):
        return "direct_title_or_indexed"
    if any(term in abstract for term in terms):
        return "abstract_only"
    return "no_cannabinoid_signal"


def searchable_text(record: PubMedRecord) -> str:
    parts = [
        record.title,
        record.abstract,
        " ".join(record.publication_types),
        " ".join(record.mesh_terms),
        " ".join(record.keywords),
    ]
    return " ".join(part for part in parts if part).lower()


def infer_study_design(record: PubMedRecord) -> tuple[str | None, int, list[str]]:
    text = searchable_text(record)
    publication_types = {value.lower() for value in record.publication_types}
    if "meta-analysis" in publication_types or "meta analysis" in text:
        return "meta_analysis", STUDY_DESIGN_RANKS["meta_analysis"], ["study_design:meta_analysis"]
    if "systematic review" in publication_types or "systematic review" in text:
        return (
            "systematic_review",
            STUDY_DESIGN_RANKS["systematic_review"],
            ["study_design:systematic_review"],
        )
    if any("randomized controlled trial" in value for value in publication_types) or any(
        term in text for term in ("randomized", "randomised")
    ):
        return (
            "randomized_controlled_trial",
            STUDY_DESIGN_RANKS["randomized_controlled_trial"],
            ["study_design:randomized_controlled_trial"],
        )
    if any("controlled clinical trial" in value for value in publication_types) or (
        "controlled clinical trial" in text
    ):
        return (
            "controlled_clinical_trial",
            STUDY_DESIGN_RANKS["controlled_clinical_trial"],
            ["study_design:controlled_clinical_trial"],
        )
    if "cohort" in text:
        return "cohort_study", STUDY_DESIGN_RANKS["cohort_study"], ["study_design:cohort_study"]
    if "case-control" in text or "case control" in text:
        return "case_control", STUDY_DESIGN_RANKS["case_control"], ["study_design:case_control"]
    if "case series" in text:
        return "case_series", STUDY_DESIGN_RANKS["case_series"], ["study_design:case_series"]
    if "case reports" in publication_types or "case report" in text:
        return "case_report", STUDY_DESIGN_RANKS["case_report"], ["study_design:case_report"]
    return None, 0, ["study_design:unclassified"]


def score_pubmed_record(record: PubMedRecord) -> tuple[int, list[str]]:
    text = searchable_text(record)
    publication_types = {value.lower() for value in record.publication_types}
    focus = cannabinoid_focus(record)
    study_design, study_design_rank, reasons = infer_study_design(record)
    score = study_design_rank
    if focus == "direct_title_or_indexed":
        score += 20
        reasons.append("direct_cannabinoid_focus")
    elif focus == "abstract_only":
        score -= 60
        reasons.append("abstract_only_cannabinoid_signal")
    else:
        score -= 100
        reasons.append("missing_cannabinoid_signal")
    if study_design in {"systematic_review", "meta_analysis"}:
        if any(term in text for term in ("randomized controlled trial", "randomised")):
            score += 10
            reasons.append("review_includes_randomized_trials")
        if "placebo" in text:
            score += 5
            reasons.append("review_includes_placebo_comparators")
    else:
        if "double-blind" in text or "double blind" in text:
            score += 15
            reasons.append("double_blind")
        if "placebo" in text:
            score += 15
            reasons.append("placebo_controlled")
    if "humans" in text or any("clinical trial" in value for value in publication_types):
        score += 15
        reasons.append("human_evidence")
    if "animals" in text:
        score -= 8
        reasons.append("animal_signal")
    if "in vitro" in text:
        score -= 12
        reasons.append("in_vitro_signal")
    matched_areas = [
        area
        for area in PRIORITY_AREAS
        if area.replace("_", " ") in text or area.replace("_", "-") in text
    ]
    if matched_areas:
        score += 15
        reasons.append("priority_condition:" + ",".join(sorted(matched_areas)))
    if record.doi:
        score += 5
        reasons.append("has_doi")
    if record.pmcid:
        score += 5
        reasons.append("has_pmcid")
    if record.abstract:
        score += 8
        reasons.append("has_abstract")
    year = parse_publication_year(record.publication_date)
    if year and year >= 2020:
        score += 10
        reasons.append("recent_2020_or_later")
    elif year and year >= 2015:
        score += 6
        reasons.append("recent_2015_or_later")
    elif year and year >= 2010:
        score += 3
        reasons.append("recent_2010_or_later")
    return score, reasons


def classify_full_text_review_priority(
    record: PubMedRecord,
    *,
    priority_score: int,
    score_reasons: list[str],
) -> str:
    if priority_score < 70:
        return "low"
    high_value_reason = any(
        reason in score_reasons
        for reason in (
            "study_design:meta_analysis",
            "study_design:systematic_review",
            "study_design:randomized_controlled_trial",
            "study_design:controlled_clinical_trial",
            "placebo_controlled",
            "double_blind",
        )
    )
    if record.pmcid and high_value_reason:
        return "high_auto_full_text"
    if high_value_reason:
        return "high_manual_full_text"
    if record.pmcid:
        return "medium_auto_full_text"
    if record.doi:
        return "medium_manual_full_text"
    return "low"


def parse_publication_year(value: str | None) -> int | None:
    if not value:
        return None
    year = value[:4]
    return int(year) if year.isdigit() else None
