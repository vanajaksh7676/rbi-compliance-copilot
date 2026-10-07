from parse import PARA_START, parse_pages, size_chunks


def test_paragraph_numbers_are_detected():
    assert PARA_START.match("3.1 The bank shall").group(1) == "3.1"
    assert PARA_START.match("12. Definitions").group(1) == "12"
    assert PARA_START.match("2025 was a year") is None  # four digits: a year


def test_small_heading_joins_next_paragraph():
    paras = [{"para": "4", "page": 2, "text": "4. Definitions"},
             {"para": "4.1", "page": 2, "text": "x" * 300}]
    out = size_chunks(paras)
    assert len(out) == 1 and out[0]["text"].startswith("4. Definitions")


def test_footnote_line_is_not_a_paragraph():
    assert PARA_START.match("1 Inserted w.e.f. October 1, 2026, vide ...") is None


def test_toc_footnote_and_page_number_are_removed():
    page = "\n".join([
        "Table of Contents",
        "Chapter I- Preliminary ........................ 2",
        "Introduction",
        "These directions are issued under Section 35A of the Act. " * 4,
        "5. All other expressions have the meaning in the Act. " * 4,
        "Shares or Voting Rights) Amendment Directions, 2026 dated October 1, 2026",
        "3",
    ])
    text = " ".join(p["text"] for p in parse_pages([(1, page)]))
    assert "Table of Contents" not in text
    assert "........" not in text
    assert "Amendment Directions" not in text
    assert "Introduction" in text


def test_heading_goes_with_the_paragraph_after_it():
    page = "\n".join([
        "1. First paragraph of the direction goes here and is long enough. " * 5,
        "B. Applicability",
        "2. Second paragraph starts after its heading and is long enough. " * 5,
    ])
    paras = parse_pages([(1, page)])
    assert paras[0]["para"] == "1" and "Applicability" not in paras[0]["text"]
    assert paras[1]["para"] == "2" and paras[1]["text"].startswith("B. Applicability")


def test_sub_heading_like_D1_goes_with_next_paragraph():
    page = "\n".join([
        "14. Earlier paragraph that is long enough to stand alone here. " * 5,
        "D.1 Single Counterparty",
        "15. The sum of all the exposure values shall not be higher. " * 5,
    ])
    paras = parse_pages([(1, page)])
    assert "Single Counterparty" not in paras[0]["text"]
    assert paras[1]["para"] == "15"


def test_merged_paragraphs_get_a_range_label():
    paras = [{"para": "1", "page": 1, "text": "1. Short."},
             {"para": "2", "page": 1, "text": "2. " + "y" * 300}]
    assert size_chunks(paras)[0]["para"] == "1–2"