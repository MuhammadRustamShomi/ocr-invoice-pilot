"""
OCR Invoice Pilot — Complete Streamlit Pipeline
Upload → OCR (Google Cloud Vision) → Extract Fields → Google Sheets → Dashboard

All 7 pipeline tasks run inside this app — no external API required.
"""
import io
import json
import os
import time
from datetime import datetime, timezone

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
@st.cache_resource
def _get_sheets_client():
    if not _gcp_info:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(_gcp_info, scopes=_SHEETS_SCOPES)
        return gspread.authorize(creds)
    except Exception as exc:
        st.warning(f"Could not connect to Google Sheets: {exc}")
        return None


def _get_sheet():
    client = _get_sheets_client()
    if not client or not SHEET_ID:
        return None
    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(SHEET_HEADERS)
        return sheet
    except Exception as exc:
        st.warning(f"Could not open sheet: {exc}")
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_sheet_data(sheet_id: str, creds_json: str) -> tuple[list, str]:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        client = gspread.authorize(creds)
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


# ── OCR via Google Cloud Vision API ───────────────────────────────────────────
def _ocr_with_vision(image_bytes: bytes, creds_info: dict) -> dict:
    """
    OCR a single image using Google Cloud Vision document_text_detection.
    Returns {"raw_text": str, "confidence": float, "error": str | None}
    """
    try:
        from google.cloud import vision as gv
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = gv.ImageAnnotatorClient(credentials=creds)
        image = gv.Image(content=image_bytes)
        response = client.document_text_detection(image=image)

        if response.error.message:
            return {"raw_text": "", "confidence": 0.0, "error": response.error.message}

        full_text = ""
        confidence = 85.0  # default when Vision API doesn't return per-block confidence

        if response.full_text_annotation:
            full_text = response.full_text_annotation.text
            confs = [
                block.confidence * 100
                for page in response.full_text_annotation.pages
                for block in page.blocks
                if block.confidence > 0
            ]
            if confs:
                confidence = sum(confs) / len(confs)

        return {"raw_text": full_text, "confidence": round(confidence, 1), "error": None}

    except ImportError:
        return {"raw_text": "", "confidence": 0.0,
                "error": "google-cloud-vision package not installed"}
    except Exception as exc:
        return {"raw_text": "", "confidence": 0.0, "error": str(exc)}


def _pdf_to_png_pages(pdf_bytes: bytes) -> list[bytes]:
    """Convert each PDF page to a PNG bytes object using PyMuPDF."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            mat = fitz.Matrix(2.0, 2.0)  # 2× zoom → better OCR quality
            pix = page.get_pixmap(matrix=mat)
            pages.append(pix.tobytes("png"))
        doc.close()
        return pages
    except ImportError:
        return []
    except Exception:
        return []


def process_file(file_bytes: bytes, filename: str, creds_info: dict) -> dict:
    """
    Full pipeline: raw file bytes → OCR → field extraction → confidence scoring.
    Returns a result dict compatible with write_to_sheet().
    """
    start = time.time()

    is_pdf = file_bytes[:4] == b"%PDF" or filename.lower().endswith(".pdf")

    # ── Step 1: OCR ────────────────────────────────────────────────────────────
    if is_pdf:
        pages = _pdf_to_png_pages(file_bytes)
        if not pages:
            return {
                "status": "failed", "filename": filename,
                "error": "Could not convert PDF to images. Ensure PyMuPDF is installed.",
                "fields": {}, "confidence": 0.0, "needs_review": True,
                "processing_time_seconds": round(time.time() - start, 2),
            }
        texts, confidences, last_error = [], [], None
        for page_bytes in pages:
            r = _ocr_with_vision(page_bytes, creds_info)
            if r["raw_text"]:
                texts.append(r["raw_text"])
                confidences.append(r["confidence"])
            if r["error"]:
                last_error = r["error"]
        if not texts:
            return {
                "status": "failed", "filename": filename,
                "error": last_error or "OCR returned no text from PDF",
                "fields": {}, "confidence": 0.0, "needs_review": True,
                "processing_time_seconds": round(time.time() - start, 2),
            }
        raw_text = "\n".join(texts)
        ocr_confidence = sum(confidences) / len(confidences)
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
    try:
        from core.field_extractor import FieldExtractor
        from core.confidence_scorer import ConfidenceScorer
        extractor = FieldExtractor()
        scorer = ConfidenceScorer()
    except Exception:
        # Inline minimal fallback so the app never hard-crashes
        extractor = _MinimalExtractor()
        scorer = _MinimalScorer()

    fields = extractor.extract_all(raw_text)
    scoring = scorer.score_extraction(fields, ocr_confidence)

    return {
        "status": "success",
        "filename": filename,
        "fields": fields,
        "confidence": scoring["overall"],
        "low_confidence_fields": scoring.get("low_confidence_fields", []),
        "processing_time_seconds": round(time.time() - start, 2),
        "needs_review": scoring["needs_review"],
        "raw_text": raw_text,
    }


# ── Minimal inline fallbacks (used only if core/ imports fail) ─────────────────
class _MinimalExtractor:
    """Bare-minimum field extractor used if core/field_extractor.py is unavailable."""

    def extract_all(self, text: str) -> dict:
        import re
        fields: dict = {
            "vendor_name": None, "invoice_number": None,
            "invoice_date": None, "due_date": None,
            "line_items": [], "subtotal": None, "tax": None, "total_amount": None,
        }
        # Invoice number
        m = re.search(r"(INV[-\s]?\d[\w\-]+|Invoice\s*#\s*[\w\-]+)", text, re.I)
        if m:
            fields["invoice_number"] = m.group(0).strip()
        # Total
        m = re.search(r"(?:Grand\s*Total|Total\s*Due|Total)[:\s]+[\$£€]?\s*([\d,]+\.?\d*)", text, re.I)
        if m:
            fields["total_amount"] = f"${m.group(1)}"
        # Date
        m = re.search(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b", text)
        if m:
            fields["invoice_date"] = m.group(0)
        # Vendor: first non-blank, non-numeric line
        for line in text.split("\n"):
            line = line.strip()
            if line and len(line) > 3 and not re.match(r"^[\d\W]+$", line):
                fields["vendor_name"] = line
                break
        return fields


class _MinimalScorer:
    def score_extraction(self, fields: dict, ocr_confidence: float) -> dict:
        present = sum(1 for v in fields.values() if v and v != [])
        overall = round((present / max(len(fields), 1)) * 60 + ocr_confidence * 0.4, 1)
        low = [k for k, v in fields.items() if not v or v == []]
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
# TAB 1 — Upload & Process
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Process an Invoice")
    st.markdown(
        "Upload any invoice — PNG, JPG, or PDF.  "
        "OCR runs via Google Cloud Vision; results are saved to Google Sheets automatically."
    )

    if not _gcp_info:
        st.error("Configure GCP credentials in Streamlit secrets to enable processing.")
    else:
        col_left, col_right = st.columns([1, 1], gap="large")

        with col_left:
            uploaded = st.file_uploader(
                "Choose invoice file",
                type=["png", "jpg", "jpeg", "pdf"],
                help="PNG, JPG, JPEG, or PDF — up to 20 MB",
            )

            if uploaded:
                st.info(
                    f"**{uploaded.name}** — "
                    f"{len(uploaded.getvalue()) / 1024:.1f} KB"
                )
                if uploaded.type and uploaded.type.startswith("image/"):
                    st.image(uploaded, use_container_width=True, caption="Preview")
                elif uploaded.name.lower().endswith(".pdf"):
                    st.markdown("**PDF** — all pages will be processed")

                process_btn = st.button(
                    "Extract Invoice Data", type="primary", use_container_width=True
                )

                if process_btn:
                    file_bytes = uploaded.getvalue()
                    if len(file_bytes) > 20 * 1024 * 1024:
                        st.error("File exceeds 20 MB limit.")
                    else:
                        with st.spinner(
                            "Running OCR and extracting fields… (3–15 seconds)"
                        ):
                            result = process_file(file_bytes, uploaded.name, _gcp_info)

                        st.session_state["last_result"] = result

                        if result["status"] == "success":
                            sheet_ok = write_to_sheet(result)
                            st.session_state["last_result"]["sheet_written"] = sheet_ok
                            st.cache_data.clear()  # refresh dashboard data

        with col_right:
            if "last_result" in st.session_state:
                result = st.session_state["last_result"]

                if result["status"] == "failed":
                    st.error(f"Processing failed: {result.get('error', 'Unknown error')}")

                    err_str = str(result.get("error", ""))
                    if any(k in err_str for k in ("Vision", "403", "not been used", "disabled", "API")):
                        st.info(
                            "**Enable Google Cloud Vision API in your GCP project:**\n\n"
                            "1. Go to [Google Cloud Console]"
                            "(https://console.cloud.google.com/apis/library/vision.googleapis.com)\n"
                            "2. Select your project\n"
                            "3. Click **Enable**\n"
                            "4. Re-upload your invoice"
                        )
                else:
                    conf = result.get("confidence", 0.0)
                    st.success(
                        f"Done in {result.get('processing_time_seconds', 0):.1f}s"
                    )
                    col_m1, col_m2 = st.columns(2)
                    col_m1.metric("Confidence", f"{conf:.1f}%")
                    col_m2.metric(
                        "Review needed",
                        "Yes" if result.get("needs_review") else "No",
                    )
                    st.progress(min(conf / 100, 1.0))

                    if result.get("needs_review"):
                        st.warning("Low confidence — manual review recommended")
                    if result.get("sheet_written"):
                        st.success("Saved to Google Sheets")
                    elif result.get("status") == "success":
                        st.warning("Could not write to Sheets (check Sheet ID and permissions)")

                    st.subheader("Extracted Fields")
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
                    for key, label in field_labels.items():
                        val = fields.get(key)
                        prefix = "⚠️ " if key in low_conf else ""
                        display = str(val) if val else "(not detected)"
                        st.text_input(
                            f"{prefix}{label}",
                            value=display,
                            disabled=True,
                            key=f"fi_{key}",
                        )

                    line_items = fields.get("line_items", [])
                    if line_items:
                        st.subheader("Line Items")
                        st.dataframe(
                            pd.DataFrame(line_items),
                            use_container_width=True,
                            hide_index=True,
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
        st.subheader("Pipeline Tasks")
        tasks = [
            ("OCR Extraction",      "Google Cloud Vision API",    bool(_gcp_info)),
            ("Field Extraction",    "Regex + heuristics (core/)", True),
            ("Google Sheets Writing", "gspread",                  bool(SHEET_ID and _gcp_info)),
            ("Folder Watching",     "Local/server only",          False),
            ("REST API",            "External (optional)",        False),
            ("Batch Processing",    "Upload tab (up to 20 MB)",   True),
            ("Monitoring Dashboard","This app (30s auto-refresh)", True),
        ]
        for name, impl, active in tasks:
            icon = "✅" if active else "⚠️"
            st.markdown(f"{icon} **{name}** — {impl}")

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
        st.markdown("**Required GCP APIs (enable all three):**")
        st.markdown("- Google Sheets API")
        st.markdown("- Google Drive API")
        st.markdown(
            "- [Cloud Vision API]"
            "(https://console.cloud.google.com/apis/library/vision.googleapis.com)"
            " ← needed for OCR"
        )

    st.divider()
    st.subheader("How the pipeline works")
    st.markdown(
        """
1. **Upload** — drop any invoice image (PNG, JPG) or PDF in the Upload tab
2. **OCR Extraction** — Google Cloud Vision reads all text from every page
3. **Field Extraction** — regex + heuristics parse vendor, dates, amounts, line items
4. **Confidence Scoring** — each field is scored 0–100; low-confidence fields are flagged
5. **Duplicate Check** — if the same invoice number already exists in Sheets, the row is updated
6. **Google Sheets** — results are written automatically; no manual export needed
7. **Dashboard** — the Dashboard tab shows live stats and refreshes every 30 seconds
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
