"""Hand-written, dated notes on where the law stands: amendments adopted or pending,
guidance still in draft. Each note lives in apps/ingest/status/*.md and is ingested as
authority=status, one chunk per "## " section, carrying the date it was last checked.

These are the one part of the corpus nobody can re-fetch, so ingest warns once a note
is older than STALE_AFTER and needs re-checking against its sources.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ingest.chunks import IngestChunk

STATUS = "status"
STATUS_DIR = Path(__file__).resolve().parents[2] / "status"
STALE_AFTER = timedelta(days=90)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class StatusNote:
    slug: str
    title: str
    as_of: date
    sources: list[str]
    sections: list[tuple[str, str]]  # (heading, body)


def parse_status_note(slug: str, text: str) -> StatusNote:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"status note {slug}: missing --- frontmatter ---")
    header, body = match.groups()

    fields: dict[str, str] = {}
    sources: list[str] = []
    for line in header.splitlines():
        if line.startswith("  - "):
            sources.append(line.removeprefix("  - ").strip())
        elif ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    if "title" not in fields or "as_of" not in fields or not sources:
        raise ValueError(f"status note {slug}: needs title, as_of and at least one source")

    parts = _SECTION_RE.split(body)
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    sections = [
        (heading.strip(), " ".join(section.split()))
        for heading, section in zip(parts[1::2], parts[2::2], strict=True)
    ]
    return StatusNote(
        slug=slug,
        title=fields["title"],
        as_of=date.fromisoformat(fields["as_of"]),
        sources=sources,
        sections=sections,
    )


def load_status_notes(directory: Path = STATUS_DIR) -> list[StatusNote]:
    return [
        parse_status_note(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.md"))
    ]


def is_stale(note: StatusNote, today: date) -> bool:
    return today - note.as_of > STALE_AFTER


def _slugify(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def build_status_chunks(note: StatusNote) -> list[IngestChunk]:
    return [
        IngestChunk(
            chunk_id=f"status:{note.slug}:{_slugify(heading)}",
            document_id=f"status:{note.slug}",
            content=(
                f"{heading} — status note as of {note.as_of.isoformat()} ({note.title})\n\n{body}"
            ),
            metadata={
                "source": f"status:{note.slug}",
                "authority": STATUS,
                "title": note.title,
                "heading": heading,
                "as_of": note.as_of.isoformat(),
                "source_url": note.sources[0],
            },
        )
        for heading, body in note.sections
    ]
