import importlib
import sys

for m in ("pypdf", "PyPDF2", "fitz", "pdfminer", "pdfplumber"):
    try:
        importlib.import_module(m)
        print(m, "AVAILABLE")
    except Exception:
        print(m, "missing")

print("---", sys.version)
