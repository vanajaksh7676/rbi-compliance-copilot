# pytest-v  (give  passed and fail cases)
from parse import ITEM_START, PARA_START, join_lines, paragraph_text, split_long, tidy


def test_paragraph_numbers_on_their_own_line_or_with_text():
    assert PARA_START.match("4.").group(1) == "4"
    assert PARA_START.match("16. With the issue of these Directions").group(1) == "16"
    assert PARA_START.match("1949. The Act") is None  # four digits: a year, not a paragraph
    assert PARA_START.match("4.1 The bank") is None   # a decimal is not a top-level paragraph
    assert PARA_START.match("19A. Notwithstanding").groups() == ("19", "A")  # inserted paragraph


def test_sub_items_are_recognised():
    for marker in ["(1)", "(1A)", "(a)", "(iv)"]:
        assert ITEM_START.match(marker + " text")


def test_real_hyphens_are_kept_when_lines_are_joined():
    assert join_lines(["under sub-", "section (1)"]) == "under sub-section (1)"
    assert join_lines(["all Non-", "Banking Financial Companies"]) == "all Non-Banking Financial Companies"
    assert join_lines(["the Banking", "Regulation Act"]) == "the Banking Regulation Act"


def test_quotes_are_straightened_not_removed():
    assert tidy("‘Bank’ means") == "'Bank' means"


def test_item_marker_joins_its_text_and_suspended_hyphen_is_kept():
    parts = [("", "In these directions:", 3), ("\n", "(1)", 3), ("", "'Amalgamation' means", 3),
             ("", "pre- and post-sanction checks", 3)]
    text = paragraph_text(parts)
    assert "\n(1) 'Amalgamation' means" in text
    assert "pre- and post-sanction" in text


def test_long_paragraph_splits_at_sub_items():
    text = "Lead in:\n" + "\n".join(f"({i}) " + "x" * 300 for i in range(1, 11))
    pieces = split_long(text, limit=1000)
    assert len(pieces) > 1 and all(len(p) <= 1000 for p in pieces)
    assert pieces[1].startswith("(")  # a new piece starts at a sub-item



def test_paragraph_number_without_space_and_two_letter_insertions():
    assert PARA_START.match("13.The bank shall constitute").group(1) == "13"
    assert PARA_START.match("428.[Deleted]").group(1) == "428"
    assert PARA_START.match("219ZB. Without prejudice").groups() == ("219", "ZB")
    assert PARA_START.match("4.1 The bank") is None


def span(text, size, y):
    return {"text": text, "size": size, "origin": (0, y)}


def test_footnote_markers_must_be_small_and_raised():
    from parse import is_marker
    word = span("plus 350", 12, 100)
    assert is_marker(span("2", 8, 97), 12, word)        # raised "2" after "350"
    assert is_marker(span("vi", 8, 97), 12, word)       # roman marker
    assert not is_marker(span("i", 8, 102), 12, word)   # lowered subscript, as in "Mi"
    assert not is_marker(span("100", 9, 100), 12, span("150", 9, 100))  # small table numbers


def test_deleted_paragraph_glued_to_previous_line_is_split():
    from parse import GLUED_DELETED
    m = GLUED_DELETED.match("cases pertaining to exporters. 428.[Deleted] .")
    assert m.group(2).startswith("428.[Deleted]")


def test_running_header_is_found():
    from parse import running_headers
    lines = [{"kind": "line", "page": p, "y": 0.05, "text": "Reserve Bank of India (X) Directions, 2026"}
             for p in range(1, 11)] + [{"kind": "line", "page": 1, "y": 0.5, "text": "body"}]
    assert running_headers(lines) == {"Reserve Bank of India (X) Directions, 2026"}