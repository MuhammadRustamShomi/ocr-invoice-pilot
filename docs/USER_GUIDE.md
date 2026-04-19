# User Guide — OCR Invoice Pilot

## Overview

This system automatically extracts data from invoice images and PDFs, then writes
the results to Google Sheets (or a local CSV if Sheets is not configured).

---

## How to Start the System

### Prerequisites
- Python 3.9+ installed
- Virtual environment set up (`venv\Scripts\activate`)
- Dependencies installed (`pip install -r requirements.txt`)

### Start all services (Windows)

```
scripts\start_all.bat
```

This opens two windows:
1. **OCR API** — REST API server on port 8000
2. **Invoice Watcher** — monitors `inbox\` for new files

### Start the dashboard (optional)

```
venv\Scripts\activate
streamlit run dashboard\app.py
```

Opens at http://localhost:8501

---

## How to Process an Invoice

**Just drop the file into the `inbox\` folder.**

Supported formats: `.png`, `.jpg`, `.jpeg`, `.pdf`

The watcher detects the file within 1–2 seconds and:
1. Sends it to the OCR API
2. Extracts: vendor name, invoice number, date, due date, line items, subtotal, tax, total
3. Writes results to Google Sheets (or `output_fallback.csv`)
4. Moves the file to `processed\` on success, or `failed\` on error
5. Prints a summary to the console

---

## How to View Results

### Google Sheets
Open the "OCR Invoice Results" Google Sheet. Each processed invoice adds one row.

### CSV Fallback
If Google Sheets is not configured, results are saved to `output_fallback.csv`.

### Dashboard
Visit http://localhost:8501 for live metrics, charts, and a searchable results table.

---

## How to Handle "Needs Review" Invoices

Invoices flagged as "Needs Review" have low extraction confidence.
The `Needs Review` column in Sheets shows "Yes" and they appear highlighted yellow in the dashboard.

To review:
1. Check the original file in `processed\`
2. Compare extracted fields against the actual invoice
3. Manually correct any wrong values in Google Sheets

---

## How to Stop the System Safely

Run `scripts\stop_all.bat` or close the two command windows.

No data is lost — all processed results are already in Sheets/CSV.

---

## Common Problems and Solutions (FAQ)

**Q1: The watcher says "Cannot connect to API"**
A: Make sure the API is running first. Run `scripts\start_all.bat` or start uvicorn manually.

**Q2: Invoice moved to `failed\` with no error message**
A: Check `logs\ocr_pilot.log` for the full error. Common causes: corrupt file, unsupported format, API timeout.

**Q3: Google Sheets not updating**
A: Check that `credentials.json` exists and `GOOGLE_SHEET_ID` is set in `.env`.
Verify the sheet is shared with the service account email. The system falls back to CSV automatically.

**Q4: Extraction accuracy is low for some invoices**
A: Noisy or low-resolution scans reduce accuracy. Try rescanning at 150+ DPI. Clean, digital PDFs give best results.

**Q5: API returns 401 Unauthorized**
A: Include the `X-API-Key` header in your request. The key is set in `.env` as `API_KEY`.

**Q6: API returns 429 Too Many Requests**
A: You've hit the 60 requests/minute rate limit per IP. Wait 60 seconds and retry.

**Q7: Processing is slow**
A: EasyOCR runs on CPU — each invoice takes 15–30 seconds. A GPU reduces this to under 5 seconds.
The first invoice after startup is slower (model loading). Subsequent ones are faster.

**Q8: PDF pages are not all being read**
A: Multi-page PDFs are fully supported. All pages are processed. Line items are collected from all pages; header fields come from page 1.

**Q9: Duplicate invoice detected**
A: If the same invoice number is processed twice, the existing Sheets row is updated (not duplicated). This is expected behavior.

**Q10: Dashboard shows no data**
A: Ensure at least one invoice has been processed. If using CSV fallback, confirm `output_fallback.csv` exists.

---

## Screenshots

*[Screenshot placeholder: Dashboard with live metrics]*
*[Screenshot placeholder: Google Sheets with extracted invoice data]*
*[Screenshot placeholder: Console output showing successful processing]*

---

## Folder Reference

| Folder | Purpose |
|--------|---------|
| `inbox\` | Drop invoices here for processing |
| `processed\` | Successfully processed invoices |
| `failed\` | Invoices that could not be processed |
| `logs\` | Application logs and stats |
| `samples\invoices\` | Generated test invoices |
