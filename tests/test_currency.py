from datetime import date

from currency import CurrencyCheck

ROWS = """doc_id,effective_from,replaced_by,replaced_from,scope,note
NEW,2027-04-01,,,,new rules
OLD,,NEW,2027-04-01,all,whole direction
"""


def make(tmp_path):
    path = tmp_path / "currency.csv"
    path.write_text(ROWS, encoding="utf-8")
    chunks = [{"doc_id": "NEW", "title": "Reserve Bank of India (Commercial Banks – New Rules) Directions, 2026"},
              {"doc_id": "OLD", "title": "Reserve Bank of India (Commercial Banks – Old Rules) Directions, 2025"}]
    return CurrencyCheck(chunks, path)


def test_not_yet_in_force_and_being_replaced(tmp_path):
    cc = make(tmp_path)
    before = date(2026, 10, 18)
    assert cc.status("NEW", before).startswith("NOT YET IN FORCE")
    assert "will be replaced fully by New Rules Directions from 1 April 2027" in cc.status("OLD", before)
    assert not cc.is_replaced("OLD", before)


def test_after_the_start_date(tmp_path):
    cc = make(tmp_path)
    after = date(2027, 5, 1)
    assert cc.status("NEW", after) == "in force"
    assert cc.status("OLD", after).startswith("REPLACED fully")
    assert cc.is_replaced("OLD", after)


def test_expired_temporary_rule_and_amendment_notes(tmp_path):
    cc = make(tmp_path)
    chunk = {"doc_id": "X", "para": "27", "text": "is temporarily withdrawn for the period until August 31, 2026.",
             "notes": ["Footnote v: Substituted with effect from August 25, 2026, vide ..."]}
    warnings = cc.warnings([chunk], date(2026, 10, 18))
    assert any("amended (substituted w.e.f. 25 August 2026)" in w for w in warnings)
    assert any("valid until 31 August 2026" in w for w in warnings)
    assert not any("valid until" in w for w in cc.warnings([chunk], date(2026, 8, 1)))  # not expired yet
