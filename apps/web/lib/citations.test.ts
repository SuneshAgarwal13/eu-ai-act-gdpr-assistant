import { describe, expect, it } from "vitest";

import { citationLabel, provenance } from "./citations";

describe("citationLabel", () => {
  it.each([
    [{ source: "eu_ai_act", article: "6", paragraph: "1a" }, "Art. 6(1a)"],
    [{ source: "gdpr", article: "33", paragraph: "1" }, "GDPR Art. 33(1)"],
    [{ source: "gdpr", recital: "85" }, "GDPR Recital 85"],
    [{ source: "eu_ai_act_amendment_2026", recital: "3" }, "Reg. 2026/1744 Recital 3"],
    [{ source: "eu_ai_act", annex: "III", point: "5" }, "Annex III pt 5"],
    [{ source: "eu_ai_act", annex: "IV" }, "Annex IV"],
    [
      { authority: "guidance", short_title: "EDPB Guidelines 9/2022", paragraphs: "31-32", page: "10" },
      "EDPB Guidelines 9/2022, paras 31-32",
    ],
    [{ authority: "guidance", short_title: "WP248", page: "5" }, "WP248, p. 5"],
    [{ authority: "status", as_of: "2026-10-18" }, "Status note · 2026-10-18"],
  ])("labels %o as %s", (metadata, expected) => {
    expect(citationLabel(metadata)).toBe(expected);
  });
});

describe("provenance", () => {
  it("says an amended article is binding, consolidated and by which act", () => {
    expect(
      provenance({
        source: "eu_ai_act",
        article: "6",
        authority: "binding",
        consolidated_as_of: "2026-07-27",
        amended_by: "32026R1744",
        source_url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727#art_6",
      }),
    ).toEqual({
      kind: "law",
      note: "Binding law · consolidated text as of 2026-07-27 · amended by Reg. (EU) 2026/1744",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727#art_6",
    });
  });

  it("marks guidance as non-binding", () => {
    const result = provenance({
      authority: "guidance",
      issuer: "European Data Protection Board",
      adopted: "2023-03-28",
      source_url: "https://www.edpb.europa.eu/x.pdf#page=10",
    });
    expect(result.kind).toBe("guidance");
    expect(result.note).toBe("Non-binding guidance · European Data Protection Board · 2023-03-28");
  });

  it("refuses a non-http link", () => {
    expect(provenance({ source_url: "javascript:alert(1)" }).url).toBeNull();
  });
});
