"""Turn RBI direction PDFs into clean, paragraph-level chunks.

Order of work for each PDF:
  1. EXTRACT  every line with its font size, boldness, position and page number.
  2. CLEAN    the whole document before splitting it:
              - drop page numbers, letterhead, reference numbers, table of contents,
                and the signature block at the end
              - remove footnote markers glued to words ("1These" -> "These"), and keep
                the footnote text (often "Amended w.e.f. ...") as a note
              - turn tables into readable rows
              - join wrapped lines, keeping real hyphens ("sub-" + "section")
              - tidy quotes and spaces
  3. CHUNK    by top-level paragraph number ("1.", "2.", ...), with the chapter and
              section headings as context. Very long paragraphs are split at their
              sub-items, so every chunk keeps its paragraph number for citations.

Run:  python src/parse.py            -> writes data/processed/chunks.json
      python src/parse.py --show 5   -> also prints 5 random chunks to check
"""
import argparse
import csv
import json
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

try:
    import pymupdf  # PyMuPDF 1.24+
except ImportError:  # older PyMuPDF versions
    import fitz as pymupdf

RAW = Path("data/raw")
REGISTRY = Path("data/registry.csv")
OUT = Path("data/processed/chunks.json")
MAX_CHARS = 1800  # longer paragraphs are split at their sub-items

# ---------- patterns ----------
DOT_LEADER = re.compile(r"\.{5,}")                       # "Applicability ........ 3"
PARA_START = re.compile(r"^\[?(\d{1,3})([A-Z]?)\.(?:\s+|$)")  # "4.", "4. In these", "19A." (inserted)
ITEM_START = re.compile(r"^\((?:\d{1,3}[A-Z]?|[a-z]{1,2}|[ivxl]{1,6})\)\s*")  # "(1)", "(1A)", "(a)", "(iv)"
# headings: "Chapter II", "Annex I", "A. Definitions", "B.4 Other ...", "[B1. Matters ..."
HEADING = re.compile(r"^\[?(Chapter\b|Annex\b|[A-Z]\.\s|[A-Z]\.?\d+(?:\.\d+)*\.?\s)")
ANNEX_NAME = re.compile(r"^Annex(?:ure)?\s*[IVXLC\d]*", re.IGNORECASE)
LETTERHEAD = re.compile(
    r"^(RESERVE BANK OF INDIA|RBI/\S+|D[Oo][Rr]\.\S+|Table of Contents|"
    r"(January|February|March|April|May|June|July|August|September|October|November|"
    r"December) \d{1,2}, \d{4})$")
REF_NO = re.compile(r"^(RBI/|D[Oo][Rr]\.)")                 # "RBI/DOR/2025-26/148", "DoR.HOL.REC..."
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SIGNATURE_NAME = re.compile(r"^\([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)+\)$")  # "(Scenta Joy)"
DESIGNATION = re.compile(
    r"^(Principal )?(Chief General Manager|General Manager|Executive Director|"
    r"Deputy Governor)(-in-Charge)?$")
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def tidy(text: str) -> str:
    """Fix odd characters and spaces. Quotes are made straight, never removed."""
    text = unicodedata.normalize("NFKC", text).translate(QUOTES)
    return re.sub(r"[ \t]+", " ", text).strip()


# ---------- 1. EXTRACT ----------
def extract_lines(doc):
    """Every text line as a dict: page, y (0-1 down the page), text, size, bold, markers."""
    sizes = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    sizes[round(s["size"])] += len(s["text"].strip())
    body = sizes.most_common(1)[0][0]  # the most common size is the body text (12 pt here)

    lines = []
    for page_no, page in enumerate(doc, start=1):
        height = page.rect.height
        tables = [t for t in page.find_tables().tables]
        table_boxes = [pymupdf.Rect(t.bbox) for t in tables]

        for t in tables:  # each table becomes one item placed where the table sits
            rows = table_rows(t)
            letterhead = any("RESERVE BANK OF INDIA" in r or REF_NO.match(r) for r in rows)
            if rows and not (page_no == 1 and letterhead):
                lines.append({"page": page_no, "y": t.bbox[1] / height, "x": t.bbox[0], "kind": "table",
                              "text": "\n".join(rows), "size": body, "bold": False, "markers": []})

        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans or any(pymupdf.Rect(line["bbox"]).intersects(b) for b in table_boxes):
                    continue
                size = max(s["size"] for s in spans)
                text, markers = "", []
                y = spans[-1]["origin"][1] / height  # baseline of the line's main text
                only_marker = (len(spans) == 1 and spans[0]["size"] < body * 0.8
                               and spans[0]["text"].strip().isdigit()
                               and spans[0]["origin"][1] / height < 0.45)
                prev_end = None
                for s in spans:
                    small_digits = s["size"] < body * 0.8 and s["text"].strip().isdigit()
                    if small_digits and (size >= body - 1.2 or only_marker):
                        markers.append(int(s["text"]))  # footnote marker inside body text
                        continue
                    # Some PDFs leave out the space between two pieces of text and just
                    # leave a gap ("banks" + "are" -> "banksare"). Put the space back.
                    gap = s["bbox"][0] - prev_end if prev_end is not None else 0
                    if text and gap > s["size"] * 0.15 and not text.endswith(" ") \
                            and not s["text"].startswith(" "):
                        text += " "
                    text += s["text"]
                    prev_end = s["bbox"][2]
                if only_marker:
                    y += 0.012  # a raised marker belongs to the text right after it
                lines.append({
                    "page": page_no, "y": y, "x": line["bbox"][0], "kind": "line",
                    "text": tidy(text), "size": size, "markers": markers,
                    "bold": all("Bold" in s["font"] for s in spans if s["text"].strip()),
                    "first_small_digits": spans[0]["text"].strip()
                    if spans[0]["size"] < body * 0.8 and spans[0]["text"].strip().isdigit() else None,
                })
    # Reading order: top to bottom; text on the same visual row goes left to right
    lines.sort(key=lambda l: (l["page"], round(l["y"] * 200), l["x"]))
    return lines, body


def table_rows(table):
    """Table -> rows like 'Chief Financial Officer | Qualification: ...'."""
    rows = []
    for row in table.extract():
        cells = []
        for cell in row:
            cell = tidy((cell or "").replace("\n", " "))
            if cell and (not cells or cells[-1] != cell):  # skip empty and merged duplicates
                cells.append(cell)
        if cells:
            rows.append(" | ".join(cells))
    return rows


# ---------- 2. CLEAN ----------
def clean(lines, body):
    """Remove noise, collect footnotes.
    Returns (clean lines, footnotes {number: text}, footnote pages {number: page})."""
    footnotes, note_pages, last_note, pending_note = {}, {}, None, None
    kept = []

    # Pages that hold the table of contents: drop from "Table of Contents" to the last dot leader
    toc_pages = {p for p, n in Counter(l["page"] for l in lines
                                       if DOT_LEADER.search(l["text"])).items() if n >= 3}
    toc_end = {p: max(l["y"] for l in lines if l["page"] == p and DOT_LEADER.search(l["text"]))
               for p in toc_pages}
    toc_start = {}
    for l in lines:
        if l["page"] in toc_pages and l["text"] == "Table of Contents":
            toc_start[l["page"]] = l["y"]

    for l in lines:
        text = l["text"]
        if l["kind"] == "table":
            kept.append(l)
            continue
        if not text:
            if l["markers"]:
                kept.append(l)  # a footnote marker on its own; it belongs to this paragraph
            continue
        # page numbers at the top or bottom edge
        if re.fullmatch(r"\d{1,3}", text) and (l["y"] < 0.12 or l["y"] > 0.88):
            continue
        # footnotes: small text in the lower part of the page
        if l["size"] < body - 1.2 and l["y"] > 0.45:
            m = re.match(r"^(\d{1,3})\s+(.*)", text)
            if l["first_small_digits"] or m:
                number = int(l["first_small_digits"] or m.group(1))
                rest = text if l["first_small_digits"] else m.group(2)
                if l["first_small_digits"]:
                    rest = re.sub(rf"^{number}\s*", "", text) if text.startswith(str(number)) else text
                footnotes[number], note_pages[number] = tidy(rest), l["page"]
                last_note, pending_note = number, None
            elif re.fullmatch(r"\d{1,3}", text):
                pending_note = int(text)  # marker on its own line; the text follows
            elif pending_note is not None:
                footnotes[pending_note], note_pages[pending_note] = text, l["page"]
                last_note, pending_note = pending_note, None
            elif last_note is not None:
                footnotes[last_note] += " " + text  # footnote continues on the next line
            continue
        # table of contents
        if l["page"] in toc_pages:
            start = toc_start.get(l["page"], 0)
            if start <= l["y"] <= toc_end[l["page"]] or DOT_LEADER.search(text):
                continue
        # letterhead, reference numbers, dates on their own line, Hindi letterhead
        if LETTERHEAD.match(text) or DEVANAGARI.search(text):
            continue
        if l["page"] == 1 and REF_NO.match(text):  # reference number line, maybe with the date
            continue
        # signature block
        if SIGNATURE_NAME.match(text) or DESIGNATION.match(text):
            continue
        kept.append(l)
    return kept, footnotes, note_pages


def join_lines(texts):
    """Join wrapped lines. 'sub-' + 'section' -> 'sub-section' (the hyphen is real here)."""
    out = ""
    for t in texts:
        if not out:
            out = t
        elif out.endswith("\n"):
            out += t
        elif out.endswith("-") and not out.endswith(" -"):
            out += t  # in RBI PDFs a hyphen at a line end is part of the word ("Non-Banking")
        else:
            out += " " + t
    return out.strip()


# ---------- 3. CHUNK ----------
def paragraphs(lines):
    """Group clean lines into numbered paragraphs with chapter/section context."""
    paras, current = [], None
    chapter = section = ""
    zone, last_number = "", 0          # zone = "" for the main body, or e.g. "Annex I"
    heading_open = False

    def start(label, page):
        return {"para": label, "page": page, "page_end": page, "markers": [],
                "section": " > ".join(x for x in (zone, chapter, section) if x),
                "parts": []}

    for l in lines:
        text = l["text"]
        if l["kind"] == "table":
            if current is None:
                current = start(f"{zone} (intro)".strip() if zone else "preamble", l["page"])
            current["parts"].append(("\n", text, l["page"]))
            heading_open = False
            continue

        if not text:  # a lone footnote marker
            if current:
                current["markers"] += l["markers"]
            continue

        if l["bold"] and (HEADING.match(text) or heading_open) and not PARA_START.match(text):
            if heading_open and not HEADING.match(text):  # a heading wrapping onto a second line
                if section:
                    section += " " + text
                else:
                    chapter += " " + text
                continue
            if text.startswith("Annex"):
                zone = ANNEX_NAME.match(text).group(0).strip()
                chapter, last_number = "", 0
                section = text[len(zone):].strip(" -–:")
            elif text.startswith("Chapter"):
                chapter, section = text, ""
            else:
                section = text
            heading_open = True
            if current:
                paras.append(current)
            current = None
            continue
        heading_open = False

        m = PARA_START.match(text)
        number = int(m.group(1)) if m else None
        suffix = m.group(2) if m else ""
        # accept the next numbers in sequence (gaps of up to 5 for deleted paragraphs),
        # or an inserted paragraph such as 19A right after 19
        in_order = number is not None and (last_number < number <= last_number + 5
                                           or (suffix and number == last_number))
        if in_order:
            if current:
                paras.append(current)
            label = f"{number}{suffix}"
            current = start(f"{zone}, {label}" if zone else label, l["page"])
            last_number = number
            text = text[m.end():].strip()
            if not text:
                current["markers"] += l["markers"]
                continue
        if current is None:
            current = start(f"{zone} (intro)".strip() if zone else "preamble", l["page"])
        # sub-items such as "(1)" or "(iv)" start on a new line inside the paragraph
        brk = "\n" if ITEM_START.match(text) else ""
        current["parts"].append((brk, text, l["page"]))
        current["page_end"] = l["page"]
        current["markers"] += l["markers"]
    if current:
        paras.append(current)
    return paras


def paragraph_text(parts):
    pieces = []
    for brk, text, _ in parts:
        pieces.append(("\n" if brk else "") + text)
    joined = join_lines(pieces)
    joined = re.sub(r" (\(\d{1,3}[A-Z]\) ')", r"\n\1", joined)  # "(1A) 'Assignee'" starts a line
    joined = re.sub(r"(\(\w{1,6}\))\s*\n\s*", r"\1 ", joined)  # "(1)\n'Amalgamated" -> "(1) 'Amalgamated"
    joined = re.sub(r"[._]{5,}", "____", joined)  # blank lines to fill in, on forms
    # "sub- broker" -> "sub-broker", but keep "pre- and post-sanction" as written
    joined = re.sub(r"(\w)- (?!(?:and|or|to)\b)([a-z])", r"\1-\2", joined)
    return re.sub(r"\n\s+", "\n", joined).strip()


def split_long(text, limit=MAX_CHARS):
    """Split at line breaks (sub-items), then at sentence ends if still too long."""
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # one very long sub-item
            cut = line.rfind(". ", 0, limit) + 1 or limit
            pieces.append((current + "\n" + line[:cut]).strip() if current else line[:cut].strip())
            current, line = "", line[cut:].strip()
        if current and len(current) + len(line) + 1 > limit:
            pieces.append(current.strip())
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current.strip():
        pieces.append(current.strip())
    return pieces


def piece_page(piece, para):
    """The page where a split-off part of a long paragraph starts, for exact citations."""
    start = re.sub(r"^\(\w{1,6}\)\s*", "", piece)  # "(8)" sits on its own line in the PDF
    start = re.sub(r"\s+", " ", start[:40]).strip()[:25]
    for _, text, page in para["parts"]:
        if start and start in re.sub(r"\s+", " ", text):
            return page
    return para["page"]


def find_title(lines):
    """Fallback title from page 1 when the registry has no row for this file."""
    page1 = [l["text"] for l in lines if l["page"] == 1 and l["kind"] == "line"]
    for i, t in enumerate(page1):
        if t.startswith("Reserve Bank of India ("):
            title = t
            for nxt in page1[i + 1:i + 3]:
                if nxt == "Table of Contents" or (title.rstrip().endswith((")", "2025", "2026"))
                                                  and "Directions" in title and not nxt.startswith("(")):
                    break
                title += " " + nxt
            return title.strip()
    return ""


def parse_pdf(path, meta):
    with pymupdf.open(path) as doc:
        raw, body = extract_lines(doc)
    title = meta.get("title") or find_title(raw) or path.stem
    lines, footnotes, note_pages = clean(raw, body)
    paras = paragraphs(lines)

    # A footnote whose marker could not be found goes to the paragraph on its page
    referenced = {n for p in paras for n in p["markers"]}
    for n in sorted(set(footnotes) - referenced):
        for p in paras:
            if p["page"] <= note_pages[n] <= p["page_end"]:
                p["markers"].append(n)
                break

    chunks, stats = [], Counter()
    for p in paras:
        text = paragraph_text(p["parts"])
        notes = [f"Footnote {n}: {footnotes[n]}" for n in dict.fromkeys(p["markers"]) if n in footnotes]
        # keep deleted paragraphs such as "[Deleted]." or "[*****]": they matter for currency checks
        if len(text) < 5 or (len(text) < 20 and not notes and not re.search(r"Deleted|\*{3}", text)):
            continue
        pieces = split_long(text)
        for i, piece in enumerate(pieces, start=1):
            page = piece_page(piece, p) if i > 1 else p["page"]
            chunks.append({
                "doc_id": path.stem, "title": title, "para": p["para"],
                "part": i, "parts": len(pieces), "section": p["section"],
                "page": page, "page_end": p["page_end"], "text": piece,
                "notes": notes, "pdf_url": meta.get("pdf_url", ""),
                "updated_as_on": meta.get("updated_as_on", ""),
            })
        stats["paragraphs"] += 1
    stats.update(pages=max(l["page"] for l in raw), footnotes=len(footnotes),
                 tables=sum(l["kind"] == "table" for l in lines), chunks=len(chunks))
    return chunks, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", type=int, default=0, help="print N random chunks to check")
    args = parser.parse_args()

    registry = {}
    if REGISTRY.exists():
        registry = {r["doc_id"]: r for r in csv.DictReader(REGISTRY.open(encoding="utf-8"))}

    all_chunks = []
    for pdf in sorted(RAW.glob("*.pdf")):
        chunks, stats = parse_pdf(pdf, registry.get(pdf.stem, {}))
        seen = set()  # duplicates only within one direction; the same sentence in two
        for c in chunks:  # different directions is two separate rules
            if (c["para"], c["text"]) in seen:
                continue
            seen.add((c["para"], c["text"]))
            c["chunk_id"] = f"{c['doc_id']}-{len(all_chunks):05d}"
            all_chunks.append(c)
        print(f"{pdf.name}: {stats['pages']} pages, {stats['paragraphs']} paragraphs, "
              f"{stats['footnotes']} footnotes, {stats['tables']} tables -> {stats['chunks']} chunks")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_chunks, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(all_chunks)} chunks to {OUT}")

    for c in random.Random(1).sample(all_chunks, min(args.show, len(all_chunks))):
        print("\n" + "=" * 80)
        print(f"{c['doc_id']} | para {c['para']} (part {c['part']}/{c['parts']}) | page {c['page']}")
        print(f"section: {c['section']}")
        print(c["text"])
        for n in c["notes"]:
            print("  NOTE:", n)


if __name__ == "__main__":
    main()
