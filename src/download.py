"""Build data/registry.csv from RBI's Master Directions page and download the
PDFs."""
import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx?did=403"  # Commercial Banks
RAW = Path("data/raw")
REGISTRY = Path("data/registry.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (student research project)"}
FIELDS = ["doc_id", "title", "pdf_url", "updated_as_on", "status",
          "replaced_by", "note"]


def build_registry():
    html = requests.get(LIST_URL, headers=HEADERS, timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    rows, seen, title = [], set(), None

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "BS_ViewMasDirections.aspx?id=" in href:
            title = a.get_text(" ", strip=True)  # the direction's title link
        elif href.upper().endswith(".PDF") and title and href not in seen:
            seen.add(href)  # the PDF link that follows the title
            if "Commercial Banks" not in title:
                continue
            m = re.search(r"Updated as on (\w+ \d{1,2}, \d{4})", title,
                          re.IGNORECASE)
            rows.append({
                "doc_id": Path(href).stem,
                "title": title,
                "pdf_url": href,
                "updated_as_on": m.group(1) if m else "",
                "status": "current",
                "replaced_by": "",
                "note": "",
            })

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Registry: {len(rows)} directions")


def download_pdfs():
    RAW.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = RAW / f"{row['doc_id']}.pdf"
            if path.exists():
                continue  # already downloaded
            print("Downloading", row["title"][:80])
            r = requests.get(row["pdf_url"], headers=HEADERS, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
            time.sleep(2)  # be polite to RBI's server


if __name__ == "__main__":
    if REGISTRY.exists():
        print("Keeping the existing registry (delete it to rebuild).")
    else:
        build_registry()
    download_pdfs()