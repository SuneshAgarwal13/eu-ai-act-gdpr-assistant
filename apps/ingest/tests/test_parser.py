from pathlib import Path

import pytest
from ingest.chunks import build_chunks
from ingest.documents import DocumentSource
from ingest.parser import parse_document
from ingest.references import extract_cross_references

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.xhtml"
TEST_SOURCE = DocumentSource(
    slug="test_doc", name="Test Document", celex_id="00000000", eli_uri="http://example.com"
)


@pytest.fixture
def fixture_xhtml() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_document_extracts_chapter_section_article_structure(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)

    assert len(doc.articles) == 2

    article_1, article_2 = doc.articles
    assert article_1.number == "1"
    assert article_1.title == "Subject matter"
    assert article_1.chapter_number == "I"
    assert article_1.section_number == "1"

    assert article_2.number == "2"
    assert article_2.title == "Scope"
    assert article_2.chapter_number == "I"
    assert article_2.section_number == "1"


def test_parse_document_extracts_paragraphs(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    article_1 = doc.articles[0]

    assert len(article_1.paragraphs) == 2
    assert article_1.paragraphs[0].number == "1"
    assert "harmonised rules" in article_1.paragraphs[0].text
    assert article_1.paragraphs[1].number == "2"
    # points fold into the owning paragraph's text
    assert "a first illustrative point" in article_1.paragraphs[1].text


def test_parse_document_handles_single_unnumbered_paragraph_article(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    article_2 = doc.articles[1]

    assert len(article_2.paragraphs) == 1
    assert article_2.paragraphs[0].number is None
    assert "applies to providers" in article_2.paragraphs[0].text


def test_parse_document_extracts_recitals_separately(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)

    assert len(doc.recitals) == 2
    assert doc.recitals[0].number == "8"
    assert "background intent" in doc.recitals[0].text
    assert doc.recitals[1].number == "9"
    assert "transparency intent" in doc.recitals[1].text


def test_extract_cross_references_captures_article_and_chapter_citations() -> None:
    refs = extract_cross_references(
        "see Article 2 for scope. Applies without prejudice to Chapter III."
    )
    assert "article:2" in refs
    assert "chapter:iii" in refs


def test_extract_cross_references_captures_synthetic_recital_citation() -> None:
    # The real corpus never cites a Recital by number — this proves the mechanism
    # itself works using the fixture's one deliberately synthetic sentence.
    refs = extract_cross_references("As noted in Recital 9, transparency matters.")
    assert refs == ["recital:9"]


def test_build_chunks_creates_parent_and_leaf_chunks_for_multi_paragraph_article(
    fixture_xhtml: str,
) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    chunks = build_chunks(doc)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}

    assert "test_doc:article:1" in by_id
    assert "test_doc:article:1:paragraph:1" in by_id
    assert "test_doc:article:1:paragraph:2" in by_id
    assert by_id["test_doc:article:1:paragraph:1"].metadata["parent_chunk_id"] == (
        "test_doc:article:1"
    )
    assert by_id["test_doc:article:1:paragraph:2"].metadata["parent_chunk_id"] == (
        "test_doc:article:1"
    )


def test_build_chunks_skips_redundant_leaf_chunk_for_single_paragraph_article(
    fixture_xhtml: str,
) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    chunks = build_chunks(doc)
    chunk_ids = {chunk.chunk_id for chunk in chunks}

    assert "test_doc:article:2" in chunk_ids
    assert "test_doc:article:2:paragraph:1" not in chunk_ids


def test_build_chunks_captures_cross_references_in_metadata(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    chunks = build_chunks(doc)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}

    article_1_refs = by_id["test_doc:article:1"].metadata["cross_references"]
    assert "article:2" in article_1_refs
    assert "chapter:iii" in article_1_refs
    assert "recital:9" in article_1_refs


def test_build_chunks_metadata_values_are_all_strings(fixture_xhtml: str) -> None:
    doc = parse_document(fixture_xhtml, TEST_SOURCE)
    chunks = build_chunks(doc)

    for chunk in chunks:
        for value in chunk.metadata.values():
            assert isinstance(value, str)


# Annex layouts vary per annex; this fixture has one of each shape seen in the real AI
# Act: numbered first cell, spacer first cell with the number in the text, a bullet
# list, "Section A" headings, and "1." headings with lettered points or plain prose.
_ANNEX_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<div id="anx_III" class="eli-container">
  <p class="oj-doc-ti">ANNEX III</p>
  <p class="oj-doc-ti">High-risk AI systems referred to in Article 6(2)</p>
  <p class="oj-normal">High-risk AI systems are those listed below:</p>
  <table><tr><td><p>1.</p></td><td><p>Biometrics.</p></td></tr></table>
  <table><tr><td><p>5.</p></td><td><p>Credit: (b) creditworthiness.</p></td></tr></table>
</div>
<div id="anx_VIII" class="eli-container">
  <p class="oj-doc-ti">ANNEX VIII</p>
  <p class="oj-doc-ti">Registration information</p>
  <p class="oj-ti-grseq-1">Section A — Providers</p>
  <p class="oj-normal">The following information shall be provided:</p>
  <table><tr><td><p></p></td><td><p>1. The name of the provider;</p></td></tr></table>
  <table><tr><td><p></p></td><td><p>2. The trade name;</p></td></tr></table>
</div>
<div id="anx_II" class="eli-container">
  <p class="oj-doc-ti">ANNEX II</p>
  <p class="oj-doc-ti">List of criminal offences</p>
  <table><tr><td><p>—</p></td><td><p>terrorism,</p></td></tr></table>
  <table><tr><td><p>—</p></td><td><p>trafficking in human beings,</p></td></tr></table>
</div>
<div id="anx_X" class="eli-container">
  <p class="oj-doc-ti">ANNEX X</p>
  <p class="oj-doc-ti">Large-scale IT systems</p>
  <p class="oj-ti-grseq-1">1. Schengen Information System</p>
  <table><tr><td><p>(a)</p></td><td><p>Regulation (EU) 2018/1860</p></td></tr></table>
  <p class="oj-ti-grseq-1">3. Eurodac</p>
  <p class="oj-normal">Regulation (EU) 2024/1358</p>
</div>
</body></html>"""


def test_parse_document_extracts_annex_points_keyed_as_cited() -> None:
    doc = parse_document(_ANNEX_XHTML, TEST_SOURCE)
    keys = {annex.number: [item.key for item in annex.items] for annex in doc.annexes}

    assert keys == {
        "III": ["1", "5"],
        "VIII": ["A.1", "A.2", "A.intro"],
        "II": ["1", "2"],
        "X": ["1(a)", "3"],
    }
    annex_iii = doc.annexes[0]
    assert annex_iii.title == "High-risk AI systems referred to in Article 6(2)"
    assert annex_iii.intro == "High-risk AI systems are those listed below:"


def test_build_chunks_emits_annex_parent_and_point_leaves() -> None:
    chunks = {c.chunk_id: c for c in build_chunks(parse_document(_ANNEX_XHTML, TEST_SOURCE))}

    leaf = chunks["test_doc:annex:III:point:5"]
    assert leaf.content.startswith("Annex III, point 5 — High-risk AI systems")
    assert "creditworthiness" in leaf.content
    assert leaf.metadata["parent_chunk_id"] == "test_doc:annex:III"
    assert leaf.metadata["authority"] == "binding"
    assert chunks["test_doc:annex:III"].metadata["cross_references"] == "article:6.2"
    # Headed points carry their heading so the leaf embeds with context.
    assert "Section A — Providers" in chunks["test_doc:annex:VIII:point:A.1"].content


def test_every_chunk_links_back_to_eurlex() -> None:
    source = DocumentSource(
        slug="eu_ai_act",
        name="AI Act",
        celex_id="32024R1689",
        eli_uri="http://data.europa.eu/eli/reg/2024/1689/oj",
    )
    chunks = build_chunks(parse_document(_ANNEX_XHTML, source))

    assert {c.metadata["source_url"] for c in chunks if c.metadata.get("annex") == "III"} == {
        "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng#anx_III"
    }
