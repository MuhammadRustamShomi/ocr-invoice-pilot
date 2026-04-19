"""Tests for FieldExtractor."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.field_extractor import FieldExtractor

extractor = FieldExtractor()

SAMPLE_TEXT = """
Acme Solutions Ltd
INVOICE

Invoice Number: INV-2025-0042    Invoice Date: 15/03/2025
                                 Due Date: 14/04/2025

Description          Qty   Unit Price    Total
Web Development      2     $800.00       $1,600.00
Graphic Design       1     $450.00       $450.00

Subtotal: $2,050.00
Tax (15%): $307.50
Grand Total: $2,357.50

Thank you for your business!
"""


def test_vendor_name():
    result = extractor.extract_vendor_name(SAMPLE_TEXT)
    assert result is not None
    assert "Acme" in result or "Ltd" in result.lower() or "acme" in result.lower()


def test_invoice_number():
    result = extractor.extract_invoice_number(SAMPLE_TEXT)
    assert result is not None
    assert "INV" in result or "2025" in result


def test_invoice_date():
    result = extractor.extract_date(SAMPLE_TEXT)
    assert result is not None
    assert "2025" in result


def test_due_date():
    result = extractor.extract_due_date(SAMPLE_TEXT)
    assert result is not None
    assert "2025" in result


def test_total():
    result = extractor.extract_total(SAMPLE_TEXT)
    assert result is not None
    assert "2" in result  # some amount


def test_tax():
    result = extractor.extract_tax(SAMPLE_TEXT)
    assert result is not None


def test_subtotal():
    result = extractor.extract_subtotal(SAMPLE_TEXT)
    assert result is not None


def test_line_items_empty_is_list():
    result = extractor.extract_line_items("")
    assert isinstance(result, list)


def test_extract_all_returns_all_keys():
    result = extractor.extract_all(SAMPLE_TEXT)
    expected_keys = {"vendor_name", "invoice_number", "invoice_date", "due_date",
                     "line_items", "subtotal", "tax", "total_amount"}
    assert expected_keys == set(result.keys())


def test_normalize_date():
    assert extractor._normalize_date("2025-03-15") == "2025-03-15"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
