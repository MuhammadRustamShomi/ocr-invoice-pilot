"""
Week 1 Summary — process all 25 sample invoices and print accuracy report.
Run: python tests/week1_summary.py
"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ocr_engine import OCREngine
from core.field_extractor import FieldExtractor
from core.confidence_scorer import ConfidenceScorer
from core.sheets_writer import SheetsWriter

MANIFEST_PATH = Path("samples/invoices/manifest.json")
SAMPLE_DIR = Path("samples/invoices")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def _normalize(val) -> str:
    """Normalize value for comparison: strip symbols, commas, spaces, lowercase."""
    s = str(val).strip().lower()
    s = s.replace(",", "").replace(" ", "")
    s = s.replace("$", "").replace("£", "").replace("€", "")
    s = s.lstrip("s")  # OCR misread $ as S
    return s


def string_match(extracted, ground_truth) -> bool:
    if extracted is None or ground_truth is None:
        return False
    e = _normalize(extracted)
    g = _normalize(ground_truth)
    return e == g or g in e or e in g


def run_week1_summary():
    print("=" * 60)
    print("  WEEK 1 SUMMARY — OCR Invoice Pilot")
    print("=" * 60)

    if not MANIFEST_PATH.exists():
        print("ERROR: manifest.json not found. Run samples/generate_samples.py first.")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    png_files = sorted(SAMPLE_DIR.glob("invoice_*.png"))
    if not png_files:
        print("ERROR: No PNG invoices found. Run samples/generate_samples.py first.")
        sys.exit(1)

    print(f"\nFound {len(png_files)} PNG invoices to process.\n")

    engine = OCREngine(gpu=False)
    extractor = FieldExtractor()
    scorer = ConfidenceScorer()
    writer = SheetsWriter()
    writer.connect()

    fields_to_check = ["vendor_name", "invoice_number", "invoice_date",
                        "due_date", "subtotal", "tax", "total_amount"]

    results = []
    field_correct = {f: 0 for f in fields_to_check}
    field_total = {f: 0 for f in fields_to_check}
    all_confidences = []
    all_times = []
    total_success = 0

    for img_path in png_files:
        fname = img_path.name
        ground_truth = manifest.get(fname, {})
        if not ground_truth:
            continue

        start = time.time()
        ocr_result = engine.extract_text(str(img_path))
        fields = extractor.extract_all(ocr_result["raw_text"])
        scoring = scorer.score_extraction(fields, ocr_result["confidence"])
        elapsed = time.time() - start

        result = {
            "status": "success",
            "filename": fname,
            "fields": fields,
            "confidence": scoring["overall"],
            "low_confidence_fields": scoring["low_confidence_fields"],
            "processing_time_seconds": round(elapsed, 3),
            "needs_review": scoring["needs_review"],
        }
        writer.write_result(result)
        results.append(result)

        all_confidences.append(scoring["overall"])
        all_times.append(elapsed)
        total_success += 1

        for field in fields_to_check:
            field_total[field] += 1
            gt_val = ground_truth.get(field)
            ex_val = fields.get(field)
            if string_match(ex_val, gt_val):
                field_correct[field] += 1

        print(f"  {fname}: conf={scoring['overall']:.1f}% | time={elapsed:.2f}s | "
              f"review={scoring['needs_review']}")

    print()
    print("=" * 60)
    print("  FIELD EXTRACTION ACCURACY")
    print("=" * 60)
    for field in fields_to_check:
        total = field_total[field]
        correct = field_correct[field]
        pct = (correct / total * 100) if total > 0 else 0
        target = {"vendor_name": 80, "invoice_number": 85, "total_amount": 80}.get(field, 70)
        status = "PASS" if pct >= target else "WARN"
        print(f"  {field:20s}: {correct}/{total} = {pct:5.1f}% [{status}]")

    avg_conf = sum(all_confidences) / len(all_confidences) if all_confidences else 0
    avg_time = sum(all_times) / len(all_times) if all_times else 0

    print()
    print(f"  Total processed:    {total_success}")
    print(f"  Avg confidence:     {avg_conf:.1f}%")
    print(f"  Avg processing time: {avg_time:.2f}s")

    sheets_summary = writer.get_summary()
    print(f"  Sheet rows:         {sheets_summary['total_rows']}")

    # Save summary
    summary = {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        "total_processed": total_success,
        "avg_confidence": round(avg_conf, 2),
        "avg_processing_time": round(avg_time, 2),
        "field_accuracy": {
            f: round(field_correct[f] / field_total[f] * 100, 1) if field_total[f] > 0 else 0
            for f in fields_to_check
        },
        "sheet_rows": sheets_summary["total_rows"],
    }
    with open(LOG_DIR / "week1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved to logs/week1_summary.json")

    print()
    print("WEEK 1 COMPLETE ✅")
    return summary


if __name__ == "__main__":
    run_week1_summary()
