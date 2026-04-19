"""
Full pipeline integration test — Day 10 verification.
Run: python tests/pipeline_test.py
"""
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_DIR = Path("samples/invoices")
INBOX = Path("inbox")
PROCESSED = Path("processed")
FAILED = Path("failed")
STATS_FILE = Path("logs/stats.json")
MANIFEST_PATH = SAMPLE_DIR / "manifest.json"

CRITERIA = {
    "All 25 invoices processed": False,
    "Accuracy > 85% on vendor_name": False,
    "Accuracy > 85% on invoice_number": False,
    "Accuracy > 80% on total_amount": False,
    "Average processing time < 10s": False,
    "Zero crashes": True,  # default pass unless we detect crash
    "All rows in Google Sheets / CSV": False,
}


def _normalize(val) -> str:
    s = str(val).strip().lower()
    s = s.replace(",", "").replace(" ", "")
    s = s.replace("$", "").replace("£", "").replace("€", "")
    s = s.lstrip("s")  # OCR reads $ as S
    return s


def string_match(extracted, ground_truth) -> bool:
    if extracted is None or ground_truth is None:
        return False
    e = _normalize(extracted)
    g = _normalize(ground_truth)
    return e == g or g in e or e in g


def load_stats() -> dict:
    if STATS_FILE.exists():
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def run_pipeline_test():
    print("=" * 60)
    print("  PIPELINE INTEGRATION TEST — Day 10")
    print("=" * 60)

    if not MANIFEST_PATH.exists():
        print("ERROR: manifest.json not found. Run samples/generate_samples.py first.")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    images = sorted(SAMPLE_DIR.glob("invoice_0*.png"))
    print(f"\nFound {len(images)} sample invoices.")

    # Run OCR pipeline directly (without requiring watcher)
    from core.ocr_engine import OCREngine
    from core.field_extractor import FieldExtractor
    from core.confidence_scorer import ConfidenceScorer
    from core.sheets_writer import SheetsWriter

    engine = OCREngine(gpu=False)
    extractor = FieldExtractor()
    scorer = ConfidenceScorer()
    writer = SheetsWriter()
    writer.connect()

    results = []
    vendor_correct = invoice_correct = total_correct = 0
    total_time = 0.0

    print("\nProcessing invoices...")
    for img_path in images:
        fname = img_path.name
        gt = manifest.get(fname, {})
        if not gt:
            continue

        start = time.time()
        ocr_result = engine.extract_text(str(img_path))
        fields = extractor.extract_all(ocr_result["raw_text"])
        scoring = scorer.score_extraction(fields, ocr_result["confidence"])
        elapsed = time.time() - start
        total_time += elapsed

        result = {
            "status": "success", "filename": fname, "fields": fields,
            "confidence": scoring["overall"],
            "low_confidence_fields": scoring["low_confidence_fields"],
            "processing_time_seconds": round(elapsed, 3),
            "needs_review": scoring["needs_review"],
        }
        writer.write_result(result)
        results.append(result)

        if string_match(fields.get("vendor_name"), gt.get("vendor_name")):
            vendor_correct += 1
        if string_match(fields.get("invoice_number"), gt.get("invoice_number")):
            invoice_correct += 1
        if string_match(fields.get("total_amount"), gt.get("total_amount")):
            total_correct += 1

        print(f"  {fname}: conf={scoring['overall']:.1f}% time={elapsed:.1f}s")

    n = len(results)
    avg_time = total_time / n if n > 0 else 0
    vendor_acc = vendor_correct / n * 100 if n > 0 else 0
    invoice_acc = invoice_correct / n * 100 if n > 0 else 0
    total_acc = total_correct / n * 100 if n > 0 else 0
    summary = writer.get_summary()

    CRITERIA["All 25 invoices processed"] = n >= 25
    CRITERIA["Accuracy > 85% on vendor_name"] = vendor_acc > 85
    CRITERIA["Accuracy > 85% on invoice_number"] = invoice_acc > 85
    CRITERIA["Accuracy > 80% on total_amount"] = total_acc > 80
    CRITERIA["Average processing time < 10s"] = avg_time < 10
    CRITERIA["All rows in Google Sheets / CSV"] = summary["total_rows"] >= n

    print()
    print("=" * 60)
    print("  PIPELINE TEST RESULTS")
    print("=" * 60)
    print(f"  Invoices processed:  {n}")
    print(f"  Vendor accuracy:     {vendor_acc:.1f}%")
    print(f"  Invoice# accuracy:   {invoice_acc:.1f}%")
    print(f"  Total accuracy:      {total_acc:.1f}%")
    print(f"  Avg processing time: {avg_time:.1f}s")
    print(f"  Sheet rows:          {summary['total_rows']}")
    print()
    all_pass = True
    for criterion, passed in CRITERIA.items():
        status = "PASS ✅" if passed else "FAIL ❌"
        print(f"  [{status}] {criterion}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("WEEK 2 COMPLETE ✅")
    else:
        print("Some criteria failed — check results above.")

    # Save report
    report = {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        "invoices_processed": n,
        "vendor_accuracy": round(vendor_acc, 1),
        "invoice_accuracy": round(invoice_acc, 1),
        "total_accuracy": round(total_acc, 1),
        "avg_processing_time": round(avg_time, 2),
        "sheet_rows": summary["total_rows"],
        "criteria": CRITERIA,
    }
    with open("logs/pipeline_test_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nReport saved: logs/pipeline_test_report.json")
    return report


if __name__ == "__main__":
    run_pipeline_test()
