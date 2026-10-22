"""Phase 5: score the copilot on questions with known answers (eval/questions.jsonl).

What is measured (all by code, so the score is the same every time you run it):
  RETRIEVAL   hit@5  - is the right paragraph among the 5 search results?
              MRR    - how high is it? (1.0 = always first, 0.5 = usually second)
  ANSWER      citation  - does the answer cite the right paragraph?
              facts     - does the answer contain the right numbers (e.g. "350")?
              refusal   - for questions NOT in the corpus, does it say "I could not find this"?
              false refusal - did it refuse a question it should have answered?
              warning   - for currency questions, is the right warning shown?
  OPTIONAL    --judge   - an LLM checks that every sentence is supported by the sources
                          (faithfulness). Costs one extra LLM call per question.

Run:
  python src/evaluate.py --retrieval-only            # free: no LLM calls
  python src/evaluate.py --retrieval-only --no-rerank  # compare without the reranker
  python src/evaluate.py                             # full run (about 30 LLM calls)
  python src/evaluate.py --judge                     # full run + faithfulness judge
  python src/evaluate.py --only q07,r01              # just a few questions
Results are saved in eval/results/ so you can compare runs.
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

QUESTIONS = Path("eval/questions.jsonl")
RESULTS = Path("eval/results")


def load_questions(path=QUESTIONS):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def fact_found(fact, text):
    """'5,000' matches '₹5,000' or '5000'; '25' does not match '250'."""
    def norm(s):
        return re.sub(r"(?<=\d),(?=\d)", "", s.lower())
    return re.search(rf"(?<![\d.]){re.escape(norm(fact))}(?![\d])", norm(text)) is not None


def matches(chunk_or_source, expected):
    return any(chunk_or_source["doc_id"].startswith(e["doc"]) and chunk_or_source["para"] == e["para"]
               for e in expected)


def retrieval_scores(hits, expected):
    """hit = right paragraph in the list; rr = 1 / its position (0 if missing)."""
    for rank, c in enumerate(hits, start=1):
        if matches(c, expected):
            return 1, 1 / rank
    return 0, 0.0


JUDGE = """You check an answer against its sources. Reply with JSON only:
{"faithful": true or false, "unsupported": "the first claim not supported by the sources, or empty"}
An answer is faithful if every fact in it (numbers, conditions, dates) is stated in the sources.
A refusal ("I could not find this...") is always faithful."""


def judge(answer, contexts):
    import providers
    sources = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(contexts, start=1))
    text, tokens = providers.chat(JUDGE, f"Sources:\n{sources}\n\nAnswer:\n{answer}")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        verdict = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        verdict = {}
    return bool(verdict.get("faithful")), verdict.get("unsupported", text[:200]), tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true", help="only test search (no LLM cost)")
    parser.add_argument("--no-rerank", action="store_true", help="switch the reranker off")
    parser.add_argument("--judge", action="store_true", help="also score faithfulness with an LLM")
    parser.add_argument("--only", default="", help="comma-separated question ids, e.g. q01,r02")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    questions = load_questions()
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    from pipeline import Copilot
    copilot = Copilot(use_reranker=not args.no_rerank)
    rows = []
    for q in questions:
        row = {"id": q["id"], "type": q["type"], "question": q["question"]}
        hits = copilot.retriever.search(q["question"], k=5)
        if q["type"] == "answer":
            row["hit@5"], row["rr"] = retrieval_scores(hits, q["expected"])
        row["top_result"] = f"{hits[0]['doc_id'][:6]} para {hits[0]['para']}" if hits else ""

        if not args.retrieval_only:
            result = copilot.ask(q["question"])
            answer = result["answer"]
            row["answer"] = answer.replace("\n", " ")
            row["tokens"] = result["tokens"]
            if q["type"] == "refuse":
                row["refused_ok"] = int(not result["found"])
            else:
                row["false_refusal"] = int(not result["found"])
                row["citation_ok"] = int(any(matches(s, q["expected"]) for s in result["sources"]))
                row["facts_ok"] = int(all(fact_found(f, answer) for f in q["facts"]))
                if q["warning"]:
                    row["warning_ok"] = int(any(q["warning"] in w for w in result["warnings"]))
            if args.judge:
                row["faithful"], row["unsupported"], extra = judge(answer, result["contexts"])
                row["faithful"] = int(row["faithful"])
                row["tokens"] += extra
            time.sleep(1)  # stay well under the API rate limit

        rows.append(row)
        marks = " ".join(f"{k}={v}" for k, v in row.items()
                         if k in ("hit@5", "citation_ok", "facts_ok", "refused_ok", "false_refusal",
                                  "warning_ok", "faithful"))
        print(f"{q['id']}: {marks} | top: {row['top_result']}")

    summary = summarise(rows)
    print("\n=== SUMMARY ===")
    for name, value in summary.items():
        print(f"{name:28} {value}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    mode = "retrieval" if args.retrieval_only else "full"
    mode += "_norerank" if args.no_rerank else ""
    out = RESULTS / f"{stamp}_{mode}.csv"
    fields = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (RESULTS / f"{stamp}_{mode}_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nSaved {out}")


def summarise(rows):
    def rate(key, kind=None):
        values = [r[key] for r in rows if key in r and (kind is None or r["type"] == kind)]
        return f"{sum(values) / len(values):.0%} ({sum(values)}/{len(values)})" if values else "-"

    answerable = [r for r in rows if r["type"] == "answer"]
    summary = {
        "questions": len(rows),
        "retrieval hit@5": rate("hit@5"),
        "retrieval MRR": f"{sum(r['rr'] for r in answerable) / len(answerable):.2f}" if answerable else "-",
        "correct citation": rate("citation_ok"),
        "correct facts": rate("facts_ok"),
        "correct refusals": rate("refused_ok"),
        "false refusals": rate("false_refusal"),
        "currency warning shown": rate("warning_ok"),
        "faithful (LLM judge)": rate("faithful"),
        "tokens": sum(r.get("tokens", 0) for r in rows),
    }
    return {k: v for k, v in summary.items() if v != "-"}


if __name__ == "__main__":
    main()
