"""Smoke tests using the exact OCR texts reported by the user."""
from core.field_extractor import FieldExtractor
from core.confidence_scorer import ConfidenceScorer

e = FieldExtractor()
s = ConfidenceScorer()

CASES = {
    "BlueSky two-column (exact user OCR)": (
        "BlueSky Technologies Inc\n"
        "INVOICE\n"
        "Invoice Number:\n"
        "INV-2025-0001\n"
        "Invoice Date:\n"
        "2025-01-26\n"
        "Due Date:\n"
        "2025-02-25\n"
        "Description\n"
        "Qty\n"
        "Unit Price\n"
        "Total\n"
        "Cloud Hosting (Monthly)\n"
        "1\n"
        "$120.00\n"
        "$120.00\n"
        "Training Session (hrs)\n"
        "5\n"
        "$150.00\n"
        "$750.00\n"
        "SEO Optimization\n"
        "1\n"
        "$350.00\n"
        "$350.00\n"
        "Content Writing\n"
        "5\n"
        "$200.00\n"
        "$1,000.00\n"
        "Thank you for your business!\n"
        "Subtotal:\n"
        "Tax (15%):\n"
        "Grand Total:\n"
        "$2,220.00\n"
        "$333.00\n"
        "$2,553.00\n"
    ),
    "Inline layout (same-line values)": (
        "VANDELAY INDUSTRIES\n"
        "Invoice No: INV-2026-0042\n"
        "Invoice Date: 15/03/2026\n"
        "Due Date: 14/04/2026\n"
        "Subtotal: $1,460.77\n"
        "Tax (15%): $218.91\n"
        "Grand Total: $1,679.88\n"
    ),
    "Next-line layout": (
        "VANDELAY INDUSTRIES\n"
        "Invoice No:\nINV-2026-0042\n"
        "Invoice Date:\n03/15/2026\n"
        "Due Date:\n04/14/2026\n"
        "Subtotal:\n$1,460.77\n"
        "Tax (15%):\n$218.91\n"
        "Grand Total:\n$1,679.88\n"
    ),
}

EXPECTED = {
    "BlueSky two-column (exact user OCR)": {
        "vendor_name": "BlueSky Technologies Inc",
        "invoice_number": "INV-2025-0001",
        "invoice_date": "2025-01-26",
        "due_date": "2025-02-25",
        "subtotal": "$2,220.00",
        "tax": "$333.00",
        "total_amount": "$2,553.00",
    },
    "Inline layout (same-line values)": {
        "invoice_number": "INV-2026-0042",
        "invoice_date": "2026-03-15",
        "due_date": "2026-04-14",
        "subtotal": "$1,460.77",
        "tax": "$218.91",
        "total_amount": "$1,679.88",
    },
    "Next-line layout": {
        "invoice_number": "INV-2026-0042",
        "due_date": "2026-04-14",
        "subtotal": "$1,460.77",
        "tax": "$218.91",
        "total_amount": "$1,679.88",
    },
}

all_pass = True
for name, text in CASES.items():
    fields = e.extract_all(text)
    score = s.score_extraction(fields, ocr_confidence=85.0)
    exp = EXPECTED[name]
    print(f"\n=== {name} ===")
    for k, got in fields.items():
        if k == "line_items":
            continue
        want = exp.get(k)
        if want is None:
            status = "  "
        elif str(got) == str(want):
            status = "OK"
        else:
            status = "FAIL"
            all_pass = False
        print(f"  [{status}] {k}: {got!r}  (want: {want!r})")
    print(f"  Confidence: {score['overall']}%  Needs Review: {score['needs_review']}")
    print(f"  Low-conf: {score['low_confidence_fields']}")

print("\n" + ("ALL PASS ✅" if all_pass else "SOME FAILURES ❌"))
