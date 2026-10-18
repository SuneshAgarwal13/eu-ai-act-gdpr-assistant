# 0008 — An authority-labelled corpus: consolidated law, guidance, status notes

## Status

Accepted — 2026-10-18

## Context

The corpus was the 2024 Official Journal text of the AI Act and the GDPR, articles and
recitals only. Three gaps showed up in a live test:

- **Annexes were dropped.** Whether credit scoring is high-risk turns on Annex III
  point 5(b); what technical documentation must contain is Annex IV. The parser never
  read `anx_*` elements.
- **The AI Act had been amended.** Regulation (EU) 2026/1744 (Digital Omnibus on AI, OJ
  24 July 2026) moved the high-risk application dates to 2 December 2027 (Annex III) and
  2 August 2028 (Annex I), inserted Articles 4a, 60a and 75a–d and a new prohibition, and
  deleted Annex I point A.1. The corpus gave the old dates.
- **Practitioners' questions are often answered by guidance**, not the regulation:
  when a controller becomes "aware" of a breach (EDPB 9/2022), what counts as exploiting a
  child's vulnerability (Commission Art. 5 guidelines).

## Decision

Every chunk carries `metadata.authority` and a `source_url`:

| authority | sources | how it's chunked |
|---|---|---|
| `binding` | AI Act articles and annexes from the EUR-Lex **consolidated version** `02024R1689-20260727`; AI Act recitals from the OJ text (consolidations carry none); recitals of Reg. 2026/1744; GDPR (unamended) | article/paragraph and annex/point parent-leaf pairs; `consolidated_as_of` and `amended_by` recorded |
| `guidance` | 3 Commission guidelines, 5 EDPB guidelines/opinions, the EDPB-endorsed WP29 DPIA guidelines | runs of numbered paragraphs (~300 words), cited "paras 26–28", linked to the PDF page |
| `status` | hand-written notes in `apps/ingest/status/*.md` | one chunk per section, with `as_of` |

- The parser auto-detects consolidated markup (`norm`/`grid-list`, `▼M1` amendment
  markers, letter-suffixed articles, "1a." paragraphs).
- The amending regulation's articles are not ingested: they are editing instructions
  ("Article 6 is amended as follows…") already folded into the consolidation, and would
  compete with it in retrieval.
- Re-ingesting deletes chunks that no longer exist in a document, so a deleted or
  renumbered provision stops being served.
- The generator is told to attribute guidance ("the EDPB considers…"), never present it as
  an obligation, and to give a status note's date. The web UI labels every source (binding
  / non-binding / status), draws non-binding chips with a dashed border, and links to the
  provision on EUR-Lex or to the guidance PDF page.

## Consequences

- **Status notes are the one part nobody can re-fetch.** Ingest logs
  `ingest.status_note_stale` once a note is 90 days old. Re-check its sources and bump
  `as_of`, or delete it.
- **The consolidation date is pinned** in `ingest.documents`. When EUR-Lex publishes a newer
  consolidation, update `consolidated_celex` and re-ingest; chunk ids stay stable.
- Guidance is weighted ×0.7 in retrieval (ADR 0007) so it informs rather than replaces the
  provision it interprets.
- Consolidated texts are not the authentic OJ text (EUR-Lex's own disclaimer). The source
  panel says "consolidated text as of …" and links to it.
- New ingest-only dependency: `pypdf` (pure Python, BSD), not in the API image.
