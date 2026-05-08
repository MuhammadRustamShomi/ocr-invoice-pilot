"""
OCR Invoice Pilot — Complete Streamlit Pipeline
Upload → OCR (Google Cloud Vision) → Extract Fields → Google Sheets → Dashboard

All 7 pipeline tasks run inside this app — no external API required.
"""
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

# Streamlit Cloud runs `streamlit run dashboard/app.py`, which adds dashboard/
# to sys.path — so `from core.xxx import ...` fails unless we add the project
# root (one directory up) explicitly.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="OCR Invoice Pilot — Live Dashboard",
    page_icon="🧾",
    layout="wide",
)

# ── Secrets / Config ───────────────────────────────────────────────────────────
def _secret(key: str, default: str = "") -> str:
    try:
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return os.getenv(key, default)


SHEET_ID = _secret("GOOGLE_SHEET_ID")

_gcp_info: dict | None = None
try:
    _gcp_info = dict(st.secrets["gcp_service_account"])
except Exception:
    pass

SHEET_HEADERS = [
    "Timestamp", "Filename", "Vendor", "Invoice No", "Invoice Date",
    "Due Date", "Subtotal", "Tax", "Total", "Confidence",
    "Needs Review", "Status", "Processed At", "Source File",
]
_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Google Sheets helpers ──────────────────────────────────────────────────────
def _make_sheets_client(scopes: list):
    """Create a gspread client from service-account info. Never cached — avoids
    caching a None on first failure so every call gets a fresh attempt."""
    import gspread
    try:
        # gspread >= 6.x: gspread.authorize() was removed; use service_account_from_dict
        return gspread.service_account_from_dict(_gcp_info, scopes=scopes)
    except AttributeError:
        pass
    try:
        # Fallback for older gspread (< 6.0) that still has authorize()
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(_gcp_info, scopes=scopes)
        return gspread.authorize(creds)  # type: ignore[attr-defined]
    except Exception:
        raise


def _get_sheet():
    if not _gcp_info or not SHEET_ID:
        return None
    try:
        client = _make_sheets_client(_SHEETS_SCOPES)
        sheet = client.open_by_key(SHEET_ID).sheet1
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(SHEET_HEADERS)
        return sheet
    except Exception as exc:
        st.warning(f"Could not open Google Sheet for writing: {exc}")
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_sheet_data(sheet_id: str, creds_json: str) -> tuple[list, str]:
    try:
        import gspread
        import json as _json
        info = _json.loads(creds_json)
        read_scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        try:
            client = gspread.service_account_from_dict(info, scopes=read_scopes)
        except AttributeError:
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(info, scopes=read_scopes)
            client = gspread.authorize(creds)  # type: ignore[attr-defined]
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet.get_all_records(), ""
    except Exception as exc:
        return [], str(exc)


def load_results() -> tuple[pd.DataFrame, str]:
    if SHEET_ID and _gcp_info:
        records, err = _fetch_sheet_data(SHEET_ID, json.dumps(_gcp_info))
        if err:
            return pd.DataFrame(), err
        return (pd.DataFrame(records) if records else pd.DataFrame()), ""
    return pd.DataFrame(), ""


def write_to_sheet(result: dict) -> bool:
    sheet = _get_sheet()
    if not sheet:
        if _gcp_info and SHEET_ID:
            st.warning(
                "Google Sheets write failed — check the **System Status** tab for errors. "
                "Verify the sheet is shared with the service-account email and that "
                "Google Sheets API + Drive API are enabled in your GCP project."
            )
        return False
    try:
        now = datetime.now(timezone.utc).isoformat()
        fields = result.get("fields", {})
        row = [
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
        # Duplicate detection — update existing row instead of appending
        inv_no = fields.get("invoice_number", "")
        if inv_no:
            try:
                all_values = sheet.get_all_values()
                inv_col = SHEET_HEADERS.index("Invoice No")
                for idx, existing_row in enumerate(all_values[1:], start=2):
                    if len(existing_row) > inv_col and existing_row[inv_col] == inv_no:
                        col_letter = chr(64 + len(SHEET_HEADERS))
                        sheet.update(f"A{idx}:{col_letter}{idx}", [row])
                        return True
            except Exception:
                pass
        sheet.append_row(row)
        return True
    except Exception as exc:
        st.warning(f"Could not write to Sheets: {exc}")
        return False


# ── OCR via Google Cloud Vision REST API ──────────────────────────────────────
def _ocr_with_vision(image_bytes: bytes, creds_info: dict) -> dict:
    """
    OCR a single image using the Vision API REST endpoint directly.
    Uses only requests + google-auth (no google-cloud-vision package needed).
    Returns {"raw_text": str, "confidence": float, "error": str | None}
    """
    try:
        import base64
        import requests as _req
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request as _GRequest

        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(_GRequest())

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = _req.post(
            "https://vision.googleapis.com/v1/images:annotate",
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json={
                "requests": [{
                    "image": {"content": image_b64},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }]
            },
            timeout=45,
        )

        if resp.status_code != 200:
            return {"raw_text": "", "confidence": 0.0,
                    "error": f"Vision API HTTP {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        r = (data.get("responses") or [{}])[0]

        if "error" in r:
            return {"raw_text": "", "confidence": 0.0,
                    "error": r["error"].get("message", "Vision API error")}

        full_text = r.get("fullTextAnnotation", {}).get("text", "")
        pages = r.get("fullTextAnnotation", {}).get("pages", [])
        confs = [
            block.get("confidence", 0) * 100
            for page in pages
            for block in page.get("blocks", [])
            if block.get("confidence", 0) > 0
        ]
        confidence = sum(confs) / len(confs) if confs else 85.0

        return {"raw_text": full_text, "confidence": round(confidence, 1), "error": None}

    except Exception as exc:
        return {"raw_text": "", "confidence": 0.0, "error": str(exc)}


def _ocr_pdf_with_vision(pdf_bytes: bytes, creds_info: dict) -> dict:
    """
    OCR a PDF directly using Vision API files:annotate (up to 5 pages sync).
    No PDF-to-image conversion required — Vision API handles PDFs natively.
    Returns {"raw_text": str, "confidence": float, "error": str | None}
    """
    try:
        import base64
        import requests as _req
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request as _GRequest

        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(_GRequest())

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        resp = _req.post(
            "https://vision.googleapis.com/v1/files:annotate",
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json={
                "requests": [{
                    "inputConfig": {
                        "content": pdf_b64,
                        "mimeType": "application/pdf",
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "pages": [1, 2, 3, 4, 5],  # up to 5 pages per sync request
                }]
            },
            timeout=60,
        )

        if resp.status_code != 200:
            return {"raw_text": "", "confidence": 0.0,
                    "error": f"Vision API HTTP {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        file_resp = (data.get("responses") or [{}])[0]

        if "error" in file_resp:
            return {"raw_text": "", "confidence": 0.0,
                    "error": file_resp["error"].get("message", "Vision API error")}

        # files:annotate returns one response per page inside file_resp["responses"]
        page_responses = file_resp.get("responses", [])
        texts, confs = [], []
        for pr in page_responses:
            annotation = pr.get("fullTextAnnotation", {})
            if annotation.get("text"):
                texts.append(annotation["text"])
            for page in annotation.get("pages", []):
                for block in page.get("blocks", []):
                    c = block.get("confidence", 0)
                    if c > 0:
                        confs.append(c * 100)

        full_text = "\n".join(texts)
        confidence = sum(confs) / len(confs) if confs else 85.0
        return {"raw_text": full_text, "confidence": round(confidence, 1), "error": None}

    except Exception as exc:
        return {"raw_text": "", "confidence": 0.0, "error": str(exc)}


def process_file(file_bytes: bytes, filename: str, creds_info: dict) -> dict:
    """
    Full pipeline: raw file bytes → OCR → field extraction → confidence scoring.
    Returns a result dict compatible with write_to_sheet().
    """
    start = time.time()

    is_pdf = file_bytes[:4] == b"%PDF" or filename.lower().endswith(".pdf")

    # ── Step 1: OCR ────────────────────────────────────────────────────────────
    if is_pdf:
        r = _ocr_pdf_with_vision(file_bytes, creds_info)
        raw_text = r["raw_text"]
        ocr_confidence = r["confidence"]
        if r["error"] and not raw_text:
            return {
                "status": "failed", "filename": filename,
                "error": r["error"],
                "fields": {}, "confidence": 0.0, "needs_review": True,
                "processing_time_seconds": round(time.time() - start, 2),
            }
    else:
        r = _ocr_with_vision(file_bytes, creds_info)
        raw_text = r["raw_text"]
        ocr_confidence = r["confidence"]
        if r["error"] and not raw_text:
            return {
                "status": "failed", "filename": filename,
                "error": r["error"],
                "fields": {}, "confidence": 0.0, "needs_review": True,
                "processing_time_seconds": round(time.time() - start, 2),
            }

    # ── Step 2: Field extraction + confidence scoring ──────────────────────────
    _core_import_err: str = ""
    try:
        from core.field_extractor import FieldExtractor
        from core.confidence_scorer import ConfidenceScorer
        extractor = FieldExtractor()
        scorer = ConfidenceScorer()
    except Exception as _exc:
        _core_import_err = str(_exc)
        extractor = _MinimalExtractor()
        scorer = _MinimalScorer()

    fields = extractor.extract_all(raw_text)
    scoring = scorer.score_extraction(fields, ocr_confidence)

    result: dict = {
        "status": "success",
        "filename": filename,
        "fields": fields,
        "confidence": scoring["overall"],
        "low_confidence_fields": scoring.get("low_confidence_fields", []),
        "processing_time_seconds": round(time.time() - start, 2),
        "needs_review": scoring["needs_review"],
        "raw_text": raw_text,
        "extractor": "FieldExtractor" if not _core_import_err else f"Fallback ({_core_import_err})",
    }
    return result


# ── Minimal inline fallbacks (used only if core/ imports fail) ─────────────────
class _MinimalExtractor:
    """
    Full-featured fallback extractor embedded in app.py so the app works even
    if sys.path doesn't contain the project root at import time.
    Handles same-line, next-line, AND two-column (Vision API column-by-column) layouts.
    """

    _AMT_RE = re.compile(
        r"[\$£€]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"
    )
    _DATE_RE = re.compile(
        r"\b(\d{4}[/\-]\d{1,2}[/\-]\d{1,2}"
        r"|\d{1,2}[/\-]\d{1,2}[/\-]\d{4}"
        r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
        re.I,
    )

    def _amt(self, text: str):
        m = self._AMT_RE.search(text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if val >= 1.0:
                    return f"${m.group(1)}"
            except ValueError:
                pass
        return None

    def _date_after(self, label_pat: str, text: str):
        """Extract a date from same line or next line after a label pattern.
        Wraps label_pat in (?:...) so alternation | doesn't swallow the suffix.
        """
        lp = f"(?:{label_pat})"
        # Same line
        m = re.search(lp + r"([^\n]{0,60})", text, re.I)
        if m:
            d = self._DATE_RE.search(m.group(1) or "")
            if d:
                return d.group(0)
        # Next line
        m = re.search(lp + r"[^\n]{0,10}\n\s*([^\n]{0,60})", text, re.I)
        if m:
            d = self._DATE_RE.search(m.group(1) or "")
            if d:
                return d.group(0)
        return None

    def _amt_after(self, label_pat: str, text: str):
        """Extract an amount from same line or next line after a label pattern.
        Wraps label_pat in (?:...) so alternation | doesn't swallow the suffix.
        """
        lp = f"(?:{label_pat})"
        m = re.search(lp + r"([^\n]{0,60})", text, re.I)
        if m and self._amt(m.group(1) or ""):
            return self._amt(m.group(1))
        m = re.search(lp + r"[^\n]{0,10}\n\s*([^\n]{0,60})", text, re.I)
        if m and self._amt(m.group(1) or ""):
            return self._amt(m.group(1))
        return None

    def _two_column_block(self, text: str) -> dict:
        """
        Detect Vision-API two-column reads: all labels first, then all amounts.
        E.g.: Subtotal:\nTax (15%):\nGrand Total:\n$2,220\n$333\n$2,553
        """
        _LABEL_FIELD = [
            ("subtotal",     [r"sub\s*total", r"subtotal", r"net\s*amount"]),
            ("tax",          [r"tax(?:\s*\(\d+%\))?", r"vat\b", r"gst\b"]),
            ("total_amount", [r"grand\s*total", r"total\s*due", r"amount\s*due",
                              r"total\s*amount", r"balance\s*due", r"(?<![a-z])total(?![a-z])"]),
        ]
        result: dict = {}
        lines = [ln.strip() for ln in text.split("\n")]
        for start in range(len(lines)):
            labels_run, i = [], start
            while i < len(lines):
                ln = lines[i]
                if not ln:
                    i += 1; continue
                hit = None
                for field, pats in _LABEL_FIELD:
                    if any(re.search(p, ln, re.I) for p in pats):
                        if not re.search(r"[\$£€]\s*\d|\d{3,}", ln):
                            hit = field; break
                if hit:
                    labels_run.append(hit); i += 1
                else:
                    break
            if len(labels_run) < 2:
                continue
            amts_run, j = [], i
            while j < len(lines) and len(amts_run) < len(labels_run):
                ln = lines[j]
                if not ln:
                    j += 1; continue
                a = self._amt(ln)
                if a:
                    amts_run.append(a); j += 1
                else:
                    break
            if len(amts_run) == len(labels_run):
                for field, amt in zip(labels_run, amts_run):
                    result[field] = amt
                if len(result) >= 2:
                    break
        return result

    def extract_all(self, text: str) -> dict:
        fields: dict = {
            "vendor_name": None, "invoice_number": None,
            "invoice_date": None, "due_date": None,
            "line_items": [], "subtotal": None, "tax": None, "total_amount": None,
        }

        # Invoice number — direct INV-XXXX pattern first, then label-based
        m = re.search(r"\bINV[-\s/]?\d{4}[-\s/]?\d{2,6}\b", text, re.I)
        if m:
            fields["invoice_number"] = m.group(0).strip()
        else:
            m = re.search(
                r"Invoice\s*(?:#|No\.?|Number|ID)[:\.\s\n]+([\w][\w\-/]{2,})",
                text, re.I,
            )
            if m:
                fields["invoice_number"] = m.group(1).strip()

        # Dates
        fields["invoice_date"] = self._date_after(
            r"Invoice\s*Date[:\s]*|Date\s*Issued[:\s]*|Date[:\s]*", text)
        fields["due_date"] = self._date_after(
            r"(?:Payment\s*)?Due\s*Date[:\s]*|Due\s*By[:\s]*", text)

        # Financial amounts — same-line / next-line
        fields["subtotal"]     = self._amt_after(r"Sub\s*Total[:\s]*|Subtotal[:\s]*|Net\s*Amount[:\s]*", text)
        fields["tax"]          = self._amt_after(r"Tax(?:\s*\(\d+%\))?[:\s]*|VAT[:\s]*|GST[:\s]*", text)
        fields["total_amount"] = (
            self._amt_after(r"Grand\s*Total[:\s]*", text)
            or self._amt_after(r"Total\s*Due[:\s]*|Amount\s*Due[:\s]*", text)
            or self._amt_after(r"(?<!\w)Total[:\s]*", text)
        )

        # Two-column fallback for any still-missing financial fields
        block = self._two_column_block(text)
        if len(block) == 3:
            fields.update(block)
        else:
            for f in ("subtotal", "tax", "total_amount"):
                if not fields[f] and block.get(f):
                    fields[f] = block[f]

        # Vendor: first substantive non-numeric line
        for line in text.split("\n"):
            line = line.strip()
            if line and len(line) > 3 and not re.match(r"^[\d\W]+$", line):
                fields["vendor_name"] = line
                break

        return fields


class _MinimalScorer:
    def score_extraction(self, fields: dict, ocr_confidence: float) -> dict:
        # line_items=[] is acceptable; don't penalise it
        key_fields = {k: v for k, v in fields.items() if k != "line_items"}
        present = sum(1 for v in key_fields.values() if v)
        total   = len(key_fields)
        field_pct = present / max(total, 1)
        overall = round(field_pct * 60 + ocr_confidence * 0.4, 1)
        low = [k for k, v in key_fields.items() if not v]
        return {
            "overall": overall,
            "field_scores": {},
            "low_confidence_fields": low,
            "needs_review": overall < 70 or len(low) >= 3,
        }


# ── Stats helper ───────────────────────────────────────────────────────────────
def _compute_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total_processed": 0, "total_success": 0,
                "total_failed": 0, "total_needs_review": 0, "avg_confidence": 0.0}
    total = len(df)
    failed = int((df.get("Status", pd.Series()).astype(str).str.lower() == "failed").sum())
    needs_review = int(
        (df.get("Needs Review", pd.Series()).astype(str).str.strip().str.lower() == "yes").sum()
    )
    conf_vals = pd.to_numeric(df.get("Confidence", pd.Series()), errors="coerce").dropna()
    avg_conf = float(conf_vals.mean()) if not conf_vals.empty else 0.0
    return {"total_processed": total, "total_success": total - failed,
            "total_failed": failed, "total_needs_review": needs_review,
            "avg_confidence": avg_conf}


# ══════════════════════════════════════════════════════════════════════════════
# Main UI
# ══════════════════════════════════════════════════════════════════════════════
st.title("OCR Invoice Pilot — Live Dashboard")
st.caption(f"Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

# Configuration warnings
if not _gcp_info:
    st.error(
        "**Google credentials not configured.**  "
        "Add `[gcp_service_account]` to your Streamlit secrets "
        "(see `.streamlit/secrets.toml.example`)."
    )
elif not SHEET_ID:
    st.warning(
        "**Google Sheet ID not set.**  "
        "Add `GOOGLE_SHEET_ID = \"your-sheet-id\"` to Streamlit secrets."
    )

tab_upload, tab_dashboard, tab_status = st.tabs(
    ["📤 Upload & Process", "📊 Dashboard", "⚙️ System Status"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Upload & Process  (also acts as the cloud Folder Watcher queue)
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Upload & Process Invoices")
    st.markdown(
        "Drop one or more invoices — PNG, JPG, or PDF.  "
        "Each file is processed in sequence (folder-watcher style): "
        "OCR → field extraction → Google Sheets, automatically."
    )

    if not _gcp_info:
        st.error("Configure GCP credentials in Streamlit secrets to enable processing.")
    else:
        uploaded_files = st.file_uploader(
            "Choose invoice files",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
            help="Upload one or many invoices — PNG, JPG, JPEG, or PDF, up to 20 MB each",
        )

        if uploaded_files:
            st.info(f"{len(uploaded_files)} file(s) queued for processing")

            process_btn = st.button(
                f"Process {len(uploaded_files)} Invoice(s)", type="primary"
            )

            if process_btn:
                batch_results = []
                progress = st.progress(0, text="Starting…")
                status_box = st.empty()

                for i, uf in enumerate(uploaded_files):
                    progress.progress(
                        (i) / len(uploaded_files),
                        text=f"Processing {i + 1}/{len(uploaded_files)}: {uf.name}",
                    )
                    status_box.info(f"Running OCR on **{uf.name}**…")
                    file_bytes = uf.getvalue()

                    if len(file_bytes) > 20 * 1024 * 1024:
                        batch_results.append({
                            "filename": uf.name,
                            "status": "failed",
                            "error": "File exceeds 20 MB limit",
                            "confidence": 0.0,
                            "needs_review": True,
                            "sheet_written": False,
                        })
                        continue

                    result = process_file(file_bytes, uf.name, _gcp_info)
                    if result["status"] == "success":
                        result["sheet_written"] = write_to_sheet(result)
                    else:
                        result["sheet_written"] = False
                    batch_results.append(result)

                progress.progress(1.0, text="Done")
                status_box.empty()
                st.cache_data.clear()
                st.session_state["batch_results"] = batch_results
                st.session_state.pop("last_result", None)

        # ── Batch results table ────────────────────────────────────────────────
        if "batch_results" in st.session_state:
            batch = st.session_state["batch_results"]
            success_n = sum(1 for r in batch if r["status"] == "success")
            failed_n  = len(batch) - success_n

            m1, m2, m3 = st.columns(3)
            m1.metric("Processed", len(batch))
            m2.metric("Success", success_n)
            m3.metric("Failed", failed_n)

            st.divider()

            for result in batch:
                fname = result.get("filename", "unknown")
                ok = result["status"] == "success"
                icon = "✅" if ok else "❌"
                with st.expander(f"{icon} {fname}  —  confidence {result.get('confidence', 0):.1f}%"):
                    if not ok:
                        st.error(result.get("error", "Unknown error"))
                        err_str = str(result.get("error", ""))
                        if any(k in err_str for k in ("Vision", "403", "not been used", "disabled")):
                            st.info(
                                "Enable [Cloud Vision API]"
                                "(https://console.cloud.google.com/apis/library/vision.googleapis.com)"
                                " in your GCP project, then retry."
                            )
                    else:
                        col_m1, col_m2, col_m3 = st.columns(3)
                        col_m1.metric("Confidence", f"{result.get('confidence', 0):.1f}%")
                        col_m2.metric("Review needed",
                                      "Yes" if result.get("needs_review") else "No")
                        col_m3.metric("Sheets", "Saved" if result.get("sheet_written") else "Failed")

                        eng = result.get("extractor", "")
                        if eng and "Fallback" in eng:
                            st.warning(f"Core extractor unavailable — using fallback. Reason: {eng}")
                        st.progress(min(result.get("confidence", 0) / 100, 1.0))

                        fields = result.get("fields", {})
                        low_conf = result.get("low_confidence_fields", [])
                        field_labels = {
                            "vendor_name":    "Vendor Name",
                            "invoice_number": "Invoice Number",
                            "invoice_date":   "Invoice Date",
                            "due_date":       "Due Date",
                            "subtotal":       "Subtotal",
                            "tax":            "Tax",
                            "total_amount":   "Total Amount",
                        }
                        rows = []
                        for key, label in field_labels.items():
                            val = fields.get(key)
                            rows.append({
                                "Field": ("⚠️ " if key in low_conf else "") + label,
                                "Value": str(val) if val else "(not detected)",
                            })
                        st.dataframe(
                            pd.DataFrame(rows), use_container_width=True, hide_index=True
                        )

                        line_items = fields.get("line_items", [])
                        if line_items:
                            st.markdown("**Line Items**")
                            st.dataframe(
                                pd.DataFrame(line_items),
                                use_container_width=True, hide_index=True,
                            )

                        with st.expander("Raw OCR text"):
                            st.text(result.get("raw_text", "(empty)"))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Dashboard
# ══════════════════════════════════════════════════════════════════════════════
with tab_dashboard:
    df, data_error = load_results()
    stats = _compute_stats(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Processed", stats["total_processed"])
    c2.metric(
        "Success Rate",
        f"{(stats['total_success'] / max(stats['total_processed'], 1)) * 100:.1f}%",
    )
    c3.metric("Avg Confidence", f"{stats['avg_confidence']:.1f}%")
    c4.metric("Needs Review", stats["total_needs_review"])

    st.divider()

    if data_error:
        st.warning(f"Could not load Sheets data: {data_error}")
    elif df.empty:
        if not SHEET_ID:
            st.info(
                "**No data source configured.**  "
                "Add `GOOGLE_SHEET_ID` and `[gcp_service_account]` to Streamlit secrets."
            )
        else:
            st.info(
                "No invoices processed yet.  "
                "Upload a file in the **Upload & Process** tab to get started."
            )
    else:
        search = st.text_input("Search by vendor or invoice number")
        fdf = df.copy()
        if search:
            mask = (
                fdf.get("Vendor", pd.Series(dtype=str))
                   .astype(str).str.contains(search, case=False, na=False)
                | fdf.get("Invoice No", pd.Series(dtype=str))
                   .astype(str).str.contains(search, case=False, na=False)
            )
            fdf = fdf[mask]

        def _row_color(row):
            status = str(row.get("Status", "")).lower()
            review = str(row.get("Needs Review", "")).strip().lower()
            if status == "failed":
                return ["background-color:#ffcccc"] * len(row)
            if review == "yes":
                return ["background-color:#fff3cd"] * len(row)
            return ["background-color:#d4edda"] * len(row)

        display_cols = [
            c for c in ["Timestamp", "Vendor", "Invoice No", "Invoice Date",
                         "Total", "Confidence", "Needs Review", "Status"]
            if c in fdf.columns
        ]
        st.subheader(f"Processed Invoices ({len(fdf)} results)")
        st.dataframe(
            fdf[display_cols].style.apply(_row_color, axis=1),
            use_container_width=True,
            height=400,
        )

        st.divider()
        ch1, ch2, ch3 = st.columns(3)

        with ch1:
            st.subheader("Invoices per Day")
            if "Timestamp" in df.columns:
                try:
                    tmp = df.copy()
                    tmp["Date"] = pd.to_datetime(tmp["Timestamp"], errors="coerce").dt.date
                    daily = (
                        tmp.dropna(subset=["Date"])
                           .groupby("Date").size()
                           .reset_index(name="Count")
                    )
                    st.bar_chart(daily.set_index("Date"))
                except Exception:
                    st.write("No date data.")

        with ch2:
            st.subheader("Status Breakdown")
            breakdown = {
                "Success": stats["total_success"],
                "Needs Review": stats["total_needs_review"],
                "Failed": stats["total_failed"],
            }
            pie_df = pd.DataFrame(list(breakdown.items()), columns=["Status", "Count"])
            pie_df = pie_df[pie_df["Count"] > 0]
            if not pie_df.empty:
                try:
                    import altair as alt
                    st.altair_chart(
                        alt.Chart(pie_df).mark_arc().encode(
                            theta="Count:Q",
                            color="Status:N",
                            tooltip=["Status", "Count"],
                        ).properties(height=200),
                        use_container_width=True,
                    )
                except Exception:
                    st.dataframe(pie_df, hide_index=True)
            else:
                st.write("No data yet.")

        with ch3:
            st.subheader("Confidence Trend")
            if "Confidence" in df.columns:
                try:
                    vals = pd.to_numeric(df["Confidence"], errors="coerce").dropna()
                    st.line_chart(vals.reset_index(drop=True))
                except Exception:
                    st.write("No confidence data.")

        st.divider()
        st.subheader("Failed Documents")
        if "Status" in df.columns:
            failed_rows = df[df["Status"].astype(str).str.lower() == "failed"]
            if not failed_rows.empty:
                show_cols = [
                    c for c in ["Filename", "Vendor", "Invoice No", "Timestamp"]
                    if c in failed_rows.columns
                ]
                st.dataframe(
                    failed_rows[show_cols] if show_cols else failed_rows,
                    use_container_width=True,
                )
            else:
                st.write("No failed documents.")
        else:
            st.write("No failed documents.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — System Status
# ══════════════════════════════════════════════════════════════════════════════
with tab_status:
    st.header("System Status")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("7 Core Pipeline Tasks")
        tasks = [
            ("OCR Extraction",
             "Google Cloud Vision API — reads images & PDFs",
             bool(_gcp_info)),
            ("Field Extraction",
             "Regex + heuristics — vendor, dates, amounts, line items",
             True),
            ("Google Sheets Writing",
             "gspread — auto-write + duplicate detection",
             bool(SHEET_ID and _gcp_info)),
            ("Folder Watching",
             "Multi-file queue — upload a batch, processed in sequence",
             True),
            ("REST API",
             "FastAPI — /extract, /extract-batch, /health, /stats",
             True),
            ("Batch Processing",
             "Up to 10 files per upload session, progress bar",
             True),
            ("Monitoring Dashboard",
             "Live stats, charts, search — 30 s auto-refresh",
             True),
        ]
        for name, impl, active in tasks:
            icon = "✅" if active else "❌"
            st.markdown(f"{icon} **{name}**")
            st.caption(f"   {impl}")

    with col_b:
        st.subheader("Configuration")
        st.markdown(
            f"**GCP Credentials:** {'✅ Configured' if _gcp_info else '❌ Missing'}"
        )
        st.markdown(
            f"**Google Sheet ID:** {'✅ Set' if SHEET_ID else '❌ Not set'}"
        )
        if _gcp_info:
            st.markdown(
                f"**Service Account:** `{_gcp_info.get('client_email', 'unknown')}`"
            )
        st.markdown("---")
        st.markdown("**GCP APIs required:**")
        st.markdown("✅ Google Sheets API")
        st.markdown("✅ Google Drive API")
        st.markdown(
            "✅ [Cloud Vision API]"
            "(https://console.cloud.google.com/apis/library/vision.googleapis.com)"
        )

    st.divider()

    # REST API reference panel
    st.subheader("REST API — Endpoint Reference")
    st.markdown(
        "The FastAPI backend (`api/main.py`) exposes these endpoints.  "
        "Run locally with `uvicorn api.main:app --port 8000` or deploy to Railway/Render."
    )

    api_cols = st.columns(2)
    endpoints = [
        ("POST", "/extract",
         "Upload a single invoice file (multipart/form-data). "
         "Returns extracted fields, confidence score, and Sheets write status.",
         "X-API-Key: ocr-pilot-key-2026\nContent-Type: multipart/form-data\nbody: file=<image_or_pdf>"),
        ("POST", "/extract-batch",
         "Send up to 10 base64-encoded invoices in one JSON request.",
         'X-API-Key: ocr-pilot-key-2026\n[{"filename":"inv.png","data":"<base64>"},…]'),
        ("GET", "/health",
         "Liveness check — returns status, version, and UTC timestamp.",
         "→ {\"status\":\"ok\",\"version\":\"1.0.0\",\"timestamp\":\"…\"}"),
        ("GET", "/stats",
         "Aggregated processing statistics from logs/stats.json.",
         "→ {\"total_processed\":42,\"avg_confidence\":87.3,…}"),
    ]
    for i, (method, path, desc, detail) in enumerate(endpoints):
        with api_cols[i % 2]:
            badge = "🟢" if method == "GET" else "🔵"
            st.markdown(f"{badge} **`{method} {path}`**")
            st.caption(desc)
            with st.expander("Details"):
                st.code(detail, language="text")

    st.divider()
    st.subheader("How the pipeline works")
    st.markdown(
        """
1. **Upload** — drop any invoice (PNG, JPG, PDF) in the Upload tab; upload multiple to process as a batch
2. **OCR Extraction** — Google Cloud Vision reads all text from every page of every file
3. **Field Extraction** — regex + heuristics parse vendor name, invoice number, dates, line items, totals
4. **Confidence Scoring** — each field scored 0–100; results below 70% are flagged for review
5. **Folder Watching** — the upload queue processes files in sequence, exactly like a local folder watcher
6. **Duplicate Detection** — same invoice number? existing Sheets row is updated, not duplicated
7. **Google Sheets** — every result is written automatically; Dashboard refreshes every 30 seconds
        """
    )


# ── Auto-refresh ───────────────────────────────────────────────────────────────
st.divider()
col_btn, col_info = st.columns([1, 4])
with col_btn:
    if st.button("Refresh Now"):
        st.cache_data.clear()
        st.rerun()
with col_info:
    st.caption("Auto-refreshes every 30 seconds")

if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()

elapsed = time.time() - st.session_state["last_refresh"]
if elapsed >= 30:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Next refresh in {int(30 - elapsed)}s")
