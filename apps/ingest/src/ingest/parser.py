from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from ingest.documents import DocumentSource

_CHAPTER_ID_RE = re.compile(r"^cpt_[IVXLCDM]+$")
_SECTION_ID_RE = re.compile(r"^cpt_[IVXLCDM]+\.sct_(\d+)$")
# Consolidated texts insert articles between existing ones ("4a", "75b").
_ARTICLE_ID_RE = re.compile(r"^art_(\d+[a-z]?)$")
_RECITAL_ID_RE = re.compile(r"^rct_(\d+)$")
_ARTICLE_PARAGRAPH_ID_RE = re.compile(r"^(\d+)\.(\d+)$")
_ANNEX_ID_RE = re.compile(r"^anx_([IVXLCDM]+)$")
# Annex headings come in two shapes: "Section A — ..." (Annexes I, VIII, XI) and
# "3. Quality management system" (Annexes VII, X). Either names the block below it.
_ANNEX_HEADING_KEY_RE = re.compile(r"^(?:Section\s+([A-Z0-9]+)\b|(\d+)\.)")
_ANNEX_ITEM_LABEL_RE = re.compile(r"^\(?([0-9]+(?:\.[0-9]+)*|[a-z])\)?\.?$")
_LEADING_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s")
_CONSOLIDATED_PARAGRAPH_LABEL_RE = re.compile(r"^(\d+[a-z]?)\.$")
_CELEX_HREF_RE = re.compile(r"/celex/(\w+)$")


@dataclass(frozen=True)
class Point:
    label: str
    text: str


@dataclass(frozen=True)
class Paragraph:
    """`number` is None for articles with a single, unnumbered body (e.g. a
    "Definitions" article whose text isn't split into "1.", "2." sub-paragraphs) —
    real EU legislative drafting doesn't guarantee every article is paragraph-numbered."""

    number: str | None
    text: str
    points: list[Point] = field(default_factory=list)


@dataclass(frozen=True)
class Article:
    number: str
    title: str
    chapter_number: str | None
    chapter_title: str | None
    section_number: str | None
    section_title: str | None
    paragraphs: list[Paragraph] = field(default_factory=list)
    # CELEX ids of the acts that amended this article (consolidated texts only).
    amended_by: tuple[str, ...] = ()

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs if p.text)


@dataclass(frozen=True)
class Recital:
    number: str
    text: str


@dataclass(frozen=True)
class AnnexItem:
    """One citable block of an annex: a numbered point ("5", "3.1", "A.2", "1(a)") or a
    headed paragraph block. `key` is how a practitioner would cite it."""

    key: str
    heading: str | None
    text: str


@dataclass(frozen=True)
class Annex:
    number: str
    title: str
    intro: str
    items: list[AnnexItem] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        parts = [self.intro] if self.intro else []
        parts.extend(item.text for item in self.items)
        return "\n".join(parts)


@dataclass(frozen=True)
class ParsedDocument:
    source: DocumentSource
    articles: list[Article] = field(default_factory=list)
    recitals: list[Recital] = field(default_factory=list)
    annexes: list[Annex] = field(default_factory=list)


def _text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def _classes(tag: Tag) -> set[str]:
    # The lxml-xml parser doesn't split `class` into a list the way the HTML parsers
    # do, so a tag with "list grid-list-column-1" comes back as one string.
    value = tag.get("class") or ""
    return set(value.split() if isinstance(value, str) else value)


def _title_text(div: Tag) -> str:
    title_div = div.find("div", class_="eli-title", recursive=False)
    return _text(title_div)


def _parse_points(container: Tag) -> list[Point]:
    """Numbered/lettered points render as one <table> per point, first cell the
    label ("(a)", "(1)", ...), second cell the point text."""
    points: list[Point] = []
    for table in container.find_all("table", recursive=False):
        cells = table.find_all("td")
        if len(cells) < 2:
            continue
        points.append(Point(label=_text(cells[0]), text=_text(cells[1])))
    return points


def _paragraph_text(intro: str, points: list[Point]) -> str:
    parts = [intro] if intro else []
    parts.extend(f"{pt.label} {pt.text}" for pt in points)
    return " ".join(parts).strip()


def _paragraph_from_container(container: Tag, number: str | None) -> Paragraph:
    intro = " ".join(
        _text(p) for p in container.find_all("p", class_="oj-normal", recursive=False)
    )
    points = _parse_points(container)
    return Paragraph(number=number, text=_paragraph_text(intro, points), points=points)


def _parse_article_paragraphs(article_div: Tag, article_number: str) -> list[Paragraph]:
    padded = article_number.zfill(3)
    paragraph_divs = [
        child
        for child in article_div.find_all("div", recursive=False)
        if child.get("id", "").startswith(f"{padded}.")
    ]
    if paragraph_divs:
        paragraphs = []
        for div in paragraph_divs:
            match = _ARTICLE_PARAGRAPH_ID_RE.match(div["id"])
            para_number = str(int(match.group(2))) if match else None
            paragraphs.append(_paragraph_from_container(div, para_number))
        return paragraphs

    # No numbered paragraph divs: the article body's direct <p class="oj-normal">/
    # <table> children form one implicit, unnumbered paragraph.
    return [_paragraph_from_container(article_div, None)]


# --- Consolidated-text markup --------------------------------------------------------
# EUR-Lex consolidated versions (CELEX "0..." ids) use a different HTML vocabulary from
# the Official Journal: "norm"/"grid-list" classes instead of "oj-normal"/<table>, and
# "modref" markers (▼B, ▼M1) wherever an amending act changed the text.


def _is_consolidated(soup: BeautifulSoup) -> bool:
    return soup.find("p", class_="title-article-norm") is not None


def _take_amending_acts(tag: Tag) -> tuple[str, ...]:
    """Reads the ▼M1-style markers inside `tag` for the CELEX ids of the acts that
    amended it, then removes the markers so they don't leak into chunk text."""
    acts: dict[str, None] = {}
    for marker in tag.select("p.modref"):
        for anchor in marker.select("a[href]"):
            if match := _CELEX_HREF_RE.search(anchor["href"]):
                acts[match.group(1)] = None
        marker.decompose()
    return tuple(acts)


def _consolidated_paragraphs(article_div: Tag) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for child in article_div.find_all("div", class_="norm", recursive=False):
        label = child.find("span", class_="no-parag", recursive=False)
        match = _CONSOLIDATED_PARAGRAPH_LABEL_RE.match(_text(label)) if label else None
        if match is None:
            continue
        # Text keeps its "1a." label, as OJ paragraph text does, so the article-level
        # chunk still reads as numbered paragraphs.
        paragraphs.append(Paragraph(number=match.group(1), text=_text(child)))
    if paragraphs:
        return paragraphs
    # One unnumbered body: every direct child except the heading, title and markers.
    body = [
        child
        for child in article_div.find_all(recursive=False)
        if not {"title-article-norm", "eli-title", "modref"} & _classes(child)
    ]
    return [Paragraph(number=None, text=" ".join(t for t in map(_text, body) if t))]


def _annex_item_key(label: str, heading_key: str | None, heading_is_section: bool) -> str:
    """"5" under no heading -> "5"; "1" under "Section A" -> "A.1"; "(a)" under "1." ->
    "1(a)"; "3.1" under "3." -> "3.1" (the label already carries the heading)."""
    match = _ANNEX_ITEM_LABEL_RE.match(label)
    core = match.group(1) if match else label
    if heading_key is None:
        return core
    if core.isalpha():
        return f"{heading_key}({core})"
    if heading_is_section:
        return f"{heading_key}.{core}"
    return core


def _parse_annex(div: Tag, number: str) -> Annex:
    """Annexes have no per-point ids, and their layout varies: numbered <table>s
    (most), <div class="oj-enumeration-spacing"> items (Annex VI), and headed blocks of
    plain paragraphs (Annexes VII, X). One walk over the direct children handles all
    three: track the current heading, emit one item per numbered element, and fold
    plain paragraphs under a heading into one item keyed by that heading."""
    _take_amending_acts(div)
    titles = div.find_all("p", class_="oj-doc-ti", recursive=False)
    # OJ: two "oj-doc-ti" lines ("ANNEX III", then the title). Consolidated: usually
    # "title-annex-2", occasionally a second "title-annex-1" (Annex X).
    consolidated_title = div.find("p", class_="title-annex-2", recursive=False)
    consolidated_lines = div.find_all("p", class_="title-annex-1", recursive=False)
    if consolidated_title is not None:
        title = _text(consolidated_title)
    elif len(consolidated_lines) > 1:
        title = _text(consolidated_lines[1])
    else:
        title = _text(titles[1]) if len(titles) > 1 else ""

    intro_parts: list[str] = []
    items: list[AnnexItem] = []
    heading: str | None = None
    heading_key: str | None = None
    heading_is_section = False
    pending: list[str] = []  # plain paragraphs under the current heading
    seen: dict[str, int] = {}
    position = 0  # items under the current heading, for unnumbered lists (Annex II)

    def add(key: str, text: str) -> None:
        # Consolidated texts lay out "3.1. ... shall include:" and its points (a)-(e) as
        # siblings, where the OJ nests them; fold the points back into their parent.
        if key_is_letter(key) and items and items[-1].heading == heading and not (
            key_is_letter(items[-1].key)
        ):
            last = items[-1]
            items[-1] = AnnexItem(key=last.key, heading=last.heading, text=f"{last.text} {text}")
            return
        # Keys are unique within an annex; a repeat (rare drafting quirk) gets a suffix
        # rather than overwriting its sibling.
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}-{seen[key]}"
        items.append(AnnexItem(key=key, heading=heading, text=text))

    def key_is_letter(key: str) -> bool:
        return key.isalpha() or key.endswith(")")

    def flush_pending() -> None:
        if pending:
            # "3. Overview" names its own block; "Section A" paragraphs introduce the
            # points numbered A.1, A.2, ... so they get their own key.
            if heading_key is None:
                key = "intro"
            else:
                key = f"{heading_key}.intro" if heading_is_section else heading_key
            add(key, " ".join(pending))
            pending.clear()

    def item_label(label: str, text: str) -> str:
        # The number sits in the first cell, or (spacer first cell) at the start of the
        # text; failing both it is a bullet list, numbered by position.
        if _ANNEX_ITEM_LABEL_RE.match(label):
            return label
        match = _LEADING_NUMBER_RE.match(text)
        return match.group(1) if match else str(position)

    for child in div.find_all(recursive=False):
        classes = _classes(child)
        skip = {"oj-doc-ti", "title-annex-1", "title-annex-2", "modref"}
        if child.name == "hr" or skip & classes:
            continue
        if child.name == "p" and {"oj-ti-grseq-1", "title-gr-seq-level-1"} & classes:
            text = _text(child)
            match = _ANNEX_HEADING_KEY_RE.match(text)
            if match:
                flush_pending()
                heading = text
                heading_key = match.group(1) or match.group(2)
                heading_is_section = match.group(1) is not None
                position = 0
            elif heading is not None:
                # A second heading line titles the first ("Section 2" + "Additional
                # information to be provided by ...").
                heading = f"{heading} — {text}"
            continue
        if child.name == "table":
            cells = child.find_all("td")
            if len(cells) >= 2:
                position += 1
                label = item_label(_text(cells[0]), _text(child))
                add(_annex_item_key(label, heading_key, heading_is_section), _text(child))
            continue
        if child.name == "div" and "grid-container" in classes:
            position += 1
            label_div = child.select_one("div.grid-list-column-1")
            add(
                _annex_item_key(
                    item_label(_text(label_div), _text(child)), heading_key, heading_is_section
                ),
                _text(child),
            )
            continue
        if child.name == "div":  # "oj-enumeration-spacing" (OJ) or a bare item div
            position += 1
            text = _text(child)
            if not text:
                continue
            label = item_label("", text)
            add(_annex_item_key(label, heading_key, heading_is_section), text)
            continue
        if child.name == "p":
            text = _text(child)
            if not text:
                continue
            if heading is None:
                intro_parts.append(text)
            else:
                pending.append(text)
    flush_pending()

    return Annex(number=number, title=title, intro=" ".join(intro_parts), items=items)


def _division_title(div: Tag, consolidated: bool) -> str:
    if consolidated:
        return _text(div.find("p", class_="title-division-2", recursive=False))
    return _title_text(div)


def parse_document(xhtml: str, source: DocumentSource) -> ParsedDocument:
    """Parses ELI-compliant XHTML (as served by the CELLAR API — see fetch.py)
    preserving Chapter -> Section -> Article -> Paragraph -> Point nesting, plus
    Recitals and Annexes collected separately. Walks every <div id="..."> in document order,
    tracking current chapter/section as state — a flat preorder scan is sufficient
    since chapter/section divs always appear before the articles they contain.

    Also reads EUR-Lex consolidated versions (detected by their markup), which carry
    the articles and annexes as amended but no recitals."""
    soup = BeautifulSoup(xhtml, "lxml-xml")
    consolidated = _is_consolidated(soup)

    articles: list[Article] = []
    recitals: list[Recital] = []
    annexes: list[Annex] = []

    current_chapter_number: str | None = None
    current_chapter_title: str | None = None
    current_section_number: str | None = None
    current_section_title: str | None = None

    for div in soup.find_all("div", id=True):
        div_id = div["id"]
        classes = div.get("class") or []

        if _CHAPTER_ID_RE.match(div_id):
            current_chapter_number = div_id.removeprefix("cpt_")
            current_chapter_title = _division_title(div, consolidated)
            current_section_number = None
            current_section_title = None
        elif section_match := _SECTION_ID_RE.match(div_id):
            current_section_number = section_match.group(1)
            current_section_title = _division_title(div, consolidated)
        elif consolidated and "eli-subdivision" in classes and (
            article_match := _ARTICLE_ID_RE.match(div_id)
        ):
            articles.append(
                Article(
                    number=article_match.group(1),
                    title=_text(div.find("p", class_="stitle-article-norm")),
                    chapter_number=current_chapter_number,
                    chapter_title=current_chapter_title,
                    section_number=current_section_number,
                    section_title=current_section_title,
                    amended_by=_take_amending_acts(div),
                    paragraphs=_consolidated_paragraphs(div),
                )
            )
        elif "eli-subdivision" in classes and (article_match := _ARTICLE_ID_RE.match(div_id)):
            number = article_match.group(1)
            title = _text(div.find("p", class_="oj-sti-art")) or _title_text(div)
            articles.append(
                Article(
                    number=number,
                    title=title,
                    chapter_number=current_chapter_number,
                    chapter_title=current_chapter_title,
                    section_number=current_section_number,
                    section_title=current_section_title,
                    paragraphs=_parse_article_paragraphs(div, number),
                )
            )
        elif "eli-subdivision" in classes and (recital_match := _RECITAL_ID_RE.match(div_id)):
            number = recital_match.group(1)
            points = _parse_points(div)
            text = points[0].text if points else _text(div)
            recitals.append(Recital(number=number, text=text))
        elif annex_match := _ANNEX_ID_RE.match(div_id):
            annexes.append(_parse_annex(div, annex_match.group(1)))

    return ParsedDocument(source=source, articles=articles, recitals=recitals, annexes=annexes)
