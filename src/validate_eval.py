"""Check the evaluation questions against YOUR chunks.json before running eval.py.
For every question it checks that the expected paragraph exists and that the expected
facts (numbers) really appear in it. Fix any line marked PROBLEM in eval/questions.jsonl.

Run:  python src/validate_eval.py
"""
import json
import sys

from evaluate import fact_found, load_questions

sys.stdout.reconfigure(encoding="utf-8")
chunks = json.load(open("data/processed/chunks.json", encoding="utf-8"))
problems = 0
for q in load_questions():
    for e in q["expected"]:
        parts = [c for c in chunks if c["doc_id"].startswith(e["doc"]) and c["para"] == e["para"]]
        text = " ".join(c["text"] + " " + " ".join(c["notes"]) for c in parts)
        missing = [f for f in q["facts"] if not fact_found(f, text)]
        if not parts:
            print(f"PROBLEM {q['id']}: {e['doc']} para {e['para']} not found in chunks.json")
            problems += 1
        elif missing:
            print(f"PROBLEM {q['id']}: {e['doc']} para {e['para']} does not contain {missing}")
            problems += 1
        else:
            print(f"ok      {q['id']}: {e['doc']} para {e['para']} (page {parts[0]['page']})")
print(f"\n{problems} problem(s)")
