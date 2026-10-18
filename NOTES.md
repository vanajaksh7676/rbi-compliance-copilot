# NOTES.md — log of what failed and what I changed

Project: RBI Compliance Copilot (Master Directions for Commercial Banks)

---

## Phase 0–1: registry, download, parse, chunk

### What failed and what I changed

| # | What failed | Cause | What I changed |
|---|---|---|---|
| 1 | `pip install fitz` failed | The PyPI package named `fitz` is a different, deactivated package | Installed `pymupdf` instead and used `import pymupdf` in the code (the name `fitz` is deprecated) |
| 2 | Parse gave 34 chunks for 34 directions (1 per direction) | The files in `data/raw` were not PDFs. RBI's bot check sent an HTML verification page, saved with a `.pdf` name | Downloaded the 34 PDFs by hand in the browser. Added a `%PDF-` header check in `build_registry.py` so a fake PDF is skipped. Wrote `make_links.py` to produce `data/download_links.html` with a `[done]/[TODO]` link per direction |
| 3 | Pasted guide code broke (lost indentation, split lines, missing imports, bad regex) | Copy-paste from the PDF | Rewrote the full files |
| 4 | First real parse had table-of-contents chunks, trailing headings, page numbers inside text, wrong merged labels | Parser was too simple | Skip the TOC; attach each heading to the paragraph that follows it; drop page-number lines; label merged paragraphs as a range (e.g. "1–2") |
| 5 | Footnotes ("1 Inserted w.e.f. …") were read as numbered paragraphs, and footnote tail lines leaked into text | The paragraph regex matched a plain number followed by a capital letter | A plain number now needs its dot ("3. Text"). Footnote blocks and "Amendment Directions … dated" lines are removed |
| 6 | Guide test expected `group(1) == "12"` but the regex returned "12." | Regex captured the trailing dot | Restructured `PARA_START` so group 1 has no dot |
| 7 | Typed `python ssrc/chunk_pdfs.py` | Typo and old file name | Run `python src/parse.py` from the project root |

### Chunk counts
- First parse with real PDFs: 5,325 chunks from 34 directions
- After the cleaning fixes: 5,164 chunks from 34 directions

### Spot check (`python src/spot_check.py`)
- Chunks looked correct for paragraphs 258, 214, 358, 129, 409 and others (text, paragraph number and page matched).
- Automatic checks: footnote/TOC leftovers = 0; jumbled-table chunks = 10; very short chunks = 15.
- "Paragraph numbers going backwards" (570) are false alarms: annexes restart numbering at 1.

### Known issues found
- [ ] **`174MD` is not a rulebook.** It is a list of company names and addresses and creates about 100 junk chunks. Fix: move `data/raw/174MD.pdf` out and re-run `parse.py`. Excluded: list of companies, not regulatory text.
- [ ] **Headings like `D.1 Single Counterparty` were not recognised**, so some chunks got the label "unnumbered" (e.g. `158MD-0019`) and a heading stuck to the end of the previous paragraph (e.g. `151MD-0449`). Fix: `HEADING` regex now also matches `D.1` / `E.2` style headings. Added a test for it.
- [ ] **Missing spaces in the text** ("itrequires", "goodtimes"). The PDFs themselves lose spaces at some line wraps. Not fixed. May hurt BM25 a little.
- [ ] **About 10 chunks look like jumbled tables** (e.g. in 151MD, 154MD, 163MD). Not fixed. Check whether retrieval fails on table questions before fixing.
- [ ] **Repeated page header** ("Provisioning and Income Recognition) Directions, 2026") appears in many chunks of one direction. Not removed.
- Hindi header text in the first chunk of some files is garbled. Ignored.

### Tests
- `tests/conftest.py` and `tests/test_parse.py` created (paragraph numbers, heading joins, footnotes, TOC, merged labels, `D.1` headings).
- `pytest` result: _(fill in: N passed)_

---

## Phase 2: search (BM25 + vectors + RRF + rerank)

### What failed and what I changed

| # | What failed | Cause | What I changed |
|---|---|---|---|
| 1 | `python src/retrieve.py` printed nothing | My copy of the file was missing the `if __name__ == "__main__":` block at the bottom | Added the block. The question goes in quotes after the command |
| 2 | `FileNotFoundError: data/processed/embeddings.npy` | `index.py` had not been run yet | Run `python src/index.py` first |
| 3 | `index.py` took a very long time with no output | About 5,000 chunks embedded on a laptop CPU, no progress shown | Rewrote `index.py` with progress, saved progress (resume after interruption) and all CPU cores. Remove junk (`174MD`) before indexing |

- The huggingface "symlinks" warning on Windows is harmless.
- Embeddings must be rebuilt (`python src/index.py`) every time `chunks.json` changes. `retrieve.py` should be made to stop with a clear message if the vector count does not match the chunk count.

### Retrieval experiment (10 questions) — fill in
Right paragraph in the top 5:

| Mode | Hits out of 10 |
|---|---|
| BM25 only | _ |
| Vectors only | _ |
| Hybrid (BM25 + vectors, RRF) | _ |
| Hybrid + reranker | _ |

Target from the guide: at least 8 of 10 for hybrid + reranker.

Questions that missed, and why: _(fill in)_

---

## Future scope: automatic update of RBI directions
- Current version: a curated registry. New or updated directions are downloaded by hand, then re-parsed, re-indexed and tested through the pipeline.
- RBI's bot check blocks scripted PDF downloads, so fully automatic download is not realistic.
- Possible next step: a scheduled `check_updates.py` (for example a GitHub Actions cron job) that reads the RBI listing page, compares each direction's "updated as on" date with `registry.csv` and reports which directions changed. I then download the changed PDFs and re-run parse, index and tests.
- Do not claim the system updates itself automatically.

---

## Reminders
- Never commit `.env`. Check that `data/raw/` and `.env` are in `.gitignore`.
- Groq free tier: about 8,000 tokens per minute and 200,000 per day. Use `gpt-oss-20b` while building.
- Commit `embeddings.npy` with the code once the index is final.


c:\vanajakshi\rbi-compliance-copilot\venv\Scrippython -c "import numpy as np; v = np.load('data/processed/embeddings.npy'); print(v.shape); print(v[0][:5])"t> 
(5529, 1536)
[ 0.01225281  0.00940704  0.06738281  0.02148438 -0.01531219]
(venv) PS C:\vanajakshi\rbi-compliance-copilot> python src/retrieve.py "What qualifications must a CFO of a public sector bank have?"
Downloading bytes:                 |  0.00B            C:\vanajakshi\rbi-compliance-copilot\venv\Lib\site-packages\huggingface_hub\file_download.py:149: UserWarning: `huggingface_hub` cache-system uses symlinks by default to efficiently store duplicated files but your machine does not support them in C:\Users\Usha\AppData\Local\Temp\fastembed_cache. Caching files will still work but in a degraded version that might require more space on your disk. This warning can be disabled by setting the `HF_HUB_DISABLE_SYMLINKS_WARNING` environment variable. For more details, see https://huggingface.co/docs/huggingface_hub/how-to-cache#limitations.
To support symlinks on Windows, you either need to activate Developer Mode or to run Python as an administrator. In order to activate developer mode, see this article: https://docs.microsoft.com/en-us/windows/apps/get-started/enable-your-device-for-development
  warnings.warn(message)
Downloading bytes:                 | 1.24kB            C:\vanajakshi\rbi-compliance-copilot\venv\Lib\site-packages\huggingface_hub\file_download.py:149: UserWarning: `huggingface_hub` cache-system uses symlinks by default to efficiently store duplicated files but your machine does not support them in C:\Users\Usha\AppData\Local\Temp\fastembed_cache\models--Xenova--ms-marco-MiniLM-L-6-v2. Caching files will still work but in a degraded version that might require more space on your disk. This warning can be disabled by setting the `HF_HUB_DISABLE_SYMLINKS_WARNING` environment variable. For more details, see https://huggingface.co/docs/huggingface_hub/how-to-cache#limitations.
To support symlinks on Windows, you either need to activate Developer Mode or to run Python as an administrator. In order to activate developer mode, see this article: https://docs.microsoft.com/en-us/windows/apps/get-started/enable-your-device-for-development
  warnings.warn(message)
Fetching 5 files: 100%|██| 5/5 [00:12<00:00,  2.57s/it]
Download complete: ████████████████| 86.8MB, 9.01MB/s  
Reserve Bank of India (Commercial Banks - Governance) Directions, 2025 (Updated  | para 36 | page 17
  Chapter-II Public Sector Banks > G. Appointment of Chief Financial Officer and Chief Technical Officer
  As a PSB's Chief Financial Officer (CFO) or Chief Technology Officer (CTO) in its management structure plays a crucial role in strengthening and sustaining the risk governance framework, the PSB shall stipulate, at a minimum, the following qualificat

Reserve Bank of India (Commercial Banks - Governance) Directions, 2025 (Updated  | para 60 | page 30
  Chapter-III Private Sector Banks > G. Appointment of Chief Financial Officer and Chief Technical Officer
  The provisions relating to the minimum qualifications and experience of a CFO and CTO applicable to a PSB, as set out in paragraph 36 of these Directions, shall, mutatis mutandis, apply to a PVB.

Reserve Bank of India (Commercial Banks - Governance) Directions, 2025 (Updated  | para 23 | page 11
  Chapter-II Public Sector Banks > D. Fit and Proper' Criteria for Elected Directors
  A Public Sector Bank (PSB) shall obtain necessary information, and a declaration and undertaking, in the format enclosed at Annex I, from persons who file their nominations for election to the post of Director under sub-section (c) of Section 19 of t

Reserve Bank of India (Commercial Banks - Governance) Directions, 2025 (Updated  | para 52 | page 25
  Chapter-III Private Sector Banks > C. Role of the Board and Individual Directors
  [The responsibilities of the Board of Directors of a Public Sector Bank (PSB) set out in paragraphs 8 to 11A of these Directions shall, mutatis mutandis, apply to the Board of a PVB.]

Reserve Bank of India (Commercial Banks - Governance) Directions, 2025 (Updated  | para 30 | page 16
  Chapter-II Public Sector Banks > E. Appointment of Chief Risk Officer
  The CRO shall be a senior official in the hierarchy of a PSB and shall possess the necessary and adequate professional qualification / experience in the area of risk management.
Download complete: ████████████████| 86.8MB, 9.01MB/s  
Reconstruction complete: 100%|█| 91.7MB / 91.7MB, 8.45M