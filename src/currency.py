"""Currency check: is the rule in a cited paragraph still valid TODAY?

Four checks, all done by code (not by the LLM), so the warnings are always shown:
  1. NOT YET IN FORCE  - the direction starts on a future date (data/currency.csv)
  2. BEING REPLACED    - a newer direction replaces this one, now or later (data/currency.csv)
  3. AMENDED           - the paragraph's footnotes say "Substituted / Inserted / Deleted w.e.f. ..."
  4. EXPIRED           - the text has a temporary rule "until <date>" and that date has passed

Set CURRENCY_DATE=2027-05-01 in .env to see how the answers change on another day.
"""
import csv
import os
import re
from datetime import date, datetime
from pathlib import Path

CURRENCY = Path("data/currency.csv")
MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December")
DATE = rf"(?:{MONTHS}) \d{{1,2}}, \d{{4}}"                       # "August 31, 2026"
UNTIL = re.compile(rf"\b(?:until|till)\s+({DATE})")               # temporary rules
AMENDED = re.compile(rf"\b(Substituted|Inserted|Deleted|Amended|Modified|Added)\b"
                     rf".*?(?:w\.e\.f\.|with effect from)\s*({DATE})", re.IGNORECASE)


def today():
    value = os.getenv("CURRENCY_DATE")
    return date.fromisoformat(value) if value else date.today()


def to_date(text):
    """'August 31, 2026' or '2026-08-31' -> date. Returns None if empty or unreadable."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def nice(d):
    return f"{d.day} {d:%B %Y}"  # 1 April 2027


def short_title(title):
    """'Reserve Bank of India (Commercial Banks – Governance) Directions, 2025 (Updated...)'
    -> 'Governance Directions'"""
    m = re.search(r"Commercial Banks\s*[-–:]\s*(.+?)\)\s*Directions", title or "")
    return f"{m.group(1).strip()} Directions" if m else (title or "")[:60]


class CurrencyCheck:
    def __init__(self, chunks, path=CURRENCY):
        self.titles = {}
        for c in chunks:
            self.titles.setdefault(c["doc_id"], c["title"])
        self.rows = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []

    def name(self, doc_id):
        return short_title(self.titles.get(doc_id, doc_id))

    def status(self, doc_id, on=None):
        """One line for the LLM prompt and the UI: is this direction in force on that day?"""
        on = on or today()
        start, replaced, later = None, [], []
        for r in (r for r in self.rows if r["doc_id"] == doc_id):
            if to_date(r["effective_from"]) and to_date(r["effective_from"]) > on:
                start = to_date(r["effective_from"])
            if r["replaced_by"]:
                when = to_date(r["replaced_from"])
                what = "fully" if r["scope"] == "all" else f"partly ({r['note']})"
                text = f"{what} by {self.name(r['replaced_by'])}"
                if when and when <= on:
                    replaced.append(f"{text} since {nice(when)}")
                else:
                    later.append(f"{text} from {nice(when) if when else 'a date not yet set'}")
        if start:
            return f"NOT YET IN FORCE: takes effect from {nice(start)}"
        if replaced:
            rest = f"; will be replaced {'; '.join(later)}" if later else ""
            return "REPLACED " + "; ".join(replaced) + rest
        if later:
            return "in force now; will be replaced " + "; ".join(later)
        return "in force"

    def is_replaced(self, doc_id, on=None):
        """True only when the WHOLE direction is already replaced. Those chunks are dropped."""
        on = on or today()
        return any(r["doc_id"] == doc_id and r["scope"] == "all" and to_date(r["replaced_from"])
                   and to_date(r["replaced_from"]) <= on for r in self.rows)

    def warnings(self, chunks, on=None):
        """Warnings for the chunks the answer cites. Each warning is a short sentence."""
        on = on or today()
        out = []
        for c in chunks:
            where = f"{self.name(c['doc_id'])}, para {c['para']}"
            status = self.status(c["doc_id"], on)
            if status != "in force":
                out.append(f"{self.name(c['doc_id'])}: {status}.")
            changes = []
            for note in c.get("notes", []):
                m = AMENDED.search(note)
                when = to_date(m.group(2)) if m else None
                if m and when and when > on:
                    out.append(f"{where}: this text is {m.group(1).lower()} with effect from "
                               f"{nice(when)}, which is in the future. Until then the old text applies.")
                elif m:
                    changes.append(f"{m.group(1).lower()} w.e.f. {nice(when) if when else m.group(2)}")
            if changes:
                out.append(f"{where}: amended ({'; '.join(changes)}).")
            for m in UNTIL.finditer(c["text"]):
                when = to_date(m.group(1))
                if when and when < on:
                    out.append(f"{where}: has a temporary rule valid until {nice(when)}. That date "
                               f"has passed, so check whether RBI extended it.")
        return list(dict.fromkeys(out))  # remove repeats, keep order
