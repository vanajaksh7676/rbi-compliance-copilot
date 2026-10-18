"""Embed every chunk once and save the vectors to data/processed/embeddings.npy.

With EMBED_PROVIDER=openai this takes a minute or two and costs a few rupees.
It works in batches, prints progress, and saves each batch, so if it stops you can
run it again and it continues. Re-run it whenever chunks.json changes.
"""
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np

import providers

CHUNKS = Path("data/processed/chunks.json")
OUT = Path("data/processed/embeddings.npy")
META = Path("data/processed/embeddings_meta.json")
BATCH = 100 if providers.EMBED_PROVIDER == "openai" else 32


def embed_text(c: dict) -> str:
    """What gets embedded: title and section give context; notes carry amendment dates."""
    return "\n".join([c["title"], c.get("section", ""), c["text"], *c.get("notes", [])])[:6000]


def main():
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    texts = [embed_text(c) for c in chunks]
    name = providers.embedding_name()
    parts = Path("data/processed/embedding_parts") / re.sub(r"[^\w.-]", "_", name)
    old = parts / "count.txt"
    if old.exists() and old.read_text() != str(len(texts)):
        shutil.rmtree(parts)  # chunks changed since the last run: start again
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "count.txt").write_text(str(len(texts)))
    print(f"{len(texts)} chunks to embed with {name}", flush=True)

    start, done_now = time.time(), 0
    for b, i in enumerate(range(0, len(texts), BATCH)):
        part = parts / f"{b:05d}.npy"
        if part.exists():
            continue  # finished in an earlier run
        batch = texts[i:i + BATCH]
        np.save(part, np.array(providers.embed_passages(batch), dtype=np.float32))
        done_now += len(batch)
        per_chunk = (time.time() - start) / done_now
        left = len(texts) - min(i + BATCH, len(texts))
        print(f"{min(i + BATCH, len(texts))}/{len(texts)} done, about {left * per_chunk:.0f} s left",
              flush=True)

    vectors = np.concatenate([np.load(p) for p in sorted(parts.glob("*.npy"))])
    if len(vectors) != len(texts):
        raise SystemExit(f"Vector count doesn't match chunk count. Delete {parts} and run again.")
    np.save(OUT, vectors)
    META.write_text(json.dumps({"embedding": name, "count": len(vectors)}, indent=1))
    print("Saved", OUT, vectors.shape)


if __name__ == "__main__":
    main()
