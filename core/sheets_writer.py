"""
Sheets Writer — writes OCR extraction results to Google Sheets (or CSV fallback).
"""
import os
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger
from dotenv import load_dotenv

load_dotenv()

SETUP_INSTRUCTIONS = """
╔══════════════════════════════════════════════════════════════╗
║            GOOGLE SHEETS SETUP — Do this once               ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Go to https://console.cloud.google.com                   ║
║ 2. Create project "ocr-invoice-pilot"                       ║
║ 3. Enable "Google Sheets API" and "Google Drive API"        ║
║ 4. Create Service Account → Download JSON → save as         ║
║    credentials.json in project root                         ║
║ 5. Create Google Sheet named "OCR Invoice Results"          ║
║ 6. Share sheet with service account email (client_email)    ║
║ 7. Copy Sheet ID from URL → paste into .env GOOGLE_SHEET_ID ║
║ 8. Run: python core/sheets_writer.py                        ║
╚══════════════════════════════════════════════════════════════╝
"""

SHEET_HEADERS = [
    "Timestamp", "Filename", "Vendor", "Invoice No", "Invoice Date",
    "Due Date", "Subtotal", "Tax", "Total", "Confidence",
    "Needs Review", "Status", "Processed At", "Source File",
]


class SheetsWriter:
    def __init__(self, credentials_file: str = None, sheet_name: str = None):
        self.credentials_file = credentials_file or os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        self.sheet_name = sheet_name or os.getenv("GOOGLE_SHEET_NAME", "OCR Invoice Results")
        self.sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
        self._client = None
        self._sheet = None
        self._connected = False
        self._fallback_csv = Path("output_fallback.csv")

        creds_path = Path(self.credentials_file)
        if not creds_path.exists():
            print(SETUP_INSTRUCTIONS)
            logger.warning(f"credentials.json not found at {creds_path}. Will use CSV fallback.")

    def connect(self) -> bool:
        creds_path = Path(self.credentials_file)
        if not creds_path.exists():
            logger.warning("Google credentials not found — using CSV fallback.")
            self._connected = False
            return False
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
            self._client = gspread.authorize(creds)
            self.ensure_sheet_exists()
            self._connected = True
            logger.success("Connected to Google Sheets.")
            return True
        except Exception as exc:
            logger.error(f"Google Sheets connection failed: {exc}")
            self._connected = False
            return False

    def ensure_sheet_exists(self) -> None:
        try:
            if self.sheet_id:
                self._sheet = self._client.open_by_key(self.sheet_id).sheet1
            else:
                self._sheet = self._client.open(self.sheet_name).sheet1
            # Add headers if sheet is empty
            existing = self._sheet.get_all_values()
            if not existing:
                self._sheet.append_row(SHEET_HEADERS)
                logger.info("Created sheet headers.")
            elif existing[0] != SHEET_HEADERS:
                logger.warning("Sheet headers mismatch — continuing anyway.")
        except Exception as exc:
            import gspread
            logger.warning(f"Sheet not found, trying to create: {exc}")
            try:
                spreadsheet = self._client.create(self.sheet_name)
                self._sheet = spreadsheet.sheet1
                self._sheet.append_row(SHEET_HEADERS)
                logger.info(f"Created new sheet: {self.sheet_name}")
            except Exception as create_err:
                logger.error(f"Could not create sheet: {create_err}")
                self._sheet = None

    def _row_from_result(self, result: dict) -> list:
        now = datetime.now(timezone.utc).isoformat()
        fields = result.get("fields", {})
        return [
            now,
            result.get("filename", ""),
            fields.get("vendor_name", "") or "",
            fields.get("invoice_number", "") or "",
            fields.get("invoice_date", "") or "",
            fields.get("due_date", "") or "",
            fields.get("subtotal", "") or "",
            fields.get("tax", "") or "",
            fields.get("total_amount", "") or "",
            result.get("confidence", 0.0),
            "Yes" if result.get("needs_review") else "No",
            result.get("status", "success"),
            now,
            result.get("filename", ""),
        ]

    def _find_duplicate_row(self, invoice_number: str) -> Optional[int]:
        """Return 1-based row index of existing invoice_number, or None."""
        if not self._sheet or not invoice_number:
            return None
        try:
            values = self._sheet.get_all_values()
            inv_col = SHEET_HEADERS.index("Invoice No")
            for idx, row in enumerate(values[1:], start=2):  # skip header
                if len(row) > inv_col and row[inv_col] == invoice_number:
                    return idx
        except Exception as exc:
            logger.error(f"Duplicate check failed: {exc}")
        return None

    def write_result(self, result: dict) -> bool:
        row = self._row_from_result(result)
        invoice_number = result.get("fields", {}).get("invoice_number", "")

        if self._connected and self._sheet:
            try:
                dup_row = self._find_duplicate_row(invoice_number)
                if dup_row:
                    logger.warning(f"Duplicate detected: {invoice_number} — updating row {dup_row}")
                    col_count = len(SHEET_HEADERS)
                    cell_range = f"A{dup_row}:{chr(64 + col_count)}{dup_row}"
                    self._sheet.update(cell_range, [row])
                else:
                    self._sheet.append_row(row)
                    logger.info(f"Written to Sheets: {result.get('filename', '')}")
                return True
            except Exception as exc:
                logger.error(f"Sheets write failed: {exc} — falling back to CSV")
        return self._fallback_to_csv(result)

    def write_batch(self, results: list) -> int:
        count = 0
        for result in results:
            if self.write_result(result):
                count += 1
        return count

    def get_summary(self) -> dict:
        if self._connected and self._sheet:
            try:
                rows = self._sheet.get_all_values()[1:]  # skip header
                total = len(rows)
                conf_col = SHEET_HEADERS.index("Confidence")
                review_col = SHEET_HEADERS.index("Needs Review")
                confidences = []
                review_count = 0
                for row in rows:
                    if len(row) > conf_col:
                        try:
                            confidences.append(float(row[conf_col]))
                        except ValueError:
                            pass
                    if len(row) > review_col and row[review_col] == "Yes":
                        review_count += 1
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
                return {"total_rows": total, "avg_confidence": round(avg_conf, 1),
                        "needs_review_count": review_count}
            except Exception as exc:
                logger.error(f"get_summary failed: {exc}")
        # CSV fallback summary
        if self._fallback_csv.exists():
            with open(self._fallback_csv, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            return {"total_rows": len(rows), "avg_confidence": 0.0, "needs_review_count": 0}
        return {"total_rows": 0, "avg_confidence": 0.0, "needs_review_count": 0}

    def _fallback_to_csv(self, result: dict, csv_path: str = None) -> bool:
        path = Path(csv_path) if csv_path else self._fallback_csv
        row = self._row_from_result(result)
        write_header = not path.exists()
        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(SHEET_HEADERS)
                writer.writerow(row)
            logger.info(f"CSV fallback written: {path}")
            return True
        except Exception as exc:
            logger.error(f"CSV fallback failed: {exc}")
            return False


if __name__ == "__main__":
    writer = SheetsWriter()
    connected = writer.connect()
    print(f"Google Sheets connected: {connected}")
    if not connected:
        print("Running in CSV fallback mode.")

    dummy_result = {
        "filename": "test_invoice.png",
        "status": "success",
        "confidence": 87.5,
        "needs_review": False,
        "fields": {
            "vendor_name": "Acme Corp Ltd",
            "invoice_number": "INV-2025-0001",
            "invoice_date": "2025-03-15",
            "due_date": "2025-04-14",
            "subtotal": "$1,150.00",
            "tax": "$172.50",
            "total_amount": "$1,322.50",
        },
    }
    success = writer.write_result(dummy_result)
    print(f"Write result: {'OK' if success else 'FAILED'}")
    summary = writer.get_summary()
    print(f"Summary: {summary}")
    print("\nSheetsWriter test complete.")
