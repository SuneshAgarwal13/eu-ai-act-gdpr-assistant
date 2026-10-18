from typing import Any

from core.models import Chunk, Filters, Query, ScoredChunk
from core.ports import Embedder
from pgvector import Vector
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from retrieval.references import referenced_chunk_ids


def _build_where_clause(filters: Filters | None) -> tuple[str, dict[str, Any]]:
    """Translates a Filters object into a SQL WHERE clause + bound params — filtering
    happens in the query itself, never fetch-then-filter in Python."""
    if filters is None:
        return "TRUE", {}

    clauses: list[str] = []
    params: dict[str, Any] = {}

    if filters.document_ids is not None:
        clauses.append("document_id = ANY(%(document_ids)s)")
        params["document_ids"] = filters.document_ids

    if filters.tags is not None:
        # Matches core.testing.FakeRetriever's tag semantics exactly: metadata["tags"]
        # is a comma-separated string, intersected with the filter's tags — same
        # conceptual filter behaves identically across the fake and this real adapter.
        clauses.append("string_to_array(metadata->>'tags', ',') && %(tags)s")
        params["tags"] = filters.tags

    if filters.metadata_equals is not None:
        for i, (key, value) in enumerate(filters.metadata_equals.items()):
            key_param, value_param = f"meta_key_{i}", f"meta_value_{i}"
            clauses.append(f"metadata ->> %({key_param})s = %({value_param})s")
            params[key_param] = key
            params[value_param] = value

    if not clauses:
        return "TRUE", {}
    return " AND ".join(clauses), params


# Each ranker's candidate pool before fusion: deep enough that a chunk ranked modestly
# by both still surfaces, shallow enough to stay a single fast query.
_CANDIDATES = 50
# Reciprocal rank fusion constant; 60 is the value from the original RRF paper and the
# common default — it flattens the gap between rank 1 and rank 5 of either list.
_RRF_K = 60
# Provisions named outright in the question are put first, up to this many, so a long
# list of references can't crowd out everything similarity search found.
_MAX_EXPLICIT = 4
# ts_rank_cd normalization bitmask (Postgres docs, "Ranking Search Results"). On the dev
# split, length normalization (1, 2, 32) never beat none (0); see ADR 0007.
_TS_NORMALIZATION = 0
# Full-text ranking's weight against the vector ranking in the fusion. At 1.0 keyword
# matches on long articles crowded out the precise paragraph; 0.5 was best on dev.
_FTS_WEIGHT = 0.5
# Default score multipliers by source kind, tuned on the dev split (ADR 0007): an
# operative provision should outrank the recital or guidance paragraph restating it.
# Status notes stay at 1.0 — for "has this been amended?" they are often the only source.
DEFAULT_AUTHORITY_WEIGHTS = {"recital": 0.8, "guidance": 0.7, "status": 1.0}


class PgVectorRetriever:
    """core.ports.Retriever over the pgvector chunks table — see ADR 0002 and 0007.

    Hybrid: a vector-similarity ranking and a Postgres full-text ranking, fused with
    reciprocal rank fusion in one SQL statement. Full text catches what a 384-dim
    embedding blurs — exact legal terms ("creditworthiness", "DPIA") and numbers.
    Provisions the question names outright (retrieval.references) are fetched by id and
    put first. `authority_weights` scales the fused score by source kind ("recital",
    "guidance", "status"; anything else 1.0) so an operative article isn't outranked by
    the recital or guidance paragraph that paraphrases it."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: Embedder,
        authority_weights: dict[str, float] | None = None,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._weights = {**DEFAULT_AUTHORITY_WEIGHTS, **(authority_weights or {})}

    async def retrieve(self, query: Query) -> list[ScoredChunk]:
        query_vector = await self._embedder.embed_query(query.text)
        where_sql, where_params = _build_where_clause(query.filters)
        explicit_ids = referenced_chunk_ids(query.text)

        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                f"""
                WITH q AS (
                    -- plainto_tsquery ANDs every word, which a full question almost never
                    -- satisfies; OR them and let ts_rank_cd reward chunks matching more.
                    SELECT NULLIF(replace(plainto_tsquery('english', %(text)s)::text,
                                          ' & ', ' | '), '')::tsquery AS tsq
                ),
                vec AS (
                    SELECT chunk_id,
                           row_number() OVER (ORDER BY embedding <=> %(query_vector)s) AS rank
                    FROM chunks
                    WHERE {where_sql}
                    ORDER BY embedding <=> %(query_vector)s
                    LIMIT %(candidates)s
                ),
                fts AS (
                    SELECT chunk_id,
                           row_number() OVER (
                               ORDER BY ts_rank_cd(tsv, q.tsq, %(ts_norm)s) DESC
                           ) AS rank
                    FROM chunks, q
                    WHERE q.tsq IS NOT NULL AND tsv @@ q.tsq AND {where_sql}
                    ORDER BY ts_rank_cd(tsv, q.tsq, %(ts_norm)s) DESC
                    LIMIT %(candidates)s
                ),
                fused AS (
                    SELECT chunk_id, sum(weight / (%(rrf_k)s + rank)) AS rrf
                    FROM (
                        SELECT chunk_id, rank, 1.0 AS weight FROM vec
                        UNION ALL
                        SELECT chunk_id, rank, %(fts_weight)s AS weight FROM fts
                    ) ranked
                    GROUP BY chunk_id
                )
                SELECT c.chunk_id, c.document_id, c.content, c.metadata,
                       f.rrf * CASE
                           WHEN c.metadata ? 'recital' THEN %(w_recital)s
                           WHEN c.metadata->>'authority' = 'guidance' THEN %(w_guidance)s
                           WHEN c.metadata->>'authority' = 'status' THEN %(w_status)s
                           ELSE 1.0
                       END AS score
                FROM fused f JOIN chunks c USING (chunk_id)
                ORDER BY score DESC
                LIMIT %(top_k)s
                """,
                # pgvector-python only adapts its own Vector wrapper (or numpy arrays)
                # to the `vector` SQL type — a bare Python list falls through to
                # psycopg's default array adapter (double precision[]), which the
                # <=> operator doesn't accept. Confirmed by reading pgvector.psycopg's
                # dumper registration directly after a live "operator does not exist:
                # vector <=> double precision[]" failure.
                {
                    "query_vector": Vector(query_vector),
                    "text": query.text,
                    "candidates": max(_CANDIDATES, query.top_k),
                    "rrf_k": _RRF_K,
                    "ts_norm": _TS_NORMALIZATION,
                    "fts_weight": _FTS_WEIGHT,
                    "w_recital": self._weights["recital"],
                    "w_guidance": self._weights["guidance"],
                    "w_status": self._weights["status"],
                    # Over-fetch: leaves whose parent is also present are dropped below.
                    "top_k": query.top_k * 2,
                    **where_params,
                },
            )
            ranked = [_to_scored(row, float(row["score"])) for row in await cur.fetchall()]

            explicit: list[ScoredChunk] = []
            if explicit_ids:
                await cur.execute(
                    f"""
                    SELECT chunk_id, document_id, content, metadata
                    FROM chunks
                    WHERE chunk_id = ANY(%(ids)s) AND {where_sql}
                    """,
                    {"ids": explicit_ids, **where_params},
                )
                found = {row["chunk_id"]: row for row in await cur.fetchall()}
                # Scored just above the best fused result, in the order named, so the
                # list still descends by score as the Retriever port requires.
                top = ranked[0].score if ranked else 0.0
                named = [found[cid] for cid in explicit_ids if cid in found][:_MAX_EXPLICIT]
                explicit = [
                    _to_scored(row, top + (len(named) - i) * 1e-3) for i, row in enumerate(named)
                ]

        pinned = {sc.chunk.id for sc in explicit}
        merged = explicit + [sc for sc in ranked if sc.chunk.id not in pinned]
        # An article (or annex) chunk holds each of its paragraph (point) chunks verbatim;
        # returning both spends two of the generator's few context slots on one text.
        present = {sc.chunk.id for sc in merged}
        distinct = [sc for sc in merged if sc.chunk.metadata.get("parent_chunk_id") not in present]
        return distinct[: query.top_k]


def _to_scored(row: dict[str, Any], score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            id=row["chunk_id"],
            document_id=row["document_id"],
            text=row["content"],
            metadata=row["metadata"],
        ),
        score=score,
    )
