"""After parse.py: check every direction for gaps in its paragraph numbers.
A gap (e.g. 12 -> 14) usually means the parser missed a paragraph start.

Run:  python src/check_numbering.py
"""
import json
import re
from collections import OrderedDict

chunks = json.load(open("data/processed/chunks.json", encoding="utf-8"))
docs = OrderedDict()
for c in chunks:
    docs.setdefault(c["doc_id"], []).append(c["para"])

problems = 0
for doc_id, labels in docs.items():
    numbers = [int(m.group(1)) for label in dict.fromkeys(labels)
               if (m := re.fullmatch(r"(\d+)[A-Z]{0,2}", label))]
    gaps = [(a, b) for a, b in zip(numbers, numbers[1:]) if b - a > 1]
    flag = "  <-- check" if gaps or not numbers else ""
    problems += bool(flag)
    print(f"{doc_id[:14]:14} paras 1-{max(numbers) if numbers else 0:<4} gaps: {gaps[:8] or 'none'}{flag}")
print(f"\n{problems} direction(s) to check")
