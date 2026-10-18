/** A cited chunk, narrowed from the reranker's node_completed payload — see
 * api.graph.events.reranker_payload, which dumps core.models.ScoredChunk as
 * {chunk: {id, document_id, text, metadata}, score}. Every id the generator can cite is
 * validated server-side against exactly this set (api.graph.nodes._validate_citations),
 * so a citation id always resolves here on the happy path; callers still handle a miss
 * defensively rather than assuming it. */
export interface CitedChunk {
  id: string;
  documentId: string;
  text: string;
  metadata: Record<string, string>;
}

function asCitedChunk(raw: unknown): CitedChunk | null {
  if (typeof raw !== "object" || raw === null || !("chunk" in raw)) return null;
  const chunk = (raw as { chunk: unknown }).chunk;
  if (typeof chunk !== "object" || chunk === null) return null;
  const { id, document_id, text, metadata } = chunk as Record<string, unknown>;
  if (typeof id !== "string" || typeof document_id !== "string" || typeof text !== "string") return null;
  return {
    id,
    documentId: document_id,
    text,
    metadata: typeof metadata === "object" && metadata !== null ? (metadata as Record<string, string>) : {},
  };
}

/** Builds an id -> chunk lookup from the reranker payload's `reranked` array — the exact
 * chunk set the generator saw and cited from. */
export function buildChunkIndex(reranked: unknown[] | undefined): Map<string, CitedChunk> {
  const index = new Map<string, CitedChunk>();
  for (const raw of reranked ?? []) {
    const chunk = asCitedChunk(raw);
    if (chunk) index.set(chunk.id, chunk);
  }
  return index;
}

/** "Art. 6(2)" / "GDPR Art. 4" / "Recital 12" / "Annex III pt 5" / "EDPB Guidelines 9/2022,
 * paras 31-32" / "Status note · 2026-10-18" — built from apps/ingest's metadata shapes
 * (chunks.py, guidance.py, status.py). GDPR gets a document prefix since the AI Act is
 * this system's implicit default corpus; the AI Act doesn't need one. */
export function citationLabel(metadata: Record<string, string>): string {
  if (metadata.authority === "guidance") {
    const where = metadata.paragraphs
      ? `${metadata.paragraphs.includes("-") ? "paras" : "para"} ${metadata.paragraphs}`
      : `p. ${metadata.page}`;
    return `${metadata.short_title ?? "Guidance"}, ${where}`;
  }
  if (metadata.authority === "status") return `Status note · ${metadata.as_of}`;

  const prefix =
    metadata.source === "gdpr" ? "GDPR " : metadata.source === "eu_ai_act_amendment_2026" ? "Reg. 2026/1744 " : "";
  if (metadata.recital) return `${prefix}Recital ${metadata.recital}`;
  if (metadata.annex) return `Annex ${metadata.annex}${metadata.point ? ` pt ${metadata.point}` : ""}`;
  if (metadata.article) {
    const paragraph = metadata.paragraph ? `(${metadata.paragraph})` : "";
    return `${prefix}Art. ${metadata.article}${paragraph}`;
  }
  return `${prefix}source`;
}

export type SourceKind = "law" | "guidance" | "status";

export interface Provenance {
  kind: SourceKind;
  /** One line under the label saying how much weight the source carries. */
  note: string;
  /** Where to read it in full (EUR-Lex, or the guidance PDF at its page). */
  url: string | null;
}

/** Amending acts named by CELEX id (metadata.amended_by) — "32026R1744" -> "Reg. (EU) 2026/1744". */
function regulationName(celex: string): string {
  const match = /^3(\d{4})R(\d{4})$/.exec(celex);
  return match ? `Reg. (EU) ${match[1]}/${Number(match[2])}` : celex;
}

export function provenance(metadata: Record<string, string>): Provenance {
  const raw = metadata.source_url ?? "";
  // The URL comes from our own ingest, but it ends up in an href: only http(s).
  const url = /^https?:\/\//.test(raw) ? raw : null;

  if (metadata.authority === "guidance") {
    return { kind: "guidance", note: `Non-binding guidance · ${metadata.issuer} · ${metadata.adopted}`, url };
  }
  if (metadata.authority === "status") {
    return { kind: "status", note: `Status note, checked ${metadata.as_of} — not law`, url };
  }
  const parts = ["Binding law"];
  if (metadata.consolidated_as_of) parts.push(`consolidated text as of ${metadata.consolidated_as_of}`);
  if (metadata.amended_by) parts.push(`amended by ${metadata.amended_by.split(",").map(regulationName).join(", ")}`);
  return { kind: "law", note: parts.join(" · "), url };
}

/** Chunk text already carries a human header line — see _article_chunk/_paragraph_chunks/
 * build_chunks in apps/ingest/src/ingest/chunks.py, e.g. "Article 6(2) — <title>\n\n<body>"
 * or "Recital 12\n\n<body>". Split on the first blank line rather than re-deriving the
 * header from metadata, so the panel shows exactly what's in the corpus. */
export function splitChunkText(text: string, fallbackHeader: string): { header: string; body: string } {
  const boundary = text.indexOf("\n\n");
  if (boundary === -1) return { header: fallbackHeader, body: text };
  return { header: text.slice(0, boundary), body: text.slice(boundary + 2) };
}
