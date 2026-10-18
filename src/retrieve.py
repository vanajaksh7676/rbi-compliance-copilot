"""Hybrid search: BM25 keywords + vectors, merged with reciprocal rank fusion, then reranked."""
import json
import os
import re
import sys
from pathlib import Path

import chromadb
import numpy as np
from rank_bm25 import BM25Okapi

import providers

RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"  # about 80 MB, runs on your CPU
USE_RERANKER = os.getenv("USE_RERANKER", "1") == "1"


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def rrf(rankings, k=60):
    """Reciprocal rank fusion: a chunk near the top of any list gets a high score."""
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


class Retriever:
    def __init__(self, use_reranker=USE_RERANKER):
        self.chunks = json.loads(Path("data/processed/chunks.json").read_text(encoding="utf-8"))
        meta = json.loads(Path("data/processed/embeddings_meta.json").read_text())
        if meta["embedding"] != providers.embedding_name() or meta["count"] != len(self.chunks):
            raise SystemExit(f"embeddings.npy was made with {meta['embedding']} for {meta['count']} "
                             f"chunks. Run python src/index.py again.")
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        self.ids = [c["chunk_id"] for c in self.chunks]
        self.position = {c["chunk_id"]: i for i, c in enumerate(self.chunks)}
        self.bm25 = BM25Okapi([tokenize(f"{c['title']} {c['section']} {c['text']}") for c in self.chunks])
        vectors = np.load("data/processed/embeddings.npy")
        self.collection = chromadb.EphemeralClient().get_or_create_collection(
            "rbi", metadata={"hnsw:space": "cosine"})
        for i in range(0, len(self.ids), 1000):  # add in batches
            self.collection.add(ids=self.ids[i:i + 1000], embeddings=vectors[i:i + 1000].tolist())
        self.reranker = None
        if use_reranker:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self.reranker = TextCrossEncoder(RERANK_MODEL)

    def search(self, question, k=5, pool=20):
        keyword_scores = self.bm25.get_scores(tokenize(question))
        by_keyword = [self.ids[i] for i in np.argsort(keyword_scores)[::-1][:pool]]
        by_meaning = self.collection.query(query_embeddings=[providers.embed_query(question)],
                                           n_results=pool)["ids"][0]
        candidates = [self.by_id[cid] for cid in rrf([by_keyword, by_meaning])[:pool]]
        if self.reranker:
            scores = list(self.reranker.rerank(
                question,[f"{c['title']}\n{c['section']}\n{c['text']}" for c in candidates])) 
            ranked = sorted(zip(scores, candidates), key=lambda pair: pair[0], reverse=True)
            candidates = [c for _, c in ranked]
        return candidates[:k]
    
    def next_chunk(self, c):
        """The paragraph right after this one in the same direction, if any."""
        i = self.position[c["chunk_id"]] + 1
        if i < len(self.chunks) and self.chunks[i]["doc_id"] == c["doc_id"]:
            return self.chunks[i]
        return None

    def with_neighbors(self, hits, limit=10):
        """The hits, plus the next paragraph after each one (e.g. para 2 after para 1)."""
        out = list(hits)
        seen = {c["chunk_id"] for c in hits}
        for c in hits:
            nxt = self.next_chunk(c)
            if nxt and nxt["chunk_id"] not in seen:
                seen.add(nxt["chunk_id"])
                out.append(nxt)
        return out[:limit]


if __name__ == "__main__":
    retriever = Retriever()
    for c in retriever.search(sys.argv[1]):
        print(f"\n{c['title'][:80]} | para {c['para']} | page {c['page']}\n  {c['section']}\n"
              f"  {c['text'][:250]}")
