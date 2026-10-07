

"""Quick check of what is inside the downloaded PDFs (first 5 files)."""
from pathlib import Path
 
import pymupdf
 
files = sorted(Path("data/raw").glob("*.pdf"))
print("PDF files found:", len(files))
 
for pdf in files[:5]:
    size_kb = pdf.stat().st_size // 1024
    with open(pdf, "rb") as f:
        starts_with_pdf = f.read(5) == b"%PDF-"
    print("\n==", pdf.name, "|", size_kb, "KB | starts with %PDF:",
          starts_with_pdf)
    try:
        with pymupdf.open(pdf) as doc:
            text = "".join(page.get_text() for page in doc)
            print("pages:", len(doc), "| characters of text:", len(text))
            print("preview:", repr(text[:200]))
    except Exception as e:
        print("could not open:", e)
 
