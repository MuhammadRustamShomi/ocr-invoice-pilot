# Quick Start — OCR Invoice Pilot

Get up and running in 5 steps (under 5 minutes).

## Step 1 — Open the project folder

```
cd C:\Users\Hp\ocr-invoice-pilot
```

## Step 2 — Start all services

Double-click **scripts\start_all.bat** or run:

```
scripts\start_all.bat
```

Two command windows open:
- **OCR API** — listening at http://127.0.0.1:8000
- **Invoice Watcher** — monitoring the `inbox\` folder

## Step 3 — (Optional) Open the dashboard

In a third terminal:

```
venv\Scripts\activate
streamlit run dashboard\app.py
```

Dashboard opens at http://localhost:8501

## Step 4 — Process an invoice

Copy or drag any invoice image (PNG, JPG) or PDF into the `inbox\` folder.

The watcher detects it automatically, sends it to the API, and:
- Moves the file to `processed\` on success
- Moves the file to `failed\` if it could not be processed

## Step 5 — View results

- **Google Sheets** — open your "OCR Invoice Results" sheet
- **CSV fallback** — open `output_fallback.csv` if Sheets is not configured
- **Dashboard** — http://localhost:8501 shows live metrics

---

**Stop all services:** Run `scripts\stop_all.bat`

**API docs:** http://127.0.0.1:8000/docs

**Logs:** `logs\ocr_pilot.log`
