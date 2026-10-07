

"""Split the downloaded RBI PDFs into paragraph-sized chunks and save them to
data/processed/chunksand.json."""
import csv
import json
import re
from pathlib import Path
 
import pymupdf  # PyMuPDF
 
# A line that starts a numbered paragraph: "3.", "3.1", "12.4.2" followed by
# text that begins with a capital letter, "(", or a quote. A plain number needs
# its dot ("3. Text"), so footnote lines like "1 Inserted w.e.f. ..." do NOT
# count as paragraphs.
PARA_START = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){1,3}|\d{1,3}(?=\.\s))\.?\s+(?=[A-Z(\"'‘“])"
)
# Footnote blocks at the bottom of a page: "1 Inserted w.e.f. October 1, 2026..."
FOOTNOTE = re.compile(
    r"^\s*\d{1,2}\s*(Inserted|Substituted|Amended|Deleted|Added|Omitted|"
    r"Renumbered|Modified|Revised|Replaced)\b", re.IGNORECASE)
# Wrapped second line of a footnote: "...Amendment Directions, 2026 dated October 1, 2026"
FOOTNOTE_TAIL = re.compile(
    r"\bAmendment\s+(?:Directions|Direction|Guidelines)\b.{0,40}\bdated\b",
    re.IGNORECASE)
# Table-of-contents lines ("Chapter I- Preliminary ........ 2")
LEADER = re.compile(r"(\.{4,}|…{2,})")
TOC_START = re.compile(r"^(table of )?contents$", re.IGNORECASE)
TOC_END = re.compile(
    r"^(Introduction|Preface|Chapter\s+[IVXL]+\b|Annex(?:ure)?\b)|^\d{1,3}\.\s")
TOC_MAX_PAGES = 3  # safety: never skip more than this many pages
# A line that is only a page number ("3") or a lone letter label ("C.")
PAGE_NUM = re.compile(r"^\d{1,3}$")
LONE_LABEL = re.compile(r"^[A-Z]\.$")
# Section headings: "A. Short Title", "Chapter II- Prior Approval", "Annex I"
HEADING = re.compile(
    r"^(?:[A-Z]\.\s+[A-Z]|Chapter\s+[IVXL]+\s*[-–—]|Annex(?:ure)?\s+[IVXL\d]+)"
)
MAX_CHARS, MIN_CHARS = 1500, 200
 
 
def read_pages(pdf_path):
    """Read each page as text blocks, dropping footnote blocks."""
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for n, page in enumerate(doc, start=1):
            texts = []
            for block in page.get_text("blocks"):
                if block[6] != 0:  # skip image blocks
                    continue
                if FOOTNOTE.match(block[4]):
                    continue
                texts.append(block[4])
            pages.append((n, "\n".join(texts)))
    return pages
 
 
def parse_pages(pages):
    """pages: list of (page_no, text). Returns paragraphs with their number.
    Headings are attached to the paragraph that FOLLOWS them."""
    paras = []
    current = {"para": "intro", "page": 1, "lines": [], "heading_only": False}
    in_toc, toc_page = False, 0
 
    def flush():
        if current["lines"]:
            paras.append({"para": current["para"] or "unnumbered",
                          "page": current["page"],
                          "lines": list(current["lines"])})
 
    for page_no, text in pages:
        if in_toc and page_no > toc_page + TOC_MAX_PAGES:
            in_toc = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
 
            # skip the table of contents until the real text starts
            if in_toc:
                if LEADER.search(line) or not TOC_END.match(line):
                    continue
                in_toc = False
            elif TOC_START.match(line):
                in_toc, toc_page = True, page_no
                continue
 
            if (LEADER.search(line) or PAGE_NUM.match(line)
                    or LONE_LABEL.match(line)
                    or (len(line) < 250 and FOOTNOTE_TAIL.search(line))):
                continue
 
            is_start = PARA_START.match(line)
            is_heading = (not is_start and len(line) <= 120
                          and HEADING.match(line))
 
            if is_heading:
                if not current["heading_only"]:
                    flush()
                    current = {"para": None, "page": page_no, "lines": [],
                               "heading_only": True}
                current["lines"].append(line)
            elif is_start:
                num = is_start.group(1).rstrip(".")
                if current["heading_only"]:
                    current["para"] = num
                    current["heading_only"] = False
                else:
                    flush()
                    current = {"para": num, "page": page_no,
                               "lines": [], "heading_only": False}
                current["lines"].append(line)
            else:
                current["heading_only"] = False
                current["lines"].append(line)
    flush()
    return [{"para": p["para"], "page": p["page"],
             "text": " ".join(p["lines"])} for p in paras]
 
 
def split_paragraphs(pdf_path):
    return parse_pages(read_pages(pdf_path))
 
 
def merge_label(a, b):
    """Label for two joined paragraphs, e.g. '1' + '2' -> '1–2'."""
    if a in ("intro", "unnumbered"):
        return b
    if b in ("intro", "unnumbered"):
        return a
    start, end = a.split("–")[0], b.split("–")[-1]
    return start if start == end else f"{start}–{end}"
 
 
def size_chunks(paras):
    """Join tiny paragraphs (often headings) onto the next one; split very
    long ones."""
    out, carry = [], None
    for p in paras:
        if carry:
            p = {"para": merge_label(carry["para"], p["para"]),
                 "page": carry["page"],
                 "text": carry["text"] + " " + p["text"]}
            carry = None
        if len(p["text"]) < MIN_CHARS:
            carry = p
            continue
        text = p["text"]
        while len(text) > MAX_CHARS:
            # cut at a sentence end
            cut = text.rfind(". ", 0, MAX_CHARS) + 1
            if cut < MIN_CHARS:
                cut = MAX_CHARS
            out.append({**p, "text": text[:cut].strip()})
            text = text[cut:]
        out.append({**p, "text": text.strip()})
    if carry:
        out.append(carry)
    return out
 
 
def main():
    with open("data/registry.csv", encoding="utf-8") as f:
        registry = {r["doc_id"]: r for r in csv.DictReader(f)}
 
    chunks = []
    for pdf in sorted(Path("data/raw").glob("*.pdf")):
        meta = registry.get(pdf.stem)
        if not meta:
            continue
        for i, p in enumerate(size_chunks(split_paragraphs(pdf))):
            chunks.append({
                "chunk_id": f"{pdf.stem}-{i:04d}",
                "doc_id": pdf.stem,
                "title": meta["title"],
                "para": p["para"],
                "page": p["page"],
                "text": p["text"],
                "pdf_url": meta["pdf_url"],
                "updated_as_on": meta["updated_as_on"],
            })
 
    out = Path("data/processed/chunks.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(chunks, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(len(chunks), "chunks from", len({c["doc_id"] for c in chunks}),
          "directions")
 
 
if __name__ == "__main__":
    main()
 
