from dataclasses import dataclass, field

from ingest.documents import DocumentSource
from ingest.parser import Annex, Article, ParsedDocument
from ingest.references import extract_cross_references


@dataclass(frozen=True)
class IngestChunk:
    chunk_id: str
    document_id: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


# Every chunk says how much weight it carries. Regulation text is "binding"; the
# guidance and status sources are not, and the generator is told to say so when it
# relies on them.
BINDING = "binding"


def _provenance(
    source: DocumentSource, anchor: str, *, consolidated: bool = False
) -> dict[str, str]:
    metadata = {
        "authority": BINDING,
        "source_url": source.eurlex_url(anchor, consolidated=consolidated),
    }
    if consolidated and source.consolidated_as_of:
        # Shown next to the citation: this is the text as amended, as of this date.
        metadata["consolidated_as_of"] = source.consolidated_as_of
    return metadata


def _base_metadata(source: DocumentSource, article: Article) -> dict[str, str]:
    metadata = {
        "source": source.slug,
        "article": article.number,
        **_provenance(source, f"art_{article.number}", consolidated=True),
    }
    amendments = [celex for celex in article.amended_by if celex != source.celex_id]
    if amendments:
        metadata["amended_by"] = ",".join(amendments)
    if article.chapter_number is not None:
        metadata["chapter"] = article.chapter_number
    if article.section_number is not None:
        metadata["section"] = article.section_number
    return metadata


def _article_chunk(source: DocumentSource, article: Article) -> IngestChunk:
    source_slug = source.slug
    header = f"Article {article.number} — {article.title}"
    content = f"{header}\n\n{article.full_text}"
    metadata = _base_metadata(source, article)
    refs = extract_cross_references(article.full_text)
    if refs:
        metadata["cross_references"] = ",".join(refs)
    return IngestChunk(
        chunk_id=f"{source_slug}:article:{article.number}",
        document_id=source_slug,
        content=content,
        metadata=metadata,
    )


def _paragraph_chunks(
    source: DocumentSource, article: Article, parent_chunk_id: str
) -> list[IngestChunk]:
    source_slug = source.slug
    chunks: list[IngestChunk] = []
    for index, paragraph in enumerate(article.paragraphs, start=1):
        para_number = paragraph.number or str(index)
        header = f"Article {article.number}({para_number}) — {article.title}"
        content = f"{header}\n\n{paragraph.text}"
        metadata = _base_metadata(source, article)
        metadata["paragraph"] = para_number
        metadata["parent_chunk_id"] = parent_chunk_id
        refs = extract_cross_references(paragraph.text)
        if refs:
            metadata["cross_references"] = ",".join(refs)
        chunks.append(
            IngestChunk(
                chunk_id=f"{source_slug}:article:{article.number}:paragraph:{para_number}",
                document_id=source_slug,
                content=content,
                metadata=metadata,
            )
        )
    return chunks


def _annex_heading(annex: Annex, point: str | None = None) -> str:
    heading = f"Annex {annex.number}" + (f", point {point}" if point else "")
    return f"{heading} — {annex.title}" if annex.title else heading


def _annex_chunks(source: DocumentSource, annex: Annex) -> list[IngestChunk]:
    """Same parent/leaf shape as articles: one whole-annex chunk, plus one per point
    when there is more than one, so "Annex III point 5" is retrievable on its own."""
    slug = source.slug
    parent_id = f"{slug}:annex:{annex.number}"
    base = {
        "source": slug,
        "annex": annex.number,
        **_provenance(source, f"anx_{annex.number}", consolidated=True),
    }

    def with_refs(metadata: dict[str, str], text: str) -> dict[str, str]:
        refs = extract_cross_references(text)
        if refs:
            metadata["cross_references"] = ",".join(refs)
        return metadata

    chunks = [
        IngestChunk(
            chunk_id=parent_id,
            document_id=slug,
            content=f"{_annex_heading(annex)}\n\n{annex.full_text}",
            # Annex titles carry the reference that brings them into force ("... referred
            # to in Article 6(2)"), so the title is scanned too.
            metadata=with_refs(dict(base), f"{annex.title}\n{annex.full_text}"),
        )
    ]
    if len(annex.items) > 1:
        for item in annex.items:
            # The heading and annex title ride along in the text so a leaf embeds with
            # its context ("point 5" alone says little).
            header = _annex_heading(annex, item.key)
            body = f"{item.heading}\n{item.text}" if item.heading else item.text
            chunks.append(
                IngestChunk(
                    chunk_id=f"{parent_id}:point:{item.key}",
                    document_id=slug,
                    content=f"{header}\n\n{body}",
                    metadata=with_refs(
                        {**base, "point": item.key, "parent_chunk_id": parent_id}, item.text
                    ),
                )
            )
    return chunks


def build_chunks(doc: ParsedDocument) -> list[IngestChunk]:
    """Parent-document retrieval chunking: every Article always gets one article-level
    "parent" chunk (full text, precise enough on its own for single-paragraph
    articles). Multi-paragraph articles additionally get one paragraph-level "leaf"
    chunk each, small/precise for embedding, carrying parent_chunk_id back to the
    article-level chunk. Recitals are single-level — no parent/child split. Annexes
    follow the article shape, with points as leaves."""
    chunks: list[IngestChunk] = []
    slug = doc.source.slug

    for article in doc.articles:
        article_chunk = _article_chunk(doc.source, article)
        chunks.append(article_chunk)
        if len(article.paragraphs) > 1:
            chunks.extend(_paragraph_chunks(doc.source, article, article_chunk.chunk_id))

    for recital in doc.recitals:
        header = f"Recital {recital.number}"
        content = f"{header}\n\n{recital.text}"
        metadata = {
            "source": slug,
            "recital": recital.number,
            **_provenance(doc.source, f"rct_{recital.number}"),
        }
        refs = extract_cross_references(recital.text)
        if refs:
            metadata["cross_references"] = ",".join(refs)
        chunks.append(
            IngestChunk(
                chunk_id=f"{slug}:recital:{recital.number}",
                document_id=slug,
                content=content,
                metadata=metadata,
            )
        )

    for annex in doc.annexes:
        chunks.extend(_annex_chunks(doc.source, annex))

    return chunks
