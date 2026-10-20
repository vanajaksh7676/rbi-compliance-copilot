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
# "4.", "4. In these", "19A." (inserted), and "13.The bank" (some PDFs leave out the space)
PARA_START = re.compile(r"^\[?(\d{1,3})([A-Z]{0,2})\.(?:\s+|$|(?=[A-Z'\"‘“\[]))")
ITEM_START = re.compile(r"^\((?:\d{1,3}[A-Z]?|[a-z]{1,2}|[ivxl]{1,6})\)\s*")  # "(1)", "(1A)", "(a)", "(iv)"
# headings: "Chapter II", "CHAPTER II", "PART D:", "Annex I", "Appendix 1", "A. Definitions",
# "B.4 Other ...", "[B1. Matters ..."
HEADING = re.compile(r"^\[?(Chapter\b|CHAPTER\b|Part\b|PART\b|Annex|Appendix\b|[A-Z]\.\s|"
                     r"[A-Z]\.?\d+(?:\.\d+)*\.?\s)")
ANNEX_NAME = re.compile(r"^(?:Annex(?:ure)?|Appendix)\s*[IVXLC\d]*", re.IGNORECASE)
CONTENTS = re.compile(r"^(Table of Contents|Contents|CONTENTS|INDEX)$")
# footnote markers: small digits ("1", "12") or small roman numerals ("iv", "vii")
GLUED_DELETED = re.compile(r"^(.*\S)\s+(\d{1,3}[A-Z]{0,2}\.\s*\[Deleted\].*)$")
MARKER = re.compile(r"^(\d{1,3}|[ivxlc]{1,6})$")
LETTERHEAD = re.compile(
    r"^(_*RESERVE BANK OF INDIA_*|www\.rbi\.org\.in|RBI/\S+|D[Oo][Rr]\.\S+|Table of Contents|"
    r"(January|February|March|April|May|June|July|August|September|October|November|"
    r"December) \d{1,2}, \d{4})$")
REF_NO = re.compile(r"^(RBI/|D[Oo][Rr]\.)")                 # "RBI/DOR/2025-26/148", "DoR.HOL.REC..."
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SIGNATURE_NAME = re.compile(r"^\([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)+\)$")  # "(Scenta Joy)"
DESIGNATION = re.compile(
    r"^\(?(Principal )?(Chief General Manager|General Manager|Executive Director|"
    r"Deputy Governor)(-in-Charge)?\)?$")
PLAIN_NAME = re.compile(r"^[A-Z][a-z.]+(?: [A-Z][A-Za-z.]*){1,3}$")  # "Vaibhav Chaturvedi"
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def tidy(text: str) -> str:
    """Fix odd characters and spaces. Quotes are made straight, never removed."""
    text = unicodedata.normalize("NFKC", text).translate(QUOTES)
    return re.sub(r"[ \t]+", " ", text).strip()


# ---------- 1. EXTRACT ----------
def is_marker(span, body, ref=None):
    """A footnote marker: small digits ("2") or roman numerals ("vi") raised above the
    text next to it (ref). Small numbers in a table, or a lowered subscript such as the
    "i" in "Mi", are not markers."""
    if span["size"] >= body * 0.8 or not MARKER.match(span["text"].strip()):
        return False
    if ref is None:
        return True
    return span["size"] < ref["size"] * 0.8 and span["origin"][1] < ref["origin"][1] - 0.5


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
        page_lines = [line for block in page.get_text("dict")["blocks"]
                      for line in block.get("lines", [])]
        tables = [t for t in page.find_tables().tables]
        table_boxes = [pymupdf.Rect(t.bbox) for t in tables]

        for t in tables:  # each table becomes one item placed where the table sits
            rows, markers = table_rows(t, page_lines, body)
            letterhead = any("RESERVE BANK OF INDIA" in r or REF_NO.match(r) for r in rows)
            if rows and not (page_no == 1 and letterhead):
                lines.append({"page": page_no, "y": t.bbox[1] / height, "x": t.bbox[0], "kind": "table",
                              "text": "\n".join(rows), "size": body, "bold": False, "markers": markers})

        for line in page_lines:
            spans = [s for s in line["spans"] if s["text"].strip()]
            # a line belongs to a table only if its middle is inside the table; a line that
            # just touches the table's edge is the next paragraph and must be kept
            mid = pymupdf.Point((line["bbox"][0] + line["bbox"][2]) / 2, (line["bbox"][1] + line["bbox"][3]) / 2)
            if not spans or any(box.contains(mid) for box in table_boxes):
                continue
            size = max(s["size"] for s in spans)
            main = max(spans, key=lambda s: s["size"])  # the line's normal text
            text, markers = "", []
            y = spans[-1]["origin"][1] / height  # baseline of the line's main text
            only_marker = (len(spans) == 1 and is_marker(spans[0], body)
                           and spans[0]["origin"][1] / height < 0.45)
            prev_end = None
            for s in spans:
                if (only_marker or (size >= body - 1.2 and is_marker(s, body, main))):
                    markers.append(s["text"].strip())  # footnote marker inside body text
                    prev_end = s["bbox"][2] if prev_end is not None else None  # no space for it
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
                "first_marker": spans[0]["text"].strip() if is_marker(spans[0], body) else None,
            })
    # Reading order: top to bottom; text on the same visual row goes left to right
    lines.sort(key=lambda l: (l["page"], round(l["y"] * 200), l["x"]))
    return lines, body


def table_rows(table, page_lines, body):
    """Table -> rows like 'Chief Financial Officer | Qualification: ...'.
    PyMuPDF reads table cells without font sizes, so a raised footnote marker gets glued
    to the number before it ("plus 350" + small "2" -> "plus 3502"). We find each small
    marker inside the table, look at the text just before it, and cut the marker out."""
    box = pymupdf.Rect(table.bbox)
    glued, markers = [], []
    for line in page_lines:
        spans = [s for s in line["spans"] if s["text"].strip()]
        for before, s in zip(spans, spans[1:]):
            if is_marker(s, body, before) and box.intersects(pymupdf.Rect(s["bbox"])):
                tail = before["text"].rstrip()[-12:]
                if tail:
                    glued.append((tail + s["text"].strip(), tail))
                markers.append(s["text"].strip())
        if len(spans) > 1 and is_marker(spans[0], body, spans[1]) and box.intersects(pymupdf.Rect(spans[0]["bbox"])):
            markers.append(spans[0]["text"].strip())  # marker at the start of a cell line
            glued.append(("\n" + spans[0]["text"].strip(), "\n"))
    rows = []
    for row in table.extract():
        cells = []
        for cell in row:
            cell = "\n" + (cell or "")
            for wrong, right in glued:
                cell = cell.replace(wrong, right, 1)
            cell = tidy(cell.replace("\n", " "))
            if cell and (not cells or cells[-1] != cell):  # skip empty and merged duplicates
                cells.append(cell)
        if cells:
            rows.append(" | ".join(cells))
    return rows, markers


# ---------- 2. CLEAN ----------
def norm(text):
    """Text without dot leaders and page numbers, for comparing headings."""
    return re.sub(r"[\s.]*\d*$", "", DOT_LEADER.sub(" ", text)).strip().lower()


def contents_zone(lines):
    """Line positions (start, end) of a table of contents that has no dot leaders.
    Some PDFs list 'CHAPTER I – PRELIMINARY' / '1.' / 'Introduction' / '3' on separate
    lines. The contents end where its first entry appears again as a real heading."""
    for i, l in enumerate(lines):
        if l["page"] > 5:
            return None
        if l["kind"] == "line" and CONTENTS.match(l["text"]):
            first = next((norm(x["text"]) for x in lines[i + 1:i + 6]
                          if x["kind"] == "line" and norm(x["text"]) and not MARKER.match(x["text"])), "")
            for j in range(i + 2, len(lines)):
                if lines[j]["page"] > l["page"] + 10:
                    break
                if first and lines[j]["kind"] == "line" and norm(lines[j]["text"]) == first:
                    return i, j
            return None
    return None


def running_headers(lines):
    """Text repeated at the top or bottom of many pages, e.g. the direction's title in
    small italics on every page. It is noise in the middle of a paragraph."""
    pages = max(l["page"] for l in lines)
    edge = Counter(l["text"] for l in lines
                   if l["kind"] == "line" and l["text"] and (l["y"] < 0.1 or l["y"] > 0.92))
    return {t for t, n in edge.items() if n >= max(3, pages * 0.3) and not t.isdigit()}


def clean(lines, body):
    """Remove noise, collect footnotes.
    Returns (clean lines, footnotes {marker: text}, footnote pages {marker: page})."""
    footnotes, note_pages, last_note, pending_note = {}, {}, None, None
    kept = []

    # Pages that hold the table of contents: drop from "Table of Contents" to the last dot leader
    toc_pages = {p for p, n in Counter(l["page"] for l in lines
                                       if DOT_LEADER.search(l["text"])).items() if n >= 3}
    toc_end = {p: max(l["y"] for l in lines if l["page"] == p and DOT_LEADER.search(l["text"]))
               for p in toc_pages}
    toc_start = {}
    for l in lines:
        if l["page"] in toc_pages and CONTENTS.match(l["text"]):
            toc_start[l["page"]] = l["y"]
    zone = contents_zone(lines) if not toc_pages else None
    headers = running_headers(lines)

    for i, l in enumerate(lines):
        text = l["text"]
        if zone and zone[0] <= i < zone[1]:
            continue  # table of contents without dot leaders
        if l["kind"] == "table":
            kept.append(l)
            continue
        if not text:
            if l["markers"]:
                kept.append(l)  # a footnote marker on its own; it belongs to this paragraph
            continue
        # page numbers at the top or bottom edge, and running headers / footers
        if re.fullmatch(r"\d{1,3}", text) and (l["y"] < 0.12 or l["y"] > 0.88):
            continue
        if text in headers and (l["y"] < 0.1 or l["y"] > 0.92):
            continue
        # footnotes: small text in the lower part of the page
        if l["size"] < body - 1.2 and l["y"] > 0.45:
            m = re.match(r"^(\d{1,3})\s+(.*)", text)
            if l["first_marker"] or m:
                number = l["first_marker"] or m.group(1)
                rest = re.sub(rf"^{re.escape(number)}\s*", "", text)
                footnotes[number], note_pages[number] = tidy(rest), l["page"]
                last_note, pending_note = number, None
            elif MARKER.match(text):
                pending_note = text  # marker on its own line; the text follows
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
        # signature block: "(Scenta Joy)", or a plain name right above "(Chief General Manager)"
        if DESIGNATION.match(text):
            if kept and kept[-1]["kind"] == "line" and kept[-1]["page"] == l["page"] \
                    and PLAIN_NAME.match(kept[-1]["text"]) and not kept[-1]["bold"]:
                kept.pop()
            continue
        if SIGNATURE_NAME.match(text):
            continue
        glued = GLUED_DELETED.match(text)
        if glued:  # "... of exporters. 428.[Deleted]" -> two lines
            kept.append({**l, "text": glued.group(1)})
            kept.append({**l, "text": glued.group(2), "markers": [], "bold": False})
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
                current = start(intro_label(zone, last_number), l["page"])
            current["parts"].append(("\n", text, l["page"]))
            current["markers"] += l["markers"]
            current["after_table"] = True
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
            if ANNEX_NAME.match(text) and text.startswith(("Annex", "Appendix")):
                zone = ANNEX_NAME.match(text).group(0).strip()
                chapter, last_number = "", 0
                section = text[len(zone):].strip(" -–:")
            elif text.upper().startswith(("CHAPTER", "PART")):
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
            current = start(intro_label(zone, last_number), l["page"])
        # sub-items such as "(1)" or "(iv)" start on a new line inside the paragraph
        brk = "\n" if ITEM_START.match(text) or (current["parts"] and current.get("after_table")) else ""
        current["after_table"] = False
        current["parts"].append((brk, text, l["page"]))
        current["page_end"] = l["page"]
        current["markers"] += l["markers"]
    if current:
        paras.append(current)
    return paras


def intro_label(zone, last_number):
    """Label for text that has no paragraph number, e.g. a 'Background:' box under a heading."""
    if zone:
        return f"{zone} (intro)"
    return f"note after para {last_number}" if last_number else "preamble"


def paragraph_text(parts):
    pieces = []
    for brk, text, _ in parts:
        pieces.append(("\n" if brk else "") + text)
    joined = join_lines(pieces)
    joined = re.sub(r" (\(\d{1,3}[A-Z]\) ')", r"\n\1", joined)  # "(1A) 'Assignee'" starts a line
    joined = re.sub(r"(\(\w{1,6}\))\s*\n\s*", r"\1 ", joined)  # "(1)\n'Amalgamated" -> "(1) 'Amalgamated"
    joined = re.sub(r"[._]{5,}", "____", joined)
    joined = re.sub(r"(\w) +([.,;:])(?=\s|$)", r"\1\2", joined)  # "2026 ." -> "2026."  # blank lines to fill in, on forms
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
