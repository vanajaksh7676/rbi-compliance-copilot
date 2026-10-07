

"""Print 10 random chunks to compare with the PDFs, plus a few automatic checks.
 
Run from the project root:  python src/spot_check.py
Change SEED (or pass a number) to get a different set of 10:  python src/spot_check.py 7
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
 
CHUNKS = Path("data/processed/chunks.json")
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1
 
 
def para_key(label):
    """'4' -> 4, '3.1' -> 3.1, '8–9' -> 8, 'intro' -> None"""
    m = re.match(r"\d+(?:\.\d+)?", label)
    return float(m.group()) if m else None
 
 
def main():
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    print(f"{len(chunks)} chunks from {len({c['doc_id'] for c in chunks})} directions\n")
 
    # ---- 10 random chunks to check by eye against the PDF ----
    print("=" * 70, "\n10 RANDOM CHUNKS - open the PDF at that page and compare\n", "=" * 70, sep="")
    for c in random.Random(SEED).sample(chunks, 10):
        print(f"\n[{c['chunk_id']}]  paragraph {c['para']}  |  page {c['page']}")
        print(f"PDF: data/raw/{c['doc_id']}.pdf")
        print(c["text"][:600] + (" ..." if len(c["text"]) > 600 else ""))
 
    # ---- automatic checks ----
    print("\n" + "=" * 70, "\nAUTOMATIC CHECKS\n", "=" * 70, sep="")
 
    by_doc = defaultdict(list)
    for c in chunks:
        by_doc[c["doc_id"]].append(c)
 
    # 1. paragraph numbers that go backwards inside one direction
    backwards = []
    for doc, items in by_doc.items():
        last = 0
        for c in items:
            k = para_key(c["para"])
            if k is None:
                continue
            if k < last - 0.5:
                backwards.append(f"{c['chunk_id']} (para {c['para']} after {last:g})")
            last = max(last, k)
    print(f"\n1. Paragraph numbers that go backwards: {len(backwards)}")
    for line in backwards[:10]:
        print("   ", line)
 
    # 2. leftovers from footnotes / table of contents / dotted lines
    leftovers = [c["chunk_id"] for c in chunks
                 if re.search(r"Inserted w\.e\.f|Amendment Directions, 20\d\d dated|\.{5,}|Table of Contents",
                              c["text"])]
    print(f"\n2. Chunks with footnote or table-of-contents leftovers: {len(leftovers)}")
    print("   ", leftovers[:10])
 
    # 3. chunks that look like jumbled tables (mostly numbers / very short words)
    jumbled = []
    for c in chunks:
        words = c["text"].split()
        if len(words) >= 20:
            numeric = sum(1 for w in words if re.fullmatch(r"[\d.,%()\-–/]+", w))
            if numeric / len(words) > 0.35:
                jumbled.append(c["chunk_id"])
    print(f"\n3. Chunks that look like jumbled tables (over 35% numbers): {len(jumbled)}")
    print("   ", jumbled[:10])
 
    # 4. very short chunks
    short = [c["chunk_id"] for c in chunks if len(c["text"]) < 120]
    print(f"\n4. Very short chunks (under 120 characters): {len(short)}")
    print("   ", short[:10])
 
    # 5. text repeated in many chunks of one direction (page headers / footers)
    print("\n5. Phrases repeated in many chunks of one direction (possible page headers):")
    found = False
    for doc, items in by_doc.items():
        if len(items) < 10:
            continue
        counter = Counter()
        for c in items:
            words = c["text"].split()
            seen = {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}
            counter.update(seen)
        for phrase, n in counter.most_common(3):
            if n >= max(8, len(items) // 4) and re.search(r"[A-Z]{2,}|\d", phrase):
                found = True
                print(f"    {doc}: '{phrase}' appears in {n} chunks")
    if not found:
        print("    none found")
 
 
if __name__ == "__main__":
    main()
 
