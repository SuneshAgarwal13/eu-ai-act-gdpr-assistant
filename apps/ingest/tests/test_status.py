from datetime import date

import pytest

from ingest.status import (
    STATUS_DIR,
    build_status_chunks,
    is_stale,
    load_status_notes,
    parse_status_note,
)

NOTE = """---
title: Example amendment
as_of: 2026-10-18
sources:
  - https://example.invalid/procedure
---

## Where it stands

Adopted on
1 January 2026.

## What changes

Article 1 is replaced.
"""


def test_each_section_becomes_a_dated_status_chunk() -> None:
    chunks = build_status_chunks(parse_status_note("example", NOTE))

    assert [c.chunk_id for c in chunks] == [
        "status:example:where-it-stands",
        "status:example:what-changes",
    ]
    first = chunks[0]
    assert first.content == (
        "Where it stands — status note as of 2026-10-18 (Example amendment)\n\n"
        "Adopted on 1 January 2026."
    )
    assert first.metadata["authority"] == "status"
    assert first.metadata["as_of"] == "2026-10-18"
    assert first.metadata["source_url"] == "https://example.invalid/procedure"


def test_note_without_sources_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        parse_status_note("bad", NOTE.replace("  - https://example.invalid/procedure\n", ""))


def test_staleness_threshold() -> None:
    note = parse_status_note("example", NOTE)
    assert not is_stale(note, date(2027, 1, 16))
    assert is_stale(note, date(2027, 1, 17))


def test_checked_in_notes_parse() -> None:
    notes = load_status_notes(STATUS_DIR)
    assert notes, "apps/ingest/status/ has no notes"
    assert all(note.sections for note in notes)
