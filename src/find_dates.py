"""Print the paragraphs that say when a direction starts or what it replaces.
Use it to fill in data/currency.csv.

Run:  python src/find_dates.py 472MD
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows: allow ₹ and other symbols

PATTERN = re.compile(r"come into (force|effect)|commencement|effective from|stand repealed", re.I)
chunks = json.load(open("data/processed/chunks.json", encoding="utf-8"))
prefix = sys.argv[1] if len(sys.argv) > 1 else ""
for c in chunks:
    if c["doc_id"].startswith(prefix) and PATTERN.search(c["text"]):
        print(f"\n{c['doc_id']} | para {c['para']} | page {c['page']}\n{c['text'][:500]}")
