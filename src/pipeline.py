"""The whole copilot in one call: search -> currency check -> answer -> sources + warnings.

Run:  python src/pipeline.py "What are the qualifications for a CFO?"
"""
import re
import sys

from currency import CurrencyCheck, today
from generate import NOT_FOUND, generate
from retrieve import Retriever


class Copilot:
    def __init__(self, use_reranker=True):
        self.retriever = Retriever(use_reranker=use_reranker)
        self.currency = CurrencyCheck(self.retriever.chunks)

    def ask(self, question, k=5):
        on = today()
        # 1. search a bit wider, then drop directions that are already fully replaced
        hits = [c for c in self.retriever.search(question, k=12)
                if not self.currency.is_replaced(c["doc_id"], on)][:k]
        chunks = self.retriever.with_neighbors(hits)
        # 2. tell the LLM whether each source is in force today
        chunks = [{**c, "status": self.currency.status(c["doc_id"], on)} for c in chunks]
        answer, tokens = generate(question, chunks, today=on.isoformat())
        # 3. sources = only the chunks the answer actually cites
        used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 < int(n) <= len(chunks)})
        cited = [chunks[n - 1] for n in used]
        sources = [{"n": n, "doc_id": c["doc_id"], "title": c["title"], "para": c["para"], "page": c["page"],
                    "status": c["status"], "url": f"{c['pdf_url']}#page={c['page']}" if c["pdf_url"] else ""}
                   for n, c in zip(used, cited)]
        found = NOT_FOUND not in answer
        return {
            "answer": answer,
            "sources": sources,
            "warnings": self.currency.warnings(cited, on) if found else [],  # made by code
            "contexts": [f"{c['title']}, para {c['para']}\nStatus: {c['status']}\n{c['text']}"+ "".join(f"\nNote: {n}" for n in c.get("notes", [])) for c in chunks],
            "tokens": tokens,
            "found": found,
            "date": on.isoformat(),
        }


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "What are the qualifications for a CFO?"
    result = Copilot().ask(question)
    print(f"\nAnswer (as on {result['date']}):\n{result['answer']}\n")
    for s in result["sources"]:
        print(f"[{s['n']}] {s['title']} | para {s['para']} | page {s['page']}\n    {s['url']}")
    for w in result["warnings"]:
        print(f"WARNING: {w}")
    print(f"\nTokens used: {result['tokens']}")
