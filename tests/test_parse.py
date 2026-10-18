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
