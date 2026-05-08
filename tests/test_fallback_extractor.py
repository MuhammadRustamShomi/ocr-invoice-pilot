"""Test the _MinimalExtractor fallback with the exact user OCR text."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import just the fallback classes without running Streamlit
import importlib.util, types

# Stub streamlit so dashboard/app.py can be partially evaluated
st_stub = types.ModuleType("streamlit")
for attr in ["set_page_config","cache_resource","cache_data","warning","error","info","secrets"]:
    setattr(st_stub, attr, lambda *a, **k: None)
st_stub.secrets = {}
sys.modules["streamlit"] = st_stub
sys.modules["pandas"] = __import__("pandas")

# Now exec only the portion of app.py that defines the fallback classes
import re as _re

exec_globals = {"re": _re, "__name__": "test", "pd": __import__("pandas")}
with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard", "app.py"), encoding="utf-8") as f:
    src = f.read()

# Extract just the two fallback classes
import ast
tree = ast.parse(src)
fallback_src_lines = []
capture = False
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name in ("_MinimalExtractor", "_MinimalScorer"):
        start = node.lineno - 1
        end = node.end_lineno
        lines = src.splitlines()[start:end]
        fallback_src_lines.extend(lines)
        fallback_src_lines.append("")

fallback_src = "\n".join(fallback_src_lines)
exec(compile(fallback_src, "<fallback>", "exec"), exec_globals)

_MinimalExtractor = exec_globals["_MinimalExtractor"]
_MinimalScorer    = exec_globals["_MinimalScorer"]

OCR = (
    "BlueSky Technologies Inc\n"
    "INVOICE\n"
    "Invoice Number:\n"
    "INV-2025-0001\n"
    "Invoice Date:\n"
    "2025-01-26\n"
    "Due Date:\n"
    "2025-02-25\n"
    "Description\nQty\nUnit Price\nTotal\n"
    "Cloud Hosting (Monthly)\n1\n$120.00\n$120.00\n"
    "Training Session (hrs)\n5\n$150.00\n$750.00\n"
    "SEO Optimization\n1\n$350.00\n$350.00\n"
    "Content Writing\n5\n$200.00\n$1,000.00\n"
    "Thank you for your business!\n"
    "Subtotal:\nTax (15%):\nGrand Total:\n"
    "$2,220.00\n$333.00\n$2,553.00\n"
)

EXPECTED = {
    "vendor_name":    "BlueSky Technologies Inc",
    "invoice_number": "INV-2025-0001",
    "invoice_date":   "2025-01-26",
    "due_date":       "2025-02-25",
    "subtotal":       "$2,220.00",
    "tax":            "$333.00",
    "total_amount":   "$2,553.00",
}

e = _MinimalExtractor()
s = _MinimalScorer()
fields = e.extract_all(OCR)
score  = s.score_extraction(fields, ocr_confidence=98.25)

print("=== _MinimalExtractor (fallback) on BlueSky two-column OCR ===")
all_ok = True
for k, want in EXPECTED.items():
    got = fields.get(k)
    ok = str(got) == str(want)
    if not ok:
        all_ok = False
    print(f"  [{'OK' if ok else 'FAIL'}] {k}: {got!r}  (want: {want!r})")

print(f"\nConfidence: {score['overall']}%  Needs Review: {score['needs_review']}")
print(f"Low-conf: {score['low_confidence_fields']}")
print("\n" + ("ALL PASS" if all_ok else "SOME FAILURES"))
