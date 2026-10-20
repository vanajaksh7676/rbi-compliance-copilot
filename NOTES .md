# NOTES.md — log of what failed and what I changed

Project: RBI Compliance Copilot (Master Directions for Commercial Banks)

Each entry: **what failed -> cause -> what I changed -> result**.

---

## Where things stand (end of Phase 3)

| Item | Value |
| --- | --- |
| Corpus | 34 RBI Master Directions for Commercial Banks, downloaded by hand into `data/raw/` |
| Parser | v2 `parse.py`: font-aware cleaning before chunking (see Phase 1, part B) |
| Chunks | 5,529 paragraph-level chunks |
| Embeddings | OpenAI `text-embedding-3-small`, 1,536 numbers per chunk |
| Search | BM25 + vectors, merged with RRF, reranked by a cross-encoder that reads title + section + text |
| Answers | OpenAI `gpt-5.6-luna`, strict citation prompt; Groq kept as a free fallback |
| Tests | 6 pytest tests for the cleaning rules: 6 passed |
| Manual Q&A | 4 of 4 test questions correct after two retrieval fixes |

---

## Phase 0–1, part A: setup, download and first parser (v1)

### What failed and what I changed

| # | What failed | Cause | What I changed |
|---|---|---|---|
| 1 | `pip install fitz` failed | The PyPI package named `fitz` is a different, deactivated package | Installed `pymupdf`; the code uses `import pymupdf` (the name `fitz` is deprecated) |
| 2 | Parse gave 34 chunks for 34 directions (1 per direction) | The files in `data/raw` were not PDFs: RBI's bot check returned an HTML verification page, saved with a `.pdf` name | Downloaded the 34 PDFs by hand in the browser. Added a `%PDF-` header check in `build_registry.py` so a fake PDF is skipped. Wrote `make_links.py` to produce `data/download_links.html` with a `[done]/[TODO]` link per direction |
| 3 | Pasted guide code broke (lost indentation, split lines, missing imports, bad regex) | Copy-paste from the PDF | Rewrote the full files |
| 4 | First real parse had table-of-contents chunks, trailing headings, page numbers inside text, wrongly merged labels | Parser was too simple | Skipped the TOC, attached headings to the following paragraph, dropped page-number lines, labelled merged paragraphs as a range (e.g. "1–2") |
| 5 | Footnotes ("1 Inserted w.e.f. …") were read as numbered paragraphs; footnote tail lines leaked into text | The paragraph regex matched a plain number followed by a capital letter | Required the dot ("3. Text"); removed footnote blocks and "Amendment Directions … dated" lines |
| 6 | Guide test expected `group(1) == "12"` but got "12." | Regex captured the trailing dot | Restructured `PARA_START` so group 1 has no dot |
| 7 | Typed `python ssrc/chunk_pdfs.py` | Typo and old file name | Run `python src/parse.py` from the project root |

### v1 results
- First parse with real PDFs: 5,325 chunks from 34 directions.
- After the cleaning fixes: 5,164 chunks from 34 directions.
- Spot check (`python src/spot_check.py`): paragraphs 258, 214, 358, 129, 409 and others matched the PDF
  (text, paragraph number, page). Footnote/TOC leftovers = 0; jumbled-table chunks = 10; very short chunks = 15.
- "Paragraph numbers going backwards" (570 cases) were false alarms: annexes restart numbering at 1.

### Why I replaced v1
- v1 deleted footnotes, but footnotes carry amendment history ("Amended w.e.f. …", "Deleted with effect from …"),
  which the currency check (Phase 4) needs.
- v1 worked on plain text, so it could not tell footnote markers or footers from body text reliably.

---

## Phase 1, part B: parser v2 (clean before chunking, font-aware)

### Decision: clean the whole document before chunking
- Order: **extract -> clean whole document -> chunk**. Cleaning chunk by chunk would miss noise that crosses
  paragraph or page boundaries (a footer in the middle of a paragraph, a word split across pages).
- Page numbers are kept as hidden markers during cleaning so every chunk keeps its page for citations.
- Built and tested on 3 sample PDFs first (146MD, 148MD, 149MD: short, medium, long with tables),
  then ran on all 34.

### What failed in the sample PDFs and what I changed

| # | What failed | Cause | What I changed | Result on the 3 samples |
|---|---|---|---|---|
| 1 | Most paragraphs not detected | Paragraph number sits on its own line ("4." then text on the next line) | Detect both layouts; accept only numbers that continue the sequence (gap up to 5 for deleted paragraphs) | Paragraphs 1–19, 1–85, 1–76 found with no gaps |
| 2 | Footnote markers glued to words ("1These Directions", "2Paragraph 18(4)") | Superscript markers merge into the next word in plain text | Read font sizes: small digit-only pieces inside body text are removed and recorded as footnote references | No glued markers left |
| 3 | Footnotes needed, not deleted | They hold amendment dates | Collect footnote text per page and attach it to the paragraph that references it (`notes` field); unreferenced footnotes go to the paragraph on the same page | 32/32 footnotes attached in 148MD, 7/7 in 149MD |
| 4 | Font sizes differ between PDFs | Footnotes 9 pt in one file, 10 pt in another | Relative rules: body = most common size; footnotes = smaller and in the lower half of the page; page numbers = digits only at the top/bottom edge | Works on all 3 |
| 5 | Hyphens at line ends | All are real words ("sub-section", "co-operative", "Non-Banking") | Join lines and keep the hyphen; keep suspended hyphens ("pre- and post-") | Covered by a test |
| 6 | Letterhead, reference numbers, TOC, signature block, Hindi header | Page-1 and end-of-document noise | Removed, including refs inside the page-1 letterhead table; circular references inside rules are kept | None left in chunks |
| 7 | Tables became jumbled lines | Plain text reads cells line by line | Detect tables; each row becomes "cell \| cell"; repeated merged cells dropped | CFO table readable |
| 8 | Inserted paragraphs missed (16A, 38A–38I, 19A, 19B) | Regex only accepted plain numbers | Accept number + optional capital letter right after the same number | 15 inserted paragraphs found |
| 9 | Standard paragraphs vanished in most directions | My duplicate filter compared text across all PDFs ("come into force with immediate effect" is in every direction) | Remove duplicates only within one direction; keep "[Deleted]" / "[*****]" paragraphs | No gaps |
| 10 | Words glued where the PDF leaves a gap ("banksare") | No space character, only a gap | Insert a space when the gap between text pieces is large enough | Fixed in samples |
| 11 | Chapter and section headings glued; "B.4 …" / "D.1 …" headings missed | Heading rules too narrow | Each heading line starts a new heading; heading regex accepts "B.4", "D.1", "[B1." | Correct section paths |
| 12 | Split parts of long paragraphs all showed the first page | Page taken from the paragraph start | Each part finds its own page | Citation links open the right page |

### Chunk design (v2)
- One chunk = one top-level paragraph, with direction title, paragraph number, chapter > section, page,
  footnote notes and PDF link. Long paragraphs (> 1,800 characters) are split at sub-items, keeping the
  paragraph number. No more merged "1–2" labels: every paragraph has its own chunk.

### v2 result on all 34 PDFs
- 5,529 chunks (v1 had 5,164). More chunks is expected: inserted paragraphs (16A …), deleted-paragraph
  placeholders, and paragraphs that v1 had merged are now separate chunks.

### Status of v1's known issues under v2

| v1 issue | Status in v2 |
|---|---|
| Hindi header garbled | Fixed: Devanagari letterhead lines removed |
| `D.1 Single Counterparty` headings not recognised | Fixed by the heading rule; **re-check `158MD-0019` and `151MD-0449`** |
| TOC / footnote leftovers | Fixed |
| Missing spaces ("itrequires", "goodtimes") | Partly fixed by the gap rule; **re-check these examples** |
| About 10 jumbled-table chunks (151MD, 154MD, 163MD) | Tables now extracted as rows; **re-check these files** |
| Repeated page header ("Provisioning and Income Recognition) Directions, 2026") | **Not fixed**: v2 does not remove running headers yet |
| `174MD` is a list of companies, not rules (~100 junk chunks) | **Check**: if `174MD.pdf` is still in `data/raw/`, move it out, re-run `parse.py` and `index.py` |

### Tests
- v2 `tests/test_parse.py` (6 tests): paragraph numbers on their own line or with text; "1949." is not a
  paragraph; "19A." is; sub-items (1), (1A), (a), (iv); hyphens kept; quotes straightened, not removed;
  long paragraphs split at sub-items.
- `pytest -v`: **6 passed**.
- To do: v1 had tests for `D.1` headings and footnotes that the v2 test file replaced. Add them back.

---

## Phase 2: search (embeddings, BM25 + vectors, RRF, rerank)

### What failed and what I changed

| # | What failed | Cause | What I changed |
|---|---|---|---|
| 1 | `python src/retrieve.py` printed nothing | My copy was missing the `if __name__ == "__main__":` block | Added the block; the question goes in quotes after the command |
| 2 | `FileNotFoundError: data/processed/embeddings.npy` | `index.py` had not been run | Run `python src/index.py` first |
| 3 | `index.py` ran 30–60 minutes with no output | About 5,500 chunks embedded with fastembed on a laptop i3 CPU, no progress shown | Rewrote `index.py`: batches, progress, resume after interruption. Then switched to OpenAI embeddings: 5,529 chunks in a few minutes for a few rupees |
| 4 | Risk of old vectors used with new chunks | Embeddings must be rebuilt whenever `chunks.json` changes | `index.py` saves `embeddings_meta.json` (model + count); `retrieve.py` stops with a clear message if they don't match |

### Decision: make the AI provider swappable (`providers.py`)
- `.env` chooses the service: `EMBED_PROVIDER=openai|fastembed`, `LLM_PROVIDER=openai|groq`.
- Reason: Groq's free tier dropped Llama 3.3 70B and allows about 8,000 tokens/minute and 200,000 tokens/day
  per model; OpenAI is cheap at this scale. Groq stays as a free fallback.

### How search works
1. BM25 keyword search over title + section + text -> top 20.
2. Vector search (OpenAI embeddings in Chroma; embedding text = title + section + text + notes) -> top 20.
3. Reciprocal rank fusion merges the lists.
4. Local cross-encoder reranker (ms-marco-MiniLM-L-6-v2, ~87 MB, downloaded once) reorders the shortlist.
5. Top 5 returned.

- `embeddings.npy` shape (5529, 1536), about 34 MB.
- The huggingface "symlinks" warning on Windows is harmless (`HF_HUB_DISABLE_SYMLINKS_WARNING=1` hides it).

### First search test
"What qualifications must a CFO of a public sector bank have?" -> rank 1: Governance Directions para 36
(exact answer); rank 2: para 60 (same rules for private banks); ranks 3–5 loosely related (paras 23, 52, 30).

### Retrieval experiment (10 questions) — to fill in
Right paragraph in the top 5:

| Mode | Hits out of 10 |
|---|---|
| BM25 only | _ |
| Vectors only | _ |
| Hybrid (BM25 + vectors, RRF) | _ |
| Hybrid + reranker | _ |

Target: at least 8 of 10 for hybrid + reranker. Questions that missed, and why: _(fill in)_

---

## Phase 3: cited answers

### How it works
- `generate.py` numbers the retrieved paragraphs [1]…[n] and instructs the model: use only these sources,
  cite every sentence, copy numbers exactly, mention amendments, and reply
  "I could not find this in the RBI directions I have." when the answer isn't there.
- `pipeline.py` runs search -> answer and turns [n] into source lines with paragraph, page and a PDF link (`#page=N`).

### What failed and what I changed

| # | What failed | Cause | What I changed | Result |
|---|---|---|---|---|
| 1 | "When did the Undertaking of Financial Services directions come into force?" was refused | Almost every direction has a near-identical para 2 ("come into force …"); the reranker read only paragraph text, so they all looked the same and other directions' para 2 ranked higher | Reranker now reads **title + section + text** | Para 2 of the right direction ranked 1st; 4 of top 5 from the right direction (before: none) |
| 2 | Short rule paragraphs lose to longer look-alikes | The paragraph before (with the direction's name) is found, the short one isn't | **Neighbour expansion**: add the next paragraph from the same direction for each hit (max 10) | Correct answer; the private-bank answer now combines para 60 + para 36 |
| 3 | Source lines cut off ("Directions, 2025 (Updated ,") | Title printed with `[:80]` | Print the full title | Cosmetic fix |

Cost of the fixes: about 2x tokens per answer (about 1,900–2,600 tokens), still a fraction of a rupee.

### Manual test results (after the fixes)

| Question | Expected | Result | Tokens |
|---|---|---|---|
| What qualifications must a CFO of a public sector bank have? | Para 36 | Correct, para 36, page 17 | 2,601 |
| Do the CFO qualification rules also apply to private sector banks? | Para 60 | Correct, para 60 + para 36 | 2,356 |
| What is today's repo rate? | Refuse | Correctly refused | 2,480 |
| When did the Undertaking of Financial Services directions come into force? | Para 2, 148MD | Correct, "with immediate effect", para 2, page 3 | 1,865 |

---

## Open issues (to do)

- [ ] `174MD` (list of companies): confirm it's removed from `data/raw/`; if not, remove, re-parse, re-index.
- [ ] Re-check v1 problem chunks under v2: `158MD-0019`, `151MD-0449`, tables in 151MD/154MD/163MD, missing spaces.
- [ ] Remove repeated running page headers (e.g. "Provisioning and Income Recognition) Directions, 2026").
- [ ] Add back tests for `D.1` headings and footnote handling.
- [ ] The "came into force" answer didn't mention the footnote "Modified w.e.f. January 01, 2026". Phase 4 will
      show notes as warnings from code.
- [ ] Fill in the 10-question retrieval experiment (Phase 2).
- [ ] Phase 4: currency check (replaced directions). Phase 5: evaluation set + RAGAS.

---

## Future scope: automatic update of RBI directions
- Current version: a curated registry. New or updated directions are downloaded by hand, then re-parsed,
  re-indexed and tested through the pipeline.
- RBI's bot check blocks scripted PDF downloads, so fully automatic download is not realistic.
- Possible next step: a scheduled `check_updates.py` (e.g. a GitHub Actions cron job) that reads the RBI listing
  page, compares each direction's "updated as on" date with `registry.csv` and reports which directions changed.
  I then download the changed PDFs and re-run parse, index and tests.
- Do not claim the system updates itself automatically.

---

## Interview talking points
1. Why clean before chunking (boundary noise; page markers for citations).
2. Why footnotes are kept, not deleted (amendment history for the currency check).
3. The fake-PDF problem (RBI bot check) and the `%PDF-` header check.
4. Why hybrid search (embeddings understand meaning; BM25 catches exact terms like "CFO").
5. A real failure and fix: identical boilerplate paragraphs confused the reranker -> rerank on title + section +
   text, then neighbour expansion.
6. Why the provider is swappable (free-tier limits, cost, no lock-in).

---

## Reminders
- Never commit `.env`. Check that `data/raw/` and `.env` are in `.gitignore`.
- Re-run `python src/index.py` every time `chunks.json` changes.
- Commit `embeddings.npy` (about 34 MB, under GitHub's 100 MB limit) once the index is final.
- OpenAI usage costs money: keep a monthly spending limit set in the OpenAI dashboard.
- Groq (fallback): about 8,000 tokens/minute and 200,000/day; use `gpt-oss-20b` while building if switching back.

## phase 4
Phase 4 done. Parser v3: fixed glued footnote markers (153MD “3502” became 350, roman v/vi markers), the table of contents without dot leaders and the repeated page header (397MD), “13.The” with no space (170MD), 219ZA-style numbers (154MD), signature lines and letterhead. Added currency.py and data/currency.csv: warnings for “not yet in force”, “being replaced”, “amended” and “expired temporary rule”, all made by code. Each source sent to the LLM has a Status line. 13 tests pass. Re-downloaded all PDFs after losing data/raw; removed the duplicate 165MD and 174MD; 156MD added; 5,801 chunks before cleanup. Test results: FCNR(B) answer gives 350 bps plus an expiry warning; ECL answer says it applies from 1 April 2027. Open issue: 158MD para 114 missing.