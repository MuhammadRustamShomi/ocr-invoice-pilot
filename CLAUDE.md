# CLAUDE.md — OCR Pilot Sprint (Invoice Processing Automation)
# ============================================================
# Claude Code: Read this entire file before writing a single line of code.
# Work through every phase in order. Never skip a step.
# Do NOT ask the user questions — all decisions are made here.
# ============================================================

## PROJECT IDENTITY
- **Project Name:** ocr-invoice-pilot
- **Goal:** Automatically extract data from invoice images/PDFs and push to Google Sheets
- **Timeline:** 15 working days (3 sprints of 5 days each)
- **Platform:** Windows (Python 3.9+ only — NO Docker, NO Git required)
- **Output:** Google Sheets via API
- **Samples:** Generate dummy invoice images programmatically

---

## ENVIRONMENT FACTS (Windows-specific)
- Use `python` not `python3`
- Use `pip` not `pip3`
- Use backslash `\` for folder creation commands in Windows CLI
- Use `type nul >` to create empty files on Windows
- Virtual environment activation: `venv\Scripts\activate`
- Path separator in Python code: use `os.path.join()` or `pathlib.Path`
- Line endings: use `\r\n` awareness in file writing
- Never use `sudo` — this is Windows

---

## ABSOLUTE RULES FOR CLAUDE CODE
1. **Never stop and ask the user a question.** All answers are in this file.
2. **Never skip a phase.** Complete each phase fully before moving to the next.
3. **Always run tests after each module is built.** Fix failures before continuing.
4. **Always print progress messages** so the user can see what is happening.
5. **If a library install fails**, try `pip install --upgrade pip` first, then retry.
6. **If Google Sheets API fails**, write to local CSV as fallback and log the error.
7. **Generate all sample data programmatically** — do not ask the user to provide files.
8. **Every Python file must have a `if __name__ == "__main__":` block** for standalone testing.
9. **Use relative paths everywhere** — never hardcode `C:\Users\...` paths.
10. **Log everything** to `logs\ocr_pilot.log` with timestamps.

---

## PROJECT FOLDER STRUCTURE
Create exactly this structure at the start of Phase 1:

```
ocr-invoice-pilot\
│
├── CLAUDE.md                    ← This file (copy here)
├── .env                         ← API keys and config (never commit)
├── .env.example                 ← Template without real values
├── requirements.txt             ← All dependencies
├── README.md                    ← Setup and usage instructions
│
├── core\
│   ├── __init__.py
│   ├── ocr_engine.py            ← EasyOCR wrapper + preprocessing
│   ├── field_extractor.py       ← Regex + heuristic field extraction
│   ├── confidence_scorer.py     ← Score and flag low-confidence results
│   └── sheets_writer.py         ← Google Sheets API integration
│
├── api\
│   ├── __init__.py
│   └── main.py                  ← FastAPI app with /extract endpoint
│
├── watcher\
│   ├── __init__.py
│   └── folder_watcher.py        ← Watchdog-based folder monitor
│
├── samples\
│   ├── generate_samples.py      ← Script to create dummy invoice images
│   └── invoices\                ← Generated sample invoices go here
│       └── .gitkeep
│
├── inbox\                       ← Drop invoices here for processing
│   └── .gitkeep
│
├── processed\                   ← Successfully processed invoices move here
│   └── .gitkeep
│
├── failed\                      ← Failed invoices move here
│   └── .gitkeep
│
├── logs\
│   └── .gitkeep
│
├── tests\
│   ├── __init__.py
│   ├── test_ocr_engine.py
│   ├── test_field_extractor.py
│   └── test_sheets_writer.py
│
└── dashboard\
    └── app.py                   ← Streamlit monitoring dashboard
```

---

## PHASE 1 — BUILD (Days 1–5)
### Goal: Working FastAPI OCR endpoint + sample invoice generator

---

### DAY 1 — Project Setup

**Step 1: Create project folder and virtual environment**
```
mkdir ocr-invoice-pilot
cd ocr-invoice-pilot
python -m venv venv
venv\Scripts\activate
```

**Step 2: Create requirements.txt with exactly these contents:**
```
fastapi==0.111.0
uvicorn==0.30.1
easyocr==1.7.1
Pillow==10.3.0
opencv-python-headless==4.9.0.80
numpy==1.26.4
python-multipart==0.0.9
watchdog==4.0.1
pdf2image==1.17.0
PyMuPDF==1.24.3
python-dotenv==1.0.1
gspread==6.1.2
google-auth==2.29.0
google-auth-oauthlib==1.2.0
reportlab==4.2.0
pytest==8.2.0
httpx==0.27.0
streamlit==1.35.0
loguru==0.7.2
colorama==0.4.6
requests==2.32.3
```

**Step 3: Install all dependencies**
```
pip install --upgrade pip
pip install -r requirements.txt
```

**Step 4: Create folder structure**
Run this Python script to create all folders and empty files:

```python
# setup_project.py
import os
from pathlib import Path

folders = [
    "core", "api", "watcher", "samples/invoices",
    "inbox", "processed", "failed", "logs", "tests", "dashboard"
]

files = [
    "core/__init__.py", "core/ocr_engine.py", "core/field_extractor.py",
    "core/confidence_scorer.py", "core/sheets_writer.py",
    "api/__init__.py", "api/main.py",
    "watcher/__init__.py", "watcher/folder_watcher.py",
    "samples/generate_samples.py",
    "tests/__init__.py", "tests/test_ocr_engine.py",
    "tests/test_field_extractor.py", "tests/test_sheets_writer.py",
    "dashboard/app.py",
    "samples/invoices/.gitkeep", "inbox/.gitkeep",
    "processed/.gitkeep", "failed/.gitkeep", "logs/.gitkeep"
]

for folder in folders:
    Path(folder).mkdir(parents=True, exist_ok=True)
    print(f"Created folder: {folder}")

for f in files:
    Path(f).touch()
    print(f"Created file: {f}")

print("\nProject structure ready!")
```

**Step 5: Create .env and .env.example**

`.env` contents:
```
# Google Sheets
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_SHEET_NAME=OCR Invoice Results
GOOGLE_SHEET_ID=

# API
API_HOST=127.0.0.1
API_PORT=8000
API_KEY=ocr-pilot-key-2026

# Processing
CONFIDENCE_THRESHOLD=70
MAX_RETRIES=3
INBOX_FOLDER=inbox
PROCESSED_FOLDER=processed
FAILED_FOLDER=failed
LOG_FILE=logs/ocr_pilot.log
```

`.env.example` — same as above but with empty values for sensitive fields.

**Step 6: Create README.md** with setup steps, how to run the watcher, how to use the API, and how to open the dashboard.

**Day 1 verification:** Run `python setup_project.py` — all folders and files must exist with no errors.

---

### DAY 2 — Generate Dummy Invoices + Core OCR Module

**Step 1: Build samples\generate_samples.py**

This script must generate 25 realistic dummy invoice PNG images using ReportLab.
Each invoice must randomly vary:
- Vendor name (pick from list of 10 company names)
- Invoice number (format: INV-YYYY-XXXX)
- Invoice date (random dates in 2025–2026)
- Line items (2–5 random items with qty, unit price, total)
- Subtotal, tax (15%), grand total
- Due date (30 days after invoice date)
- Some invoices should have slightly rotated text (±2 degrees) to simulate scan artifacts
- Some should have slight noise/blur to test preprocessing

Generate invoices in these formats:
- 15 clean PNG invoices (easy)
- 5 slightly rotated PNG invoices (medium)
- 5 noisy/blurred PNG invoices (hard)

Save all 25 to `samples\invoices\` with names: `invoice_001.png` through `invoice_025.png`
Also save a `samples\invoices\manifest.json` with ground truth data for each invoice (for accuracy testing).

**Step 2: Build core\ocr_engine.py**

Must contain:
```python
class OCREngine:
    def __init__(self, languages=['en'], gpu=False)
    def preprocess_image(self, image_path: str) -> np.ndarray
        # Steps: load → convert to grayscale → deskew → denoise → increase contrast
    def extract_text(self, image_path: str) -> dict
        # Returns: {"raw_text": str, "blocks": list, "confidence": float, "processing_time": float}
    def extract_from_pdf(self, pdf_path: str) -> list[dict]
        # Converts each PDF page to image, runs extract_text, returns list of page results
    def _deskew(self, image: np.ndarray) -> np.ndarray
    def _denoise(self, image: np.ndarray) -> np.ndarray
    def _increase_contrast(self, image: np.ndarray) -> np.ndarray
```

Preprocessing pipeline order: grayscale → deskew → denoise → contrast boost → return

**Step 3: Run first accuracy test**
Test OCREngine on all 25 sample invoices.
Print accuracy summary: average confidence, min, max, how many > 70% threshold.

**Day 2 verification:**
- 25 invoice images exist in `samples\invoices\`
- `manifest.json` exists with ground truth
- OCREngine processes all 25 without crashing
- Average confidence > 60% on clean invoices

---

### DAY 3 — FastAPI Endpoint

**Build api\main.py with these endpoints:**

```
POST /extract
  - Accepts: multipart/form-data with field "file" (image or PDF)
  - Header: X-API-Key (must match API_KEY in .env)
  - Returns: JSON with extracted fields + confidence + processing_time
  - On error: returns {"error": "description", "status": "failed"}

GET /health
  - Returns: {"status": "ok", "version": "1.0.0", "timestamp": ISO string}

GET /stats
  - Returns: {"total_processed": int, "success_rate": float, "avg_confidence": float}
  - Read stats from logs\stats.json (create if not exists)

POST /extract-batch
  - Accepts: JSON list of base64-encoded images
  - Processes each, returns list of results
  - Max 10 images per batch
```

Response schema for /extract:
```json
{
  "status": "success",
  "filename": "invoice_001.png",
  "fields": {
    "vendor_name": "string or null",
    "invoice_number": "string or null",
    "invoice_date": "string or null",
    "due_date": "string or null",
    "line_items": [{"description": "", "qty": 0, "unit_price": 0, "total": 0}],
    "subtotal": "string or null",
    "tax": "string or null",
    "total_amount": "string or null"
  },
  "confidence": 0.0,
  "low_confidence_fields": ["list of field names below threshold"],
  "processing_time_seconds": 0.0,
  "needs_review": false
}
```

**API key middleware:** Reject requests without correct X-API-Key header with 401.

**Run the API:**
```
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

**Day 3 verification:**
- `GET /health` returns 200
- `POST /extract` with a sample invoice returns valid JSON
- `POST /extract` without API key returns 401
- FastAPI docs available at `http://127.0.0.1:8000/docs`

---

### DAY 4 — Field Extraction Engine

**Build core\field_extractor.py**

The FieldExtractor class must extract structured fields from raw OCR text using regex + heuristics.

```python
class FieldExtractor:
    def extract_all(self, raw_text: str) -> dict
        # Calls all extract_ methods, returns combined dict
    
    def extract_vendor_name(self, raw_text: str) -> str | None
        # Heuristic: First non-empty line, or line containing "Ltd", "LLC", "Inc", "Corp", "Co."
    
    def extract_invoice_number(self, raw_text: str) -> str | None
        # Regex patterns: INV-\d+, Invoice #\d+, Invoice No[.: ]\w+, #\d{4,}
    
    def extract_date(self, raw_text: str) -> str | None
        # Patterns: DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY, Month DD YYYY, DD Month YYYY
        # Label keywords: "Date:", "Invoice Date:", "Issued:"
    
    def extract_due_date(self, raw_text: str) -> str | None
        # Label keywords: "Due Date:", "Payment Due:", "Due By:"
    
    def extract_total(self, raw_text: str) -> str | None
        # Label keywords: "Total:", "Grand Total:", "Amount Due:", "Total Due:"
        # Extract the currency amount on the same line or next line
    
    def extract_tax(self, raw_text: str) -> str | None
        # Label keywords: "Tax:", "VAT:", "GST:", "Tax Amount:"
    
    def extract_subtotal(self, raw_text: str) -> str | None
        # Label keywords: "Subtotal:", "Sub Total:", "Net Amount:"
    
    def extract_line_items(self, raw_text: str) -> list[dict]
        # Look for table-like structure: lines with multiple numbers
        # Each item: {"description": str, "qty": float, "unit_price": float, "total": float}
        # Return empty list if no items found (never return None)
    
    def _extract_currency_amount(self, text: str) -> str | None
        # Extract number like: $1,234.56 or 1234.56 or 1,234
    
    def _normalize_date(self, date_str: str) -> str | None
        # Convert any date format to YYYY-MM-DD standard
```

**Build core\confidence_scorer.py**

```python
class ConfidenceScorer:
    def score_extraction(self, fields: dict, ocr_confidence: float) -> dict
        # Returns: {"overall": float, "field_scores": {field: float}, 
        #           "low_confidence_fields": [str], "needs_review": bool}
    
    def _score_field(self, field_name: str, value) -> float
        # Score each field 0-100 based on:
        # - Not None: +40 points
        # - Passes format validation: +30 points  
        # - Consistent with other fields (e.g., subtotal + tax ≈ total): +30 points
```

**Day 4 verification:**
- Run FieldExtractor on all 25 sample invoices
- Print extraction report: how many invoices have each field correctly extracted
- Target: vendor_name > 80%, invoice_number > 85%, total > 80%

---

### DAY 5 — Google Sheets Integration + Week 1 Summary

**Step 1: Build core\sheets_writer.py**

```python
class SheetsWriter:
    def __init__(self, credentials_file: str, sheet_name: str)
    
    def connect(self) -> bool
        # Authenticate using service account credentials
        # Return True if connected, False if failed
    
    def ensure_sheet_exists(self) -> None
        # Check if sheet exists, create it if not
        # Set up headers on first row if sheet is empty
    
    def write_result(self, result: dict) -> bool
        # Append one row to the sheet with all extracted fields + metadata
        # Columns: Timestamp, Filename, Vendor, Invoice No, Date, Due Date,
        #          Subtotal, Tax, Total, Confidence, Needs Review, Status
    
    def write_batch(self, results: list[dict]) -> int
        # Write multiple rows at once, return count of successful writes
    
    def get_summary(self) -> dict
        # Read sheet and return: total rows, avg confidence, needs_review count
    
    def _fallback_to_csv(self, result: dict, csv_path: str = "output_fallback.csv") -> bool
        # If Sheets API fails, write to CSV instead
        # Always return True (CSV should not fail)
```

**Google Sheets Setup Instructions** (print these to console when sheets_writer.py runs for first time):
```
GOOGLE SHEETS SETUP — Do this once:
1. Go to https://console.cloud.google.com
2. Create a new project called "ocr-invoice-pilot"
3. Enable "Google Sheets API" and "Google Drive API"
4. Create a Service Account → Download JSON key → save as credentials.json in project root
5. Open Google Sheets → Create sheet named "OCR Invoice Results"
6. Share the sheet with the service account email (from credentials.json "client_email" field)
7. Copy the Sheet ID from the URL and paste into .env as GOOGLE_SHEET_ID
8. Run: python core/sheets_writer.py to test connection
```

**If credentials.json does not exist:** SheetsWriter must fall back to CSV automatically and print a clear message explaining what the user needs to do. Never crash.

**Step 2: Integrate SheetsWriter into api\main.py**
- After successful extraction, write result to Sheets (or CSV fallback)
- Add `"sheet_written": true/false` to API response

**Step 3: Week 1 Summary Script**
Create `tests\week1_summary.py`:
- Process all 25 sample invoices through the full pipeline
- Print accuracy report for each field
- Print average processing time
- Print Google Sheets row count
- Save summary to `logs\week1_summary.json`

**Day 5 verification:**
- `python tests\week1_summary.py` runs without errors
- Google Sheets (or CSV fallback) has 25 rows of data
- Overall field extraction accuracy > 80% on clean invoices
- Print "WEEK 1 COMPLETE ✅" on success

---

## PHASE 2 — AUTOMATE (Days 6–10)
### Goal: Zero-touch pipeline — drop invoice, data appears in Google Sheets

---

### DAY 6 — Folder Watcher

**Build watcher\folder_watcher.py**

```python
class InvoiceWatcher:
    def __init__(self, inbox: str, processed: str, failed: str, api_url: str, api_key: str)
    
    def start(self) -> None
        # Start watching inbox folder
        # Print: "Watching [inbox] for new invoices... Press Ctrl+C to stop"
    
    def stop(self) -> None
    
    def on_new_file(self, file_path: str) -> None
        # Called when new file detected
        # 1. Wait 500ms (file might still be writing)
        # 2. Validate file type (png, jpg, jpeg, pdf only)
        # 3. Send to API /extract endpoint
        # 4. If success: move to processed\, log result
        # 5. If failed: move to failed\, log error
        # 6. Print result summary to console
    
    def _send_to_api(self, file_path: str) -> dict | None
        # POST file to http://localhost:8000/extract
        # Include X-API-Key header
        # Return parsed JSON or None on error
    
    def _move_file(self, src: str, dest_folder: str) -> str
        # Move file, handle name conflicts with timestamp suffix
```

**Create watcher\run_watcher.py** — simple script to start the watcher:
```python
# Usage: python watcher/run_watcher.py
# This runs forever until Ctrl+C
```

**Day 6 verification:**
- Start the watcher in one terminal: `python watcher\run_watcher.py`
- Start the API in another terminal: `uvicorn api.main:app --port 8000`
- Copy a sample invoice to `inbox\`
- Watcher detects it, processes it, moves it to `processed\`
- Row appears in Google Sheets (or CSV fallback)

---

### DAY 7 — PDF Support

**Enhance core\ocr_engine.py:**
- Use PyMuPDF (fitz) for PDF → image conversion (preferred over pdf2image, no poppler needed)
- Process each page separately
- For multi-page PDFs: extract fields from all pages, merge intelligently
  - Vendor, Invoice No, Date: from page 1
  - Line items: from ALL pages (concatenated)
  - Total: from LAST page containing "Total" keyword

**Generate 5 dummy PDF invoices** in `samples\generate_samples.py`:
- Add `generate_pdf_invoices(count=5)` function using ReportLab
- Save as `invoice_pdf_001.pdf` through `invoice_pdf_005.pdf`
- Add to manifest.json

**Update watcher** to handle .pdf files.

**Day 7 verification:**
- Copy a PDF invoice to `inbox\`
- Watcher processes it correctly
- All pages are read
- Result in Sheets/CSV

---

### DAY 8 — Output Hardening

**Enhance core\sheets_writer.py:**
- Add duplicate detection: before writing, check if invoice_number already exists in sheet
  - If duplicate: update existing row instead of adding new one
  - Log: "Duplicate detected: INV-2026-0042 — updating existing row"
- Add a "Processed At" timestamp column
- Add a "Source File" column with original filename

**Create logs\stats.json updater:**
After every processed invoice, update `logs\stats.json`:
```json
{
  "total_processed": 0,
  "total_success": 0,
  "total_failed": 0,
  "total_needs_review": 0,
  "avg_confidence": 0.0,
  "avg_processing_time": 0.0,
  "last_updated": "ISO timestamp"
}
```

**Add alert system in watcher\folder_watcher.py:**
- Track consecutive failures
- If 3 consecutive failures: print bright red warning to console
- Log all failures with full error details to `logs\ocr_pilot.log`

**Day 8 verification:**
- Process an invoice twice — second time shows "Duplicate detected" message
- `logs\stats.json` updates correctly after each invoice
- Manually corrupt an image and drop it to inbox — failure is logged and file moves to failed\

---

### DAY 9 — Retry Logic + Error Handling

**Add to watcher\folder_watcher.py:**
- Retry failed OCR up to MAX_RETRIES (from .env) times with 2-second delay
- On each retry: try different preprocessing (more aggressive denoising)
- Only move to `failed\` after all retries exhausted

**Add to core\ocr_engine.py:**
- Preprocessing fallback chain:
  1. Standard preprocessing
  2. High contrast + threshold (OTSU binarization)
  3. Upscale 2x then OCR
  4. Raw image (no preprocessing) as last resort

**Create tests\stress_test.py:**
- Copy all 25 sample invoices to inbox simultaneously
- Measure: all processed within 5 minutes, no crashes, correct Sheets rows
- Print stress test report

**Day 9 verification:**
- Run stress test: `python tests\stress_test.py`
- All 25 processed without crash
- Failed folder only contains genuinely unreadable files

---

### DAY 10 — Full Pipeline Integration Test

**Create tests\pipeline_test.py:**
- Full end-to-end test:
  1. Start API (subprocess)
  2. Start watcher (subprocess)
  3. Copy all 25 invoices to inbox
  4. Wait for processing (poll stats.json)
  5. Verify Sheets has correct row count
  6. Compare extracted fields vs manifest.json ground truth
  7. Print accuracy report per field
  8. Print PASS/FAIL for each success criterion:
     - [ ] All 25 invoices processed
     - [ ] Accuracy > 85% on vendor_name
     - [ ] Accuracy > 85% on invoice_number
     - [ ] Accuracy > 80% on total_amount
     - [ ] Average processing time < 10 seconds
     - [ ] Zero crashes
     - [ ] All rows in Google Sheets

**Day 10 verification:**
- Run `python tests\pipeline_test.py`
- All 7 criteria must PASS
- Print "WEEK 2 COMPLETE ✅" on success

---

## PHASE 3 — POLISH & GO-LIVE (Days 11–15)
### Goal: Dashboard, security, user-ready, production launch

---

### DAY 11 — Streamlit Dashboard

**Build dashboard\app.py:**

Must display:
- **Header:** "OCR Invoice Pilot — Live Dashboard"
- **Metric cards (top row):** Total Processed | Success Rate | Avg Confidence | Needs Review
- **Live table:** All processed invoices (read from Google Sheets or CSV fallback)
  - Columns: Timestamp, Vendor, Invoice No, Date, Total, Confidence, Status
  - Color-code rows: green (high confidence), yellow (needs review), red (failed)
  - Searchable by vendor name or invoice number
- **Charts:**
  - Bar chart: invoices processed per day
  - Pie chart: Success vs Needs Review vs Failed
  - Line chart: confidence score trend over time
- **Failed documents panel:** List files in failed\ folder with error reason
- **Auto-refresh:** every 30 seconds using `st.rerun()`

**Run dashboard:**
```
streamlit run dashboard\app.py
```

**Day 11 verification:**
- Dashboard opens in browser at localhost:8501
- Shows real data from previous tests
- Auto-refreshes
- Search works

---

### DAY 12 — Security Hardening

**Enhance api\main.py:**
- Rate limiting: max 60 requests per minute per IP using a simple in-memory counter
  - Return 429 Too Many Requests if exceeded
- Request size limit: reject files > 20MB with 413 error
- File type validation: check actual file magic bytes, not just extension
  - Allowed: JPEG (FF D8 FF), PNG (89 50 4E 47), PDF (25 50 44 46)
  - Reject anything else with 415 Unsupported Media Type
- Add request ID to every response (UUID4)
- Sanitize all logged filenames (strip path traversal attempts)

**Enhance .env handling:**
- At startup, validate all required .env variables exist
- Print clear error message for each missing variable
- Exit with code 1 if GOOGLE_CREDENTIALS_FILE is set but file doesn't exist

**Create api\security.py:**
- `verify_api_key(key: str) -> bool`
- `check_rate_limit(ip: str) -> bool`
- `validate_file_type(file_bytes: bytes) -> str | None`

**Day 12 verification:**
- Send request without API key → 401
- Send request with wrong content type → 415
- Send 61 requests in 1 minute → 62nd returns 429
- Send 25MB file → 413

---

### DAY 13 — User Guide + Training Materials

**Create docs\ folder with:**

**docs\USER_GUIDE.md** — must include:
- How to start the system (step by step, Windows commands)
- How to process an invoice (just drop it in the inbox\ folder)
- How to view results (Google Sheets link + dashboard URL)
- How to handle "Needs Review" invoices
- How to stop the system safely
- Common problems and solutions (FAQ section with 10 Q&As)
- Screenshots placeholders with descriptions

**docs\QUICK_START.md** — one-page version:
- 5 steps to get the system running
- Should take < 5 minutes to follow

**Create scripts\start_all.bat** — Windows batch file:
```batch
@echo off
echo Starting OCR Invoice Pilot...
echo.
echo [1/3] Activating virtual environment...
call venv\Scripts\activate
echo.
echo [2/3] Starting OCR API on port 8000...
start "OCR API" cmd /k uvicorn api.main:app --host 127.0.0.1 --port 8000
timeout /t 3 /nobreak > nul
echo.
echo [3/3] Starting Invoice Watcher...
start "Invoice Watcher" cmd /k python watcher\run_watcher.py
echo.
echo All services started!
echo  - API:       http://127.0.0.1:8000
echo  - API Docs:  http://127.0.0.1:8000/docs
echo  - Dashboard: Run "streamlit run dashboard\app.py" separately
echo.
pause
```

**Create scripts\stop_all.bat:**
```batch
@echo off
echo Stopping OCR Invoice Pilot...
taskkill /f /im uvicorn.exe 2>nul
taskkill /f /fi "WINDOWTITLE eq Invoice Watcher" 2>nul
echo Done. All services stopped.
pause
```

**Day 13 verification:**
- Run `scripts\start_all.bat` — two windows open (API + Watcher)
- All content in USER_GUIDE.md is accurate and testable
- A non-technical user could follow QUICK_START.md without help

---

### DAY 14 — User Acceptance Testing (UAT)

**Create tests\uat_test.py:**

Simulates a real user running the system for the first time:

**Test Scenario 1 — Happy Path:**
- Start API and watcher
- Drop invoice_001.png into inbox
- Wait for processing
- Verify row appears in Sheets with correct vendor and total
- PASS/FAIL

**Test Scenario 2 — PDF Invoice:**
- Drop a PDF invoice into inbox
- Verify processed correctly
- PASS/FAIL

**Test Scenario 3 — Bad File:**
- Drop a .txt file into inbox
- Verify it moves to failed\ with appropriate error
- PASS/FAIL

**Test Scenario 4 — Duplicate Invoice:**
- Drop same invoice twice
- Verify only one Sheets row (updated, not duplicated)
- PASS/FAIL

**Test Scenario 5 — Low Quality Invoice:**
- Drop a noisy invoice (from samples)
- Verify confidence score is low and needs_review=True
- PASS/FAIL

**Test Scenario 6 — API Direct Call:**
- POST to /extract with valid invoice and API key
- Verify response schema matches spec
- PASS/FAIL

**Test Scenario 7 — Security:**
- POST without API key → must return 401
- PASS/FAIL

Print final UAT report:
```
UAT RESULTS — Day 14
====================
Scenario 1 (Happy Path):        PASS ✅
Scenario 2 (PDF):               PASS ✅
Scenario 3 (Bad File):          PASS ✅
Scenario 4 (Duplicate):         PASS ✅
Scenario 5 (Low Quality):       PASS ✅
Scenario 6 (API Direct):        PASS ✅
Scenario 7 (Security):          PASS ✅

Overall: 7/7 PASSED — READY FOR GO-LIVE ✅
```

If any test FAILS: fix the issue before moving to Day 15. Do not skip.

---

### DAY 15 — GO LIVE 🚀

**Step 1: Final cleanup**
- Remove all test files from inbox\, processed\, failed\
- Clear logs\ (archive to logs\archive\)
- Reset stats.json to zeros
- Verify .env has correct production values

**Step 2: Run production smoke test**
- Start all services via `scripts\start_all.bat`
- Process 3 real (or sample) invoices
- Confirm all appear in Google Sheets
- Open dashboard and verify metrics show correctly

**Step 3: Generate Go-Live Report**
Create `logs\golive_report.json`:
```json
{
  "go_live_date": "ISO timestamp",
  "system_version": "1.0.0",
  "pilot_use_case": "Invoice Processing Automation",
  "services": {
    "api": "http://127.0.0.1:8000",
    "dashboard": "http://localhost:8501",
    "watcher": "watching inbox/"
  },
  "test_results": {
    "week1_accuracy": 0.0,
    "week2_pipeline_tests": "7/7 passed",
    "uat_scenarios": "7/7 passed"
  },
  "output_destination": "Google Sheets: OCR Invoice Results",
  "sample_invoices_processed": 25,
  "status": "LIVE"
}
```

**Step 4: Print go-live banner**
```
╔══════════════════════════════════════════════╗
║   🚀 OCR INVOICE PILOT — LIVE IN PRODUCTION  ║
║                                              ║
║   API:        http://127.0.0.1:8000          ║
║   Dashboard:  http://localhost:8501          ║
║   Output:     Google Sheets                 ║
║   Status:     ✅ ALL SYSTEMS GO              ║
║                                              ║
║   Drop invoices into inbox\ to process      ║
╚══════════════════════════════════════════════╝
```

**Day 15 verification:**
- Go-live banner printed
- 3 invoices processed in production run
- Google Sheets has correct data
- Dashboard shows live metrics
- Print "SPRINT COMPLETE — DAY 15 DONE 🏆"

---

## SUCCESS CRITERIA SUMMARY
Claude Code must not consider the project done until ALL of these pass:

| # | Criterion | Target |
|---|-----------|--------|
| 1 | OCR Accuracy (vendor_name) | > 85% |
| 2 | OCR Accuracy (invoice_number) | > 85% |
| 3 | OCR Accuracy (total_amount) | > 80% |
| 4 | Processing Speed | < 10 seconds/invoice |
| 5 | Pipeline: inbox → Sheets | Zero human steps |
| 6 | UAT Scenarios | 7/7 PASS |
| 7 | API Security | Key auth + rate limit working |
| 8 | Dashboard | Live, auto-refresh, searchable |
| 9 | Start script | `scripts\start_all.bat` works |
| 10 | No crashes in stress test (25 invoices) | 0 crashes |

---

## DEPENDENCY RESOLUTION (if installs fail)

| Package | If it fails | Alternative |
|---------|-------------|-------------|
| easyocr | Try: `pip install easyocr --no-deps` then deps separately | pytesseract |
| opencv-python-headless | Try: `pip install opencv-python` instead | - |
| PyMuPDF | Try: `pip install pymupdf` (lowercase) | pdf2image + poppler |
| gspread | Should always work | - |
| reportlab | Should always work | - |

**If easyocr model download fails** (needs internet):
- EasyOCR downloads models on first run (~100MB)
- If behind proxy: set `HTTP_PROXY` and `HTTPS_PROXY` env vars
- Models cache to `C:\Users\<user>\.EasyOCR\` — do not delete

---

## LOGGING STANDARD
Every module must use loguru for logging:
```python
from loguru import logger
import os
from dotenv import load_dotenv
load_dotenv()

logger.add(
    os.getenv("LOG_FILE", "logs/ocr_pilot.log"),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}"
)
```

Log levels to use:
- `logger.info()` — normal operations (file detected, invoice processed)
- `logger.warning()` — low confidence, duplicate detected, fallback used
- `logger.error()` — OCR failed, API error, file move failed
- `logger.success()` — day complete, test passed, go-live achieved

---

## WHAT TO DO IF STUCK

1. **EasyOCR accuracy is low** → Increase preprocessing aggressiveness in `_increase_contrast`. Try OTSU binarization.
2. **Google Sheets auth fails** → Fall back to CSV. Print exact setup steps. Continue.
3. **Regex misses fields** → Add more pattern variants. Test on the specific failing invoice.
4. **API is slow** → EasyOCR loads model on first call. Warm it up at startup in a background thread.
5. **Watcher misses files** → Add 1-second poll interval as fallback alongside event-based watching.
6. **PDF pages not reading** → Check PyMuPDF version. Use `fitz.open()` not `fitz.Document()`.

---

*This CLAUDE.md was generated for the OCR Invoice Pilot Sprint.*
*Start date: April 22, 2026. Target go-live: May 10, 2026.*
*Do not modify this file during the sprint — it is the source of truth.*
