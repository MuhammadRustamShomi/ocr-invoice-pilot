"""
User Acceptance Test (UAT) — Day 14 verification.
Tests 7 real-world scenarios.
Run: python tests/uat_test.py
  (requires API running on port 8000)
"""
import sys
import os
import json
import time
import shutil
import base64
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

API_URL = "http://127.0.0.1:8000"
API_KEY = os.getenv("API_KEY", "ocr-pilot-key-2026")
SAMPLE_DIR = Path("samples/invoices")
INBOX = Path("inbox")
PROCESSED = Path("processed")
FAILED = Path("failed")

results = {}


def check_api_running() -> bool:
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def scenario_1_happy_path() -> bool:
    """Drop invoice_001.png via API, verify fields extracted."""
    print("\n[Scenario 1] Happy Path — direct API call")
    img_path = SAMPLE_DIR / "invoice_001.png"
    if not img_path.exists():
        print("  SKIP — sample not found")
        return False
    with open(img_path, "rb") as f:
        resp = requests.post(
            f"{API_URL}/extract",
            files={"file": ("invoice_001.png", f, "image/png")},
            headers={"X-API-Key": API_KEY},
            timeout=120,
        )
    if resp.status_code != 200:
        print(f"  FAIL — HTTP {resp.status_code}")
        return False
    data = resp.json()
    vendor = data.get("fields", {}).get("vendor_name")
    inv_no = data.get("fields", {}).get("invoice_number")
    passed = data.get("status") == "success" and vendor and inv_no
    print(f"  vendor={vendor}, invoice#={inv_no} → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_2_pdf() -> bool:
    """Process a PDF invoice."""
    print("\n[Scenario 2] PDF Invoice")
    pdf_path = SAMPLE_DIR / "invoice_pdf_001.pdf"
    if not pdf_path.exists():
        print("  SKIP — PDF sample not found")
        return False
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{API_URL}/extract",
            files={"file": ("invoice_pdf_001.pdf", f, "application/pdf")},
            headers={"X-API-Key": API_KEY},
            timeout=120,
        )
    if resp.status_code != 200:
        print(f"  FAIL — HTTP {resp.status_code}")
        return False
    data = resp.json()
    passed = data.get("status") == "success"
    print(f"  confidence={data.get('confidence')} → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_3_bad_file() -> bool:
    """Send a text file — expect 415 Unsupported Media Type."""
    print("\n[Scenario 3] Bad File Type")
    fake_content = b"This is not an image"
    resp = requests.post(
        f"{API_URL}/extract",
        files={"file": ("invoice.txt", fake_content, "text/plain")},
        headers={"X-API-Key": API_KEY},
        timeout=30,
    )
    passed = resp.status_code == 415
    print(f"  HTTP {resp.status_code} (expected 415) → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_4_duplicate() -> bool:
    """Send same invoice twice — verify no crash, both return success."""
    print("\n[Scenario 4] Duplicate Invoice")
    img_path = SAMPLE_DIR / "invoice_002.png"
    if not img_path.exists():
        print("  SKIP — sample not found")
        return False
    success_count = 0
    for i in range(2):
        with open(img_path, "rb") as f:
            resp = requests.post(
                f"{API_URL}/extract",
                files={"file": ("invoice_002.png", f, "image/png")},
                headers={"X-API-Key": API_KEY},
                timeout=120,
            )
        if resp.status_code == 200 and resp.json().get("status") == "success":
            success_count += 1
    passed = success_count == 2
    print(f"  Both calls succeeded ({success_count}/2) → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_5_low_quality() -> bool:
    """Send a noisy invoice — verify needs_review=True (or low confidence)."""
    print("\n[Scenario 5] Low Quality Invoice")
    noisy = sorted(SAMPLE_DIR.glob("invoice_02*.png"))
    if not noisy:
        print("  SKIP — no noisy samples")
        return False
    with open(noisy[0], "rb") as f:
        resp = requests.post(
            f"{API_URL}/extract",
            files={"file": (noisy[0].name, f, "image/png")},
            headers={"X-API-Key": API_KEY},
            timeout=120,
        )
    if resp.status_code != 200:
        print(f"  FAIL — HTTP {resp.status_code}")
        return False
    data = resp.json()
    confidence = data.get("confidence", 100)
    needs_review = data.get("needs_review", False)
    # Pass if confidence is low OR needs_review is flagged
    passed = needs_review or confidence < 85
    print(f"  confidence={confidence}, needs_review={needs_review} → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_6_api_direct() -> bool:
    """Verify /extract response schema matches spec."""
    print("\n[Scenario 6] API Response Schema")
    img_path = SAMPLE_DIR / "invoice_003.png"
    if not img_path.exists():
        print("  SKIP — sample not found")
        return False
    with open(img_path, "rb") as f:
        resp = requests.post(
            f"{API_URL}/extract",
            files={"file": ("invoice_003.png", f, "image/png")},
            headers={"X-API-Key": API_KEY},
            timeout=120,
        )
    if resp.status_code != 200:
        print(f"  FAIL — HTTP {resp.status_code}")
        return False
    data = resp.json()
    required_keys = {"status", "filename", "fields", "confidence",
                     "low_confidence_fields", "processing_time_seconds", "needs_review"}
    field_keys = {"vendor_name", "invoice_number", "invoice_date", "due_date",
                  "line_items", "subtotal", "tax", "total_amount"}
    has_all_keys = required_keys.issubset(data.keys())
    has_field_keys = field_keys.issubset(data.get("fields", {}).keys())
    passed = has_all_keys and has_field_keys
    print(f"  response keys OK={has_all_keys}, field keys OK={has_field_keys} → {'PASS' if passed else 'FAIL'}")
    return passed


def scenario_7_security() -> bool:
    """POST without API key → 401."""
    print("\n[Scenario 7] Security — No API Key")
    img_path = SAMPLE_DIR / "invoice_001.png"
    with open(img_path, "rb") as f:
        resp = requests.post(
            f"{API_URL}/extract",
            files={"file": ("invoice_001.png", f, "image/png")},
            timeout=10,
        )
    passed = resp.status_code == 401
    print(f"  HTTP {resp.status_code} (expected 401) → {'PASS' if passed else 'FAIL'}")
    return passed


def run_uat():
    print("=" * 60)
    print("  UAT RESULTS — Day 14")
    print("=" * 60)

    if not check_api_running():
        print("\nERROR: API not running. Start it first:")
        print("  uvicorn api.main:app --port 8000")
        sys.exit(1)

    scenarios = [
        ("Scenario 1 (Happy Path)", scenario_1_happy_path),
        ("Scenario 2 (PDF)", scenario_2_pdf),
        ("Scenario 3 (Bad File)", scenario_3_bad_file),
        ("Scenario 4 (Duplicate)", scenario_4_duplicate),
        ("Scenario 5 (Low Quality)", scenario_5_low_quality),
        ("Scenario 6 (API Direct)", scenario_6_api_direct),
        ("Scenario 7 (Security)", scenario_7_security),
    ]

    passed_count = 0
    scenario_results = {}
    for name, fn in scenarios:
        try:
            ok = fn()
        except Exception as exc:
            print(f"  ERROR: {exc}")
            ok = False
        scenario_results[name] = ok
        if ok:
            passed_count += 1

    print()
    print("=" * 60)
    print("  FINAL UAT REPORT")
    print("=" * 60)
    for name, ok in scenario_results.items():
        status = "PASS ✅" if ok else "FAIL ❌"
        print(f"  {name:40s}: {status}")

    print()
    print(f"  Overall: {passed_count}/7 {'PASSED' if passed_count == 7 else 'FAILED'}", end="")
    if passed_count == 7:
        print(" — READY FOR GO-LIVE ✅")
    else:
        print("")

    return passed_count == 7


if __name__ == "__main__":
    success = run_uat()
    sys.exit(0 if success else 1)
