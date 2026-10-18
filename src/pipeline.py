"""Question in -> cited answer out."""
import re
import sys
from generate import NOT_FOUND, generate
from retrieve import Retriever
class Copilot:
    def __init__(self, use_reranker=True):
        self.retriever = Retriever(use_reranker=use_reranker)
    def ask(self, question, k=5):
        chunks = self.retriever.with_neighbors(self.retriever.search(question, k=k))
        answer, tokens = generate(question, chunks)
        used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 
< int(n) <= len(chunks)})
        sources = [{"n": n, "title": chunks[n - 1]["title"], "para": chunks[n - 1]["para"],
                    "page": chunks[n - 1]["page"],
                    "url": f"{chunks[n - 1]['pdf_url']}#page={chunks[n - 1]
['page']}"}
                   for n in used]
        return {"answer": answer, "sources": sources, "warnings": [], 
"replaced_warnings": [],
                "contexts": [c["text"] for c in chunks], "tokens": tokens,
                "found": NOT_FOUND not in answer}
if __name__ == "__main__":
    out = Copilot().ask(sys.argv[1])
    print(out["answer"])
    for s in out["sources"]:
        print(f"[{s['n']}] {s['title']}, para {s['para']}, page {s['page']}\n    {s['url']}")
    print("tokens:", out["tokens"])