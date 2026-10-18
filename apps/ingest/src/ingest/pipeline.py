from dataclasses import dataclass
from pathlib import Path

import psycopg
from pgvector import Vector
from psycopg.types.json import Jsonb
from sentence_transformers import SentenceTransformer

from ingest.chunks import IngestChunk, build_chunks
from ingest.documents import DocumentSource
from ingest.fetch import fetch_document_xhtml
from ingest.guidance import (
    GuidanceSource,
    build_guidance_chunks,
    extract_pages,
    fetch_guidance_pdf,
)
from ingest.parser import ParsedDocument, parse_document
from telemetry import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestStats:
    articles: int
    recitals: int
    chunks: int
    inserted: int


def _truncate(doc: ParsedDocument, max_items: int | None) -> ParsedDocument:
    if max_items is None:
        return doc
    return ParsedDocument(
        source=doc.source,
        articles=doc.articles[:max_items],
        recitals=doc.recitals[:max_items],
        annexes=doc.annexes[:max_items],
    )


def _upsert_chunks(
    conn: psycopg.Connection, chunks: list[IngestChunk], embeddings: list[list[float]]
) -> int:
    with conn.cursor() as cur:
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            cur.execute(
                """
                INSERT INTO chunks (chunk_id, document_id, content, embedding, metadata)
                VALUES (%(chunk_id)s, %(document_id)s, %(content)s, %(embedding)s, %(metadata)s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata
                """,
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "content": chunk.content,
                    "embedding": Vector(embedding),
                    "metadata": Jsonb(chunk.metadata),
                },
            )
        # A re-ingest must also drop provisions that no longer exist (an amendment
        # deleted or renumbered them) — an upsert alone would keep serving them.
        cur.execute(
            "DELETE FROM chunks WHERE document_id = %(document_id)s"
            " AND NOT (chunk_id = ANY(%(chunk_ids)s))",
            {
                "document_id": chunks[0].document_id,
                "chunk_ids": [chunk.chunk_id for chunk in chunks],
            },
        )
    conn.commit()
    return len(chunks)


def _embed_and_upsert(
    conn: psycopg.Connection,
    embedder_model: SentenceTransformer,
    slug: str,
    chunks: list[IngestChunk],
) -> int:
    if not chunks:
        return 0
    vectors = embedder_model.encode([chunk.content for chunk in chunks], normalize_embeddings=True)
    embeddings = [vector.tolist() for vector in vectors]
    logger.info("ingest.chunks_embedded", source=slug, chunks=len(embeddings))
    inserted = _upsert_chunks(conn, chunks, embeddings)
    logger.info("ingest.chunks_inserted", source=slug, chunks=inserted)
    return inserted


def ingest_guidance(
    source: GuidanceSource,
    conn: psycopg.Connection,
    embedder_model: SentenceTransformer,
    cache_dir: Path,
    *,
    force_refresh: bool = False,
) -> int:
    """Fetch -> extract -> chunk -> embed -> upsert one guidance PDF (ingest.guidance)."""
    pages = extract_pages(fetch_guidance_pdf(source, cache_dir, force_refresh=force_refresh))
    chunks = build_guidance_chunks(source, pages)
    logger.info("ingest.chunks_built", source=source.slug, pages=len(pages), chunks=len(chunks))
    return _embed_and_upsert(conn, embedder_model, source.slug, chunks)


def ingest_document(
    source: DocumentSource,
    conn: psycopg.Connection,
    embedder_model: SentenceTransformer,
    cache_dir: Path,
    *,
    max_items: int | None = None,
    force_refresh: bool = False,
) -> IngestStats:
    """Fetch -> parse -> chunk -> embed -> idempotently upsert one document.
    `max_items` caps the number of articles/recitals parsed (used by the integration
    test to keep a real fetch fast, not a normal production knob)."""
    xhtml = fetch_document_xhtml(source, cache_dir, force_refresh=force_refresh)
    logger.info("ingest.document_fetched", source=source.slug, bytes=len(xhtml))
    doc = parse_document(xhtml, source)

    if source.consolidated_celex:
        consolidated = parse_document(
            fetch_document_xhtml(source, cache_dir, force_refresh=force_refresh, consolidated=True),
            source,
        )
        doc = ParsedDocument(
            source=source,
            articles=consolidated.articles,
            recitals=doc.recitals,
            annexes=consolidated.annexes,
        )
        logger.info(
            "ingest.consolidated_version", source=source.slug, celex=source.consolidated_celex
        )
    if source.recitals_only:
        doc = ParsedDocument(source=source, recitals=doc.recitals)

    doc = _truncate(doc, max_items)
    logger.info(
        "ingest.articles_parsed",
        source=source.slug,
        articles=len(doc.articles),
        recitals=len(doc.recitals),
        annexes=len(doc.annexes),
    )

    chunks = build_chunks(doc)
    logger.info("ingest.chunks_built", source=source.slug, chunks=len(chunks))
    inserted = _embed_and_upsert(conn, embedder_model, source.slug, chunks)

    return IngestStats(
        articles=len(doc.articles),
        recitals=len(doc.recitals),
        chunks=len(chunks),
        inserted=inserted,
    )
