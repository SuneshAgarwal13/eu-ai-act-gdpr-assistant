import math


def _validate(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> None:
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if not relevant_ids:
        raise ValueError(
            "relevant_ids must be non-empty — the caller is responsible for "
            "excluding items with no ground truth (e.g. out_of_scope questions) "
            "before calling a metric function"
        )


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """|retrieved_ids[:k] ∩ relevant_ids| / |relevant_ids|. k > len(retrieved_ids) is
    not an error — slicing a short list just yields fewer candidates."""
    _validate(retrieved_ids, relevant_ids, k)
    hits = len(set(retrieved_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """1 / (1-indexed rank of the first relevant hit within top-k), 0.0 if none.
    This is the per-item quantity — "MRR" is the mean of this over a query set,
    computed by the caller (scorecard.aggregate), not here."""
    _validate(retrieved_ids, relevant_ids, k)
    for rank, chunk_id in enumerate(retrieved_ids[:k], start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def _covers(retrieved_id: str, relevant_id: str) -> bool:
    """A retrieved article- or annex-level chunk holds each of its paragraph/point
    chunks verbatim (apps/ingest chunks.py), so it gives the generator the same text."""
    return retrieved_id == relevant_id or relevant_id.startswith(
        (f"{retrieved_id}:paragraph:", f"{retrieved_id}:point:")
    )


def hit_at_k_containing(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """1.0 if any of the top-k chunks is, or contains, a relevant chunk. The strict
    metrics count a whole-article hit as a miss when the label is a paragraph — the
    grain artifact in ADR 0006 — so this is reported alongside them, never instead."""
    _validate(retrieved_ids, relevant_ids, k)
    return float(any(_covers(r, rel) for r in retrieved_ids[:k] for rel in relevant_ids))


def reciprocal_rank_containing(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    _validate(retrieved_ids, relevant_ids, k)
    for rank, chunk_id in enumerate(retrieved_ids[:k], start=1):
        if any(_covers(chunk_id, rel) for rel in relevant_ids):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Binary-relevance nDCG@k: DCG = sum of 1/log2(rank+1) over hits in the top-k,
    IDCG = the same formula for the ideal ranking (all relevant items first, capped
    at min(k, len(relevant_ids)) since you can't rank more relevant items than
    exist). Returns DCG / IDCG."""
    _validate(retrieved_ids, relevant_ids, k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved_ids[:k], start=1)
        if chunk_id in relevant_ids
    )
    ideal_hits = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
