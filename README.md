# OCR Invoice Pilot

Automatically extract data from invoice images/PDFs and push to Google Sheets.

## Setup

### 1. Create and activate virtual environment
```
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies
```
pip install -r requirements.txt
```

### 3. Configure environment
Copy `.env.example` to `.env` and fill in your values:
- `GOOGLE_CREDENTIALS_FILE` — path to your Google service account JSON
- `GOOGLE_SHEET_ID` — ID from your Google Sheet URL
- `API_KEY` — secret key for API authentication

### 4. Google Sheets Setup (one-time)
1. Go to https://console.cloud.google.com
2. Create project "ocr-invoice-pilot"
3. Enable Google Sheets API and Google Drive API
4. Create Service Account → download JSON → save as `credentials.json`
5. Create Google Sheet named "OCR Invoice Results"
6. Share sheet with the service account email
7. Copy Sheet ID into `.env`

### 5. Generate sample invoices
```
python samples\generate_samples.py
```

## Running the System

### Start API server
```
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

### Start folder watcher
```
python watcher\run_watcher.py
```

### Start dashboard
```
streamlit run dashboard\app.py
```

### Start everything at once (Windows)
```
scripts\start_all.bat
```

## Usage

Drop invoice images (PNG, JPG) or PDFs into the `inbox\` folder.
The watcher automatically processes them and writes results to Google Sheets.

## API Endpoints

- `GET  /health` — Service health check
- `GET  /stats` — Processing statistics
- `POST /extract` — Extract fields from invoice (requires X-API-Key header)
- `POST /extract-batch` — Process up to 10 invoices at once

## Project Structure

```
ocr-invoice-pilot\
├── core\           OCR engine, field extractor, sheets writer
├── api\            FastAPI REST API
├── watcher\        Folder monitoring service
├── samples\        Sample invoice generator
├── tests\          Test suite
├── dashboard\      Streamlit monitoring UI
├── inbox\          Drop invoices here
├── processed\      Successfully processed invoices
├── failed\         Failed invoices
└── logs\           Application logs
```
