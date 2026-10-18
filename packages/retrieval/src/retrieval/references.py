"""Finds the provisions a question names outright ("Article 5(1)", "Art. 50 GDPR",
"Annex III point 5", "Recital 44") and maps them to chunk ids, so the retriever can
put them first instead of hoping similarity search ranks them there.

The chunk-id scheme is apps/ingest's (ingest.chunks): "<doc>:article:<n>",
"<doc>:article:<n>:paragraph:<p>", "<doc>:recital:<n>", "<doc>:annex:<roman>",
"<doc>:annex:<roman>:point:<key>".
"""

import re

AI_ACT = "eu_ai_act"
GDPR = "gdpr"

_ARTICLE_RE = re.compile(r"\b(?:Article|Art\.?)\s*(\d+[a-z]?)(?:\s*\((\d+[a-z]?)\))?", re.I)
_RECITAL_RE = re.compile(r"\bRecital\s+(\d+)\b", re.I)
_ANNEX_RE = re.compile(r"\bAnnex\s+([IVXL]+)\b(?:,?\s*(?:point|pt\.?)\s*(\d+))?", re.I)
_GDPR_RE = re.compile(r"\bGDPR\b|2016/679|General Data Protection Regulation", re.I)
_AI_ACT_RE = re.compile(r"\bAI Act\b|2024/1689|Artificial Intelligence Act", re.I)
_DOCUMENT_NAMES = ((AI_ACT, _AI_ACT_RE), (GDPR, _GDPR_RE))


def referenced_chunk_ids(text: str) -> list[str]:
    """Ids of the provisions `text` names, most specific first (a paragraph before its
    article). With no regulation named, an article or recital number is looked up in
    both; annexes exist only in the AI Act. Ids may not exist — the caller keeps the
    ones that do."""
    named = [doc for doc, pattern in _DOCUMENT_NAMES if pattern.search(text)]
    documents = named or [AI_ACT, GDPR]

    ids: dict[str, None] = {}
    for match in _ARTICLE_RE.finditer(text):
        article, paragraph = match.group(1).lower(), match.group(2)
        for doc in documents:
            if paragraph:
                ids[f"{doc}:article:{article}:paragraph:{paragraph.lower()}"] = None
            ids[f"{doc}:article:{article}"] = None
    for match in _RECITAL_RE.finditer(text):
        for doc in documents:
            ids[f"{doc}:recital:{match.group(1)}"] = None
    for match in _ANNEX_RE.finditer(text):
        annex, point = match.group(1).upper(), match.group(2)
        if point:
            ids[f"{AI_ACT}:annex:{annex}:point:{point}"] = None
        ids[f"{AI_ACT}:annex:{annex}"] = None
    return list(ids)
