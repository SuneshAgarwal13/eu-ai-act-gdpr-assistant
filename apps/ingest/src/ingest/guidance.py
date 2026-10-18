"""Official, non-binding guidance on the AI Act and GDPR: Commission guidelines and
EDPB (incl. endorsed Article 29 Working Party) guidelines and opinions.

Both issuers number their paragraphs ("26." in EDPB documents, "(111)" in Commission
guidelines), and practitioners cite them that way, so a chunk is a run of consecutive
numbered paragraphs, cited as "paras 26-28" and linked to the PDF page it starts on.
"""

import logging
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from ingest.chunks import IngestChunk
from ingest.fetch import _USER_AGENT

GUIDANCE = "guidance"

# Paragraph runs are cut near this size: big enough to hold a point and its example,
# small enough to stay inside the embedder's 512-token window.
_TARGET_WORDS = 300

# Each issuer's paragraph-number style, matched at the start of a line.
_PARAGRAPH_STYLES = {
    "dotted": re.compile(r"^\s*(\d{1,3})\.\s+(?=\S)", re.MULTILINE),
    "bracketed": re.compile(r"^\s*\((\d{1,3})\)\s+(?=\S)", re.MULTILINE),
}
# Running headers and footers ("Adopted  10", a bare page number) and table-of-contents
# lines ("1. Introduction ....... 3"), which would otherwise pass for paragraph 1.
_PAGE_FURNITURE_RE = re.compile(
    r"^\s*(?:Adopted\s+)?\d{1,3}\s*$|^.*\.{4,}\s*\d+\s*$", re.MULTILINE
)


@dataclass(frozen=True)
class GuidanceSource:
    slug: str
    # How the document is cited: "EDPB Guidelines 9/2022".
    short_title: str
    title: str
    issuer: str
    adopted: str  # ISO date of the version ingested
    url: str


GUIDANCE_SOURCES: list[GuidanceSource] = [
    GuidanceSource(
        slug="com_guidelines_prohibited_practices_2025",
        short_title="Commission Guidelines on prohibited AI practices",
        title="Guidelines on prohibited artificial intelligence practices established by "
        "Regulation (EU) 2024/1689 (AI Act), C(2025) 5052",
        issuer="European Commission",
        adopted="2025-07-29",
        url="https://ai-act-service-desk.ec.europa.eu/sites/default/files/2025-08/guidelines_on_prohibited_artificial_intelligence_practices_established_by_regulation_eu_20241689_ai_act_english_ied3r5nwo50xggpcfmwckm3nuc_112367-1.PDF",
    ),
    GuidanceSource(
        slug="com_guidelines_ai_system_definition_2025",
        short_title="Commission Guidelines on the AI system definition",
        title="Guidelines on the definition of an artificial intelligence system established "
        "by Regulation (EU) 2024/1689 (AI Act), C(2025) 5053",
        issuer="European Commission",
        adopted="2025-07-29",
        url="https://ai-act-service-desk.ec.europa.eu/sites/default/files/2025-08/commission_guidelines_on_the_definition_of_an_artificial_intelligence_system_established_by_regulation_eu_20241689_ai_actenglish_nf2skcqfrtjdfggjavcodopcwz4_112455.PDF",
    ),
    GuidanceSource(
        slug="com_guidelines_gpai_scope_2025",
        short_title="Commission Guidelines on general-purpose AI models",
        title="Guidelines on the scope of the obligations for general-purpose AI models "
        "established by Regulation (EU) 2024/1689 (AI Act), C(2025) 5045",
        issuer="European Commission",
        adopted="2025-07-18",
        url="https://ai-act-service-desk.ec.europa.eu/sites/default/files/2025-07/guidelines_on_the_scope_of_the_obligations_for_generalpurpose_ai_models_established_by_regulation_1cx2atxgq79us4n3x8jfgyy1qlm_118340-3.pdf",
    ),
    GuidanceSource(
        slug="edpb_guidelines_9_2022",
        short_title="EDPB Guidelines 9/2022",
        title="Guidelines 9/2022 on personal data breach notification under GDPR, version 2.0",
        issuer="European Data Protection Board",
        adopted="2023-03-28",
        url="https://www.edpb.europa.eu/system/files/2023-04/edpb_guidelines_202209_personal_data_breach_notification_v2.0_en.pdf",
    ),
    GuidanceSource(
        slug="edpb_guidelines_07_2020",
        short_title="EDPB Guidelines 07/2020",
        title="Guidelines 07/2020 on the concepts of controller and processor in the GDPR, "
        "version 2.1",
        issuer="European Data Protection Board",
        adopted="2021-07-07",
        url="https://www.edpb.europa.eu/system/files/2023-10/EDPB_guidelines_202007_controllerprocessor_final_en.pdf",
    ),
    GuidanceSource(
        slug="edpb_guidelines_05_2020",
        short_title="EDPB Guidelines 05/2020",
        title="Guidelines 05/2020 on consent under Regulation 2016/679, version 1.1",
        issuer="European Data Protection Board",
        adopted="2020-05-04",
        url="https://www.edpb.europa.eu/system/files/documents/files/file1/edpb_guidelines_202005_consent_en.pdf",
    ),
    GuidanceSource(
        slug="edpb_guidelines_4_2019",
        short_title="EDPB Guidelines 4/2019",
        title="Guidelines 4/2019 on Article 25 Data Protection by Design and by Default, "
        "version 2.0",
        issuer="European Data Protection Board",
        adopted="2020-10-20",
        url="https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_201904_dataprotection_by_design_and_by_default_v2.0_en.pdf",
    ),
    GuidanceSource(
        slug="wp29_wp248_dpia",
        short_title="WP29 DPIA Guidelines (WP248 rev.01)",
        title="Guidelines on Data Protection Impact Assessment (DPIA) and determining whether "
        "processing is 'likely to result in a high risk', WP248 rev.01, endorsed by the EDPB",
        issuer="Article 29 Working Party (endorsed by the EDPB)",
        adopted="2017-10-04",
        url="https://ec.europa.eu/newsroom/just/redirection/document/47711",
    ),
    GuidanceSource(
        slug="edpb_opinion_28_2024",
        short_title="EDPB Opinion 28/2024",
        title="Opinion 28/2024 on certain data protection aspects related to the processing "
        "of personal data in the context of AI models",
        issuer="European Data Protection Board",
        adopted="2024-12-17",
        url="https://www.edpb.europa.eu/system/files/2024-12/edpb_opinion_202428_ai-models_en.pdf",
    ),
]


def fetch_guidance_pdf(
    source: GuidanceSource, cache_dir: Path, *, force_refresh: bool = False
) -> bytes:
    """Same disk-cache contract as ingest.fetch.fetch_document_xhtml."""
    cache_path = cache_dir / f"{source.slug}.pdf"
    if not force_refresh and cache_path.exists():
        return cache_path.read_bytes()

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(source.url, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        content = response.content
    if not content.startswith(b"%PDF"):
        raise ValueError(f"{source.slug}: {source.url} did not return a PDF")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(content)
    return content


def extract_pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages]


# pypdf logs a warning per glyph it can't map ("Advanced encoding /SymbolSetEncoding
# not implemented yet") — bullet symbols in these PDFs, no lost text.
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class _Paragraph:
    number: int
    page: int  # 1-based
    text: str


def _numbered_paragraphs(pages: list[str]) -> list[_Paragraph]:
    """Splits the document at its numbered-paragraph markers. Only a strictly
    increasing sequence counts — a "1." inside a list in paragraph 40 is not paragraph
    1 — and only the dominant numbering style, so footnote or list numbers in the
    other style don't cut paragraphs apart. Text before paragraph 1 (cover, contents,
    executive summary) is dropped: it restates the numbered body."""
    cleaned = [_PAGE_FURNITURE_RE.sub("", page) for page in pages]
    style = max(
        _PARAGRAPH_STYLES.values(),
        key=lambda pattern: sum(len(pattern.findall(page)) for page in cleaned),
    )

    paragraphs: list[_Paragraph] = []
    expected = 1
    current: _Paragraph | None = None
    for page_number, page in enumerate(cleaned, start=1):
        cursor = 0
        for match in style.finditer(page):
            number = int(match.group(1))
            if number != expected:
                continue
            if current is not None:
                text = f"{current.text} {page[cursor : match.start()]}"
                paragraphs.append(_Paragraph(current.number, current.page, text))
            current = _Paragraph(number, page_number, "")
            cursor = match.end()
            expected += 1
        if current is not None:
            current = _Paragraph(current.number, current.page, f"{current.text} {page[cursor:]}")
    if current is not None:
        paragraphs.append(current)

    return [
        _Paragraph(p.number, p.page, " ".join(p.text.split())) for p in paragraphs if p.text.strip()
    ]


@dataclass(frozen=True)
class _Unit:
    """One chunk's worth of a guidance document, before it becomes an IngestChunk."""

    id_part: str  # "paras:26-28", "paras:40:part:2", "page:5"
    label: str  # "paras 26-28", "para 40 (part 2)", "p. 5"
    page: int
    body: str
    paragraphs: str | None


def _split_long(unit: _Unit) -> list[_Unit]:
    # One numbered paragraph can run past a thousand words (worked examples, tables);
    # cut it into parts that each fit the embedder, all keeping the paragraph's label.
    words = unit.body.split()
    if len(words) <= _TARGET_WORDS * 3 // 2:
        return [unit]
    windows = [words[i : i + _TARGET_WORDS] for i in range(0, len(words), _TARGET_WORDS)]
    return [
        _Unit(
            id_part=f"{unit.id_part}:part:{n}",
            label=f"{unit.label} (part {n})",
            page=unit.page,
            body=" ".join(window),
            paragraphs=unit.paragraphs,
        )
        for n, window in enumerate(windows, start=1)
    ]


def _paragraph_units(paragraphs: list[_Paragraph]) -> list[_Unit]:
    runs: list[list[_Paragraph]] = [[]]
    for paragraph in paragraphs:
        run_words = sum(len(p.text.split()) for p in runs[-1])
        if runs[-1] and run_words + len(paragraph.text.split()) > _TARGET_WORDS:
            runs.append([])
        runs[-1].append(paragraph)

    units: list[_Unit] = []
    for run in runs:
        first, last = run[0].number, run[-1].number
        span = str(first) if first == last else f"{first}-{last}"
        units.append(
            _Unit(
                id_part=f"paras:{span}",
                label=f"para {span}" if first == last else f"paras {span}",
                page=run[0].page,
                body=" ".join(f"{p.number}. {p.text}" for p in run),
                paragraphs=span,
            )
        )
    return units


def _page_units(pages: list[str]) -> list[_Unit]:
    """Fallback for documents without paragraph numbering (WP248): one unit per page,
    skipping near-empty pages and the table of contents (dot leaders)."""
    units: list[_Unit] = []
    for number, page in enumerate(pages, start=1):
        text = " ".join(_PAGE_FURNITURE_RE.sub("", page).split())
        if len(text.split()) < 40 or text.count("....") > 5:
            continue
        units.append(_Unit(f"page:{number}", f"p. {number}", number, text, None))
    return units


def build_guidance_chunks(source: GuidanceSource, pages: list[str]) -> list[IngestChunk]:
    paragraphs = _numbered_paragraphs(pages)
    total_words = sum(len(page.split()) for page in pages)
    numbered_words = sum(len(p.text.split()) for p in paragraphs)
    # Numbered paragraphs must carry most of the document, or the "numbering" found was
    # really a list somewhere inside it.
    if total_words and numbered_words / total_words >= 0.8:
        units = _paragraph_units(paragraphs)
    else:
        units = _page_units(pages)
    if not units:
        raise ValueError(f"{source.slug}: no text extracted — check the PDF")

    chunks: list[IngestChunk] = []
    for unit in [part for whole in units for part in _split_long(whole)]:
        metadata = {
            "source": source.slug,
            "authority": GUIDANCE,
            "issuer": source.issuer,
            "short_title": source.short_title,
            "page": str(unit.page),
            "adopted": source.adopted,
            # PDF viewers honour #page=N, so the link opens where the unit starts.
            "source_url": f"{source.url}#page={unit.page}",
        }
        if unit.paragraphs:
            metadata["paragraphs"] = unit.paragraphs
        chunks.append(
            IngestChunk(
                chunk_id=f"{source.slug}:{unit.id_part}",
                document_id=source.slug,
                content=(
                    f"{source.short_title}, {unit.label} — {source.title} "
                    f"(non-binding guidance, {source.issuer}, {source.adopted})\n\n{unit.body}"
                ),
                metadata=metadata,
            )
        )
    return chunks
