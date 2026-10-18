from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentSource:
    """One legal instrument to ingest. `celex_id` drives the actual fetch (via the
    CELLAR content-negotiation API — see fetch.py); `eli_uri` is retained for
    citation/provenance display only, since the literal ELI URL is blocked by
    EUR-Lex's WAF for non-browser clients."""

    slug: str
    name: str
    celex_id: str
    eli_uri: str
    # EUR-Lex consolidated version ("0" + CELEX + "-" + date) to take the articles and
    # annexes from, so amendments are in force in the corpus. Consolidated texts carry
    # no recitals; those still come from `celex_id`, the Official Journal text.
    consolidated_celex: str | None = None
    # An amending act: its articles are editing instructions ("Article 6 is amended as
    # follows ...") already folded into the consolidated text, so only its recitals,
    # which explain the changes, are worth retrieving.
    recitals_only: bool = False

    @property
    def consolidated_as_of(self) -> str | None:
        """"02024R1689-20260727" -> "2026-07-27"."""
        if self.consolidated_celex is None:
            return None
        date = self.consolidated_celex.rsplit("-", 1)[1]
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"

    def eurlex_url(self, anchor: str, *, consolidated: bool = False) -> str:
        """Human-readable EUR-Lex page for this instrument, scrolled to `anchor` — the
        same element ids the parser keys on ("art_50", "rct_44", "anx_III"). Browsers
        get through EUR-Lex's WAF; only scripted clients are blocked."""
        if consolidated and self.consolidated_celex:
            celex = self.consolidated_celex
            return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}#{anchor}"
        path = self.eli_uri.removeprefix("http://data.europa.eu/eli/")
        return f"https://eur-lex.europa.eu/eli/{path}/eng#{anchor}"


DOCUMENTS: list[DocumentSource] = [
    DocumentSource(
        slug="eu_ai_act",
        name="Regulation (EU) 2024/1689 (Artificial Intelligence Act)",
        celex_id="32024R1689",
        eli_uri="http://data.europa.eu/eli/reg/2024/1689/oj",
        # As amended by Regulation (EU) 2026/1744 (Digital Omnibus on AI). Check
        # EUR-Lex for a newer consolidation before re-ingesting.
        consolidated_celex="02024R1689-20260727",
    ),
    DocumentSource(
        slug="eu_ai_act_amendment_2026",
        name="Regulation (EU) 2026/1744 (Digital Omnibus on AI, amending the AI Act)",
        celex_id="32026R1744",
        eli_uri="http://data.europa.eu/eli/reg/2026/1744/oj",
        recitals_only=True,
    ),
    DocumentSource(
        slug="gdpr",
        name="Regulation (EU) 2016/679 (General Data Protection Regulation)",
        celex_id="32016R0679",
        eli_uri="http://data.europa.eu/eli/reg/2016/679/oj",
    ),
]
