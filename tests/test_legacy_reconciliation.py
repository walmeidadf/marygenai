from pocs.legacy_reconciliation.reconcile_legacy import (
    build_record,
    extract_doi,
    extract_pmcid,
    extract_pmid,
    normalize_title,
)


def test_extract_pmid_from_pubmed_urls() -> None:
    assert extract_pmid("https://pubmed.ncbi.nlm.nih.gov/35319936/") == "35319936"
    assert extract_pmid("https://www.ncbi.nlm.nih.gov/pubmed/27094344") == "27094344"


def test_extract_pmcid_from_pmc_url() -> None:
    url = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7235264/"
    assert extract_pmcid(url) == "PMC7235264"


def test_extract_doi_from_doi_and_publisher_urls() -> None:
    assert extract_doi("https://doi.org/10.1000/Example") == "10.1000/example"
    assert (
        extract_doi("https://www.bmj.com/content/323/7303/16.full?doi=10.1136/bmj.323.7303.16")
        == "10.1136/bmj.323.7303.16"
    )


def test_build_record_prefers_pmid_as_stable_identifier() -> None:
    record = build_record(
        {
            "ID do Estudo": "1",
            "Título": "Título em português",
            "Título do artigo em inglês": "Cannabis Use Example.",
            "Domínio onde estudo foi publicado": "nlm.nih.gov",
            "URL do estudo": "https://pubmed.ncbi.nlm.nih.gov/35319936/",
            "Tipo de Estudo": "Metanálise",
            "Ano de Publicação": "2022",
        }
    )

    assert record.pmid == "35319936"
    assert record.stable_identifier == "35319936"
    assert record.stable_identifier_type == "pmid"
    assert record.source_class == "pubmed_record_page"
    assert not record.needs_manual_review


def test_normalize_title_removes_accents_and_punctuation() -> None:
    assert normalize_title("Canabidiol como Tratamento: revisão.") == (
        "canabidiol como tratamento revisao"
    )
