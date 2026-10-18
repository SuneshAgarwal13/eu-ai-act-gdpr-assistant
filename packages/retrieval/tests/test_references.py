from retrieval.references import expand_aliases, referenced_chunk_ids


def test_article_with_paragraph_in_a_named_regulation() -> None:
    assert referenced_chunk_ids("What does Article 33(1) GDPR require?") == [
        "gdpr:article:33:paragraph:1",
        "gdpr:article:33",
    ]


def test_unnamed_regulation_looks_in_both() -> None:
    assert referenced_chunk_ids("Explain Art. 5") == ["eu_ai_act:article:5", "gdpr:article:5"]


def test_inserted_article_annex_point_and_recital() -> None:
    ids = referenced_chunk_ids(
        "Under the AI Act, how do Article 4a, Annex iii point 5 and Recital 44 fit?"
    )
    assert ids == [
        "eu_ai_act:article:4a",
        "eu_ai_act:recital:44",
        "eu_ai_act:annex:III:point:5",
        "eu_ai_act:annex:III",
    ]


def test_plain_question_names_nothing() -> None:
    assert referenced_chunk_ids("Do I need to tell people they are talking to a chatbot?") == []


def test_regulation_named_after_the_number_scopes_it() -> None:
    text = "Does the EU AI Act override the 72-hour deadline in Article 33 GDPR?"
    assert referenced_chunk_ids(text) == ["eu_ai_act:article:2:paragraph:7", "gdpr:article:33"]


def test_naming_both_regulations_brings_in_their_interplay_provision() -> None:
    assert referenced_chunk_ids("Does the AI Act change my GDPR obligations?") == [
        "eu_ai_act:article:2:paragraph:7"
    ]


def test_acronyms_gain_their_formal_citation_for_full_text_search() -> None:
    assert expand_aliases("Does the AI Act override the GDPR?") == (
        "Does the AI Act override the GDPR? Regulation (EU) 2016/679 Regulation (EU) 2024/1689"
    )
    assert expand_aliases("What is a chatbot?") == "What is a chatbot?"
