# 0007 — Hybrid retrieval, named-provision pinning and authority weights

## Status

Accepted — 2026-10-18

## Context

`PgVectorRetriever` was vector-only (ADR 0002 left hybrid search as future work). A live
test on 2026-10-18 showed two failure shapes:

- **Exact legal terms blur in a 384-dim embedding.** "Creditworthiness", "DPIA",
  "emotion recognition in the workplace" retrieved recitals and neighbouring articles
  rather than Annex III point 5 or Article 5(1)(f).
- **The paraphrase outranks the provision.** Recitals, and once guidance was ingested
  (ADR 0008) EDPB and Commission paragraphs, restate the operative text in plainer
  words, so they win on similarity. Adding 744 guidance chunks dropped strict recall@5
  on the old golden set from 0.968 to 0.871 with vector search alone.

The old golden set could not judge a fix: 30 of its 37 questions name the article
("…according to Article 5"). A 48-item plain-language set with a held-out test split
was added for this (see `evals/datasets/README.md`).

## Decision

One SQL statement in `PgVectorRetriever.retrieve`:

1. **Vector ranking** (top 50) and **Postgres full-text ranking** (top 50, migration
   0002's generated `tsvector` + GIN index). `plainto_tsquery` ANDs every word, which a
   full question almost never satisfies, so its terms are OR-ed and `ts_rank_cd`
   rewards chunks that match more of them.
2. **Reciprocal rank fusion**, k = 60, full-text weighted 0.5 against vector 1.0.
3. **Authority weights** on the fused score: recital ×0.8, guidance ×0.7, status ×1.0
   (status notes are often the only source for "has this been amended?").
4. **Named-provision pinning**: `retrieval.references` finds "Article 5(1)", "Art. 50
   GDPR", "Annex III point 5", "Recital 44" in the query and fetches those chunks by id,
   up to four, ahead of the fused list. The planner is told never to add a provision
   number the user didn't write, since its rewrite is what the retriever reads.
5. **Parent/leaf dedupe**: a paragraph chunk is dropped when its article chunk is in
   the same result, so five context slots hold five different texts.

No new dependency; all of it lives in the adapter, so `core.ports.Retriever` is
unchanged.

### Tuning

Weights were grid-searched on the **dev split only** (FTS weight {0.5, 1.0},
`ts_rank_cd` normalization {0, 1, 2, 32}, guidance {1.0, 0.7}, recital {1.0, 0.8}, pinning
on/off). Length normalization never beat none. FTS at 1.0 let long articles crowd out the
precise paragraph.

## Results

Held-out test split (29 scored plain-language items), top 5:

| | baseline (main) | this change |
|---|---|---|
| hit@5, containment-aware | 0.586 | **0.724** |
| MRR@5, containment-aware | 0.371 | **0.549** |
| hit@1, containment-aware | 0.207 | **0.448** |
| recall@5, strict | **0.342** | 0.138 |

"Containment-aware" counts a retrieved article or annex chunk as covering the paragraph
or point it holds verbatim (`evals.metrics.hit_at_k_containing`). The strict metric falls
because full-text ranking and the dedupe prefer the whole article where the label is a
paragraph — the grain gap ADR 0006 diagnosed. Both are reported; neither replaces the
other. Whether the coarser grain costs answer quality is measured by the Layer 3
generation eval, recorded in the PR that introduced this ADR.

## Consequences

- Article-level chunks reach the generator more often. They are longer; Article 5 runs
  past 2,000 words. If generation quality or token cost suffers, the next lever is a
  per-chunk length cap in the reranker node, not undoing hybrid search.
- `retrieval.references` knows the corpus's chunk-id scheme and document slugs
  (`eu_ai_act`, `gdpr`). A new instrument needs a line there to be pinnable.
- The reranker decision (ADR 0003) is untouched; the identity reranker still truncates to
  the top 5.
