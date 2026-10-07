

"""Make a simple web page with a clickable link for every PDF in the registry,
so you can download them one by one in your normal browser."""
import csv
import html
from pathlib import Path
 
RAW = Path("data/raw")
OUT = Path("data/download_links.html")
 
with open("data/registry.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
 
items = []
for row in rows:
    have = any(p.stem.lower() == row["doc_id"].lower()
               for p in RAW.glob("*.pdf"))
    mark = "done" if have else "TODO"
    items.append(
        f'<li>[{mark}] <a href="{html.escape(row["pdf_url"])}" '
        f'target="_blank">{html.escape(row["title"])}</a></li>'
    )
 
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(
    "<html><body><h2>RBI PDFs - click, save into data/raw</h2><ol>"
    + "\n".join(items) + "</ol></body></html>",
    encoding="utf-8",
)
print("Wrote", OUT, "with", len(rows), "links")
 
