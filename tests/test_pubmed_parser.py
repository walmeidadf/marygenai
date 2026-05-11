from pocs.pubmed.validate_pubmed import parse_pubmed_xml

SAMPLE_XML = """\
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345</PMID>
      <ChemicalList>
        <Chemical>
          <NameOfSubstance>Cannabidiol</NameOfSubstance>
        </Chemical>
      </ChemicalList>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName>Cannabinoids</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
      <Article>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
              <Month>05</Month>
              <Day>01</Day>
            </PubDate>
          </JournalIssue>
          <Title>Example Journal</Title>
        </Journal>
        <ArticleTitle>Cannabinoid evidence test.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">First section.</AbstractText>
          <AbstractText Label="METHODS">Second section.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>Jane</ForeName>
          </Author>
          <Author>
            <CollectiveName>Research Group</CollectiveName>
          </Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Review</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">12345</ArticleId>
        <ArticleId IdType="doi">10.1000/example</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parse_pubmed_xml_extracts_validation_fields() -> None:
    records = parse_pubmed_xml(SAMPLE_XML, query="cannabinoid", fetched_at="2026-05-11T00:00:00Z")

    assert len(records) == 1
    record = records[0]
    assert record.pmid == "12345"
    assert record.doi == "10.1000/example"
    assert record.title == "Cannabinoid evidence test."
    assert record.abstract == "First section.\nSecond section."
    assert record.journal == "Example Journal"
    assert record.publication_date == "2024-05-01"
    assert record.publication_types == ["Journal Article", "Review"]
    assert record.mesh_terms == ["Cannabinoids"]
    assert record.authors == ["Jane Smith", "Research Group"]
    assert record.languages == ["eng"]
    assert record.chemicals == ["Cannabidiol"]
    assert record.provenance["source"] == "pubmed"
