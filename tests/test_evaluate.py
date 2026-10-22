from evaluate import fact_found, retrieval_scores


def test_fact_matching_is_exact_on_numbers():
    assert fact_found("350", "Swap plus 350 basis points")
    assert not fact_found("350", "plus 3502 basis points")      # the old parser bug
    assert not fact_found("25", "a ceiling of 250 per cent")
    assert fact_found("5,000", "pay ₹5000 for each day")
    assert fact_found("0.40", "a floor of 0.40%")
    assert fact_found("immediate", "comes into force with Immediate effect")


def test_retrieval_rank():
    expected = [{"doc": "153MD", "para": "32"}]
    hits = [{"doc_id": "153MD", "para": "31"}, {"doc_id": "153MD", "para": "32"}]
    assert retrieval_scores(hits, expected) == (1, 0.5)
    assert retrieval_scores(hits[:1], expected) == (0, 0.0)
