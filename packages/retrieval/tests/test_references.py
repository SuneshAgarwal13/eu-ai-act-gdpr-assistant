from retrieval.references import referenced_chunk_ids


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
