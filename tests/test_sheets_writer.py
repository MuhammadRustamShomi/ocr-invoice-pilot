"""Tests for SheetsWriter (CSV fallback mode)."""
import sys
import csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.sheets_writer import SheetsWriter

DUMMY_RESULT = {
    "filename": "test_invoice.png",
    "status": "success",
    "confidence": 87.5,
    "needs_review": False,
    "fields": {
        "vendor_name": "Test Corp Ltd",
        "invoice_number": "INV-2025-9999",
        "invoice_date": "2025-03-15",
        "due_date": "2025-04-14",
        "subtotal": "$1,000.00",
        "tax": "$150.00",
        "total_amount": "$1,150.00",
    },
}


def test_csv_fallback(tmp_path):
    writer = SheetsWriter()
    csv_path = tmp_path / "test_output.csv"
    result = writer._fallback_to_csv(DUMMY_RESULT, str(csv_path))
    assert result is True
    assert csv_path.exists()
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + 1 data row
    assert "Test Corp Ltd" in rows[1]


def test_csv_fallback_header(tmp_path):
    writer = SheetsWriter()
    csv_path = tmp_path / "test_output2.csv"
    writer._fallback_to_csv(DUMMY_RESULT, str(csv_path))
    writer._fallback_to_csv(DUMMY_RESULT, str(csv_path))
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + 2 data rows (no duplicate headers)


def test_connect_without_credentials():
    writer = SheetsWriter(credentials_file="nonexistent_creds.json")
    connected = writer.connect()
    assert connected is False


def test_get_summary_no_data(tmp_path):
    writer = SheetsWriter()
    writer._fallback_csv = tmp_path / "empty.csv"
    summary = writer.get_summary()
    assert summary["total_rows"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
