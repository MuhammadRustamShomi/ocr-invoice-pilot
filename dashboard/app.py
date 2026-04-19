"""
Streamlit monitoring dashboard for OCR Invoice Pilot.
Run: streamlit run dashboard/app.py
"""
import json
import os
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

from dotenv import load_dotenv
load_dotenv()

import requests as _requests

STATS_FILE = Path("logs/stats.json")
CSV_FALLBACK = Path("output_fallback.csv")
FAILED_DIR = Path("failed")
API_URL = f"http://{os.getenv('API_HOST','127.0.0.1')}:{os.getenv('API_PORT','8000')}"
API_KEY = os.getenv("API_KEY", "ocr-pilot-key-2026")

st.set_page_config(
    page_title="OCR Invoice Pilot — Live Dashboard",
    page_icon="🧾",
    layout="wide",
)

st.title("OCR Invoice Pilot — Live Dashboard")
st.caption(f"Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

# --- Upload page (sidebar) ---
with st.sidebar:
    st.header("Upload Invoice")
    st.caption("Upload directly from browser — no need to use inbox/ folder")
    uploaded = st.file_uploader(
        "Choose invoice (PNG, JPG, PDF)",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=False,
    )
    if uploaded:
        if st.button("Extract Now", type="primary"):
            with st.spinner("Processing..."):
                try:
                    resp = _requests.post(
                        f"{API_URL}/extract",
                        files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                        headers={"X-API-Key": API_KEY},
                        timeout=120,
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        st.success(f"Done — confidence {d.get('confidence',0):.1f}%")
                        f = d.get("fields", {})
                        st.json({
                            "Vendor": f.get("vendor_name"),
                            "Invoice #": f.get("invoice_number"),
                            "Date": f.get("invoice_date"),
                            "Total": f.get("total_amount"),
                            "Needs Review": d.get("needs_review"),
                        })
                    else:
                        st.error(f"API error {resp.status_code}: {resp.text[:200]}")
                except _requests.exceptions.ConnectionError:
                    st.error("Cannot reach API. Is it running on port 8000?")
                except Exception as e:
                    st.error(f"Error: {e}")
    st.divider()
    st.caption(f"API: {API_URL}")


def load_stats() -> dict:
    defaults = {
        "total_processed": 0,
        "total_success": 0,
        "total_failed": 0,
        "total_needs_review": 0,
        "avg_confidence": 0.0,
        "avg_processing_time": 0.0,
        "last_updated": "N/A",
    }
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                return {**defaults, **json.load(f)}
        except Exception:
            pass
    return defaults


def load_results() -> pd.DataFrame:
    """Load results from Google Sheets or CSV fallback."""
    # Try Google Sheets
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if Path(creds_file).exists() and sheet_id:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(sheet_id).sheet1
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        except Exception:
            pass

    # CSV fallback
    if CSV_FALLBACK.exists():
        try:
            return pd.read_csv(CSV_FALLBACK)
        except Exception:
            pass

    return pd.DataFrame()


stats = load_stats()
df = load_results()

# --- Metric cards ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Processed", stats["total_processed"])
success_rate = (stats["total_success"] / max(stats["total_processed"], 1)) * 100
col2.metric("Success Rate", f"{success_rate:.1f}%")
col3.metric("Avg Confidence", f"{stats['avg_confidence']:.1f}%")
col4.metric("Needs Review", stats["total_needs_review"])

st.divider()

if df.empty:
    st.info("No data yet. Drop invoices into inbox/ to start processing.")
else:
    # --- Search ---
    search = st.text_input("Search by vendor or invoice number")
    filtered = df.copy()
    if search:
        mask = (
            filtered.get("Vendor", pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
            | filtered.get("Invoice No", pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]

    # --- Color-code rows ---
    def row_color(row):
        needs_review = str(row.get("Needs Review", "")).strip().lower()
        status = str(row.get("Status", "")).strip().lower()
        if status == "failed":
            return ["background-color: #ffcccc"] * len(row)
        if needs_review == "yes":
            return ["background-color: #fff3cd"] * len(row)
        return ["background-color: #d4edda"] * len(row)

    display_cols = [c for c in ["Timestamp", "Vendor", "Invoice No", "Invoice Date",
                                 "Total", "Confidence", "Needs Review", "Status"]
                    if c in filtered.columns]
    styled = filtered[display_cols].style.apply(row_color, axis=1)

    st.subheader(f"Processed Invoices ({len(filtered)} results)")
    st.dataframe(styled, use_container_width=True, height=400)

    st.divider()

    # --- Charts ---
    chart_col1, chart_col2, chart_col3 = st.columns(3)

    with chart_col1:
        st.subheader("Invoices per Day")
        if "Timestamp" in df.columns:
            try:
                df["Date"] = pd.to_datetime(df["Timestamp"]).dt.date
                daily = df.groupby("Date").size().reset_index(name="Count")
                st.bar_chart(daily.set_index("Date"))
            except Exception:
                st.write("No date data available.")

    with chart_col2:
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
                chart = alt.Chart(pie_df).mark_arc().encode(
                    theta="Count:Q", color="Status:N",
                    tooltip=["Status", "Count"]
                ).properties(height=200)
                st.altair_chart(chart, use_container_width=True)
            except Exception:
                st.dataframe(pie_df, hide_index=True)
        else:
            st.write("No data yet.")

    with chart_col3:
        st.subheader("Confidence Trend")
        if "Confidence" in df.columns:
            try:
                conf_series = pd.to_numeric(df["Confidence"], errors="coerce").dropna()
                st.line_chart(conf_series.reset_index(drop=True))
            except Exception:
                st.write("No confidence data.")

st.divider()

# --- Failed documents ---
st.subheader("Failed Documents")
failed_files = [f for f in FAILED_DIR.iterdir() if f.is_file() and f.name != ".gitkeep"] \
    if FAILED_DIR.exists() else []
if failed_files:
    for f in sorted(failed_files, key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        st.write(f"- `{f.name}` ({f.stat().st_size} bytes)")
else:
    st.write("No failed documents.")

# --- Auto-refresh ---
st.divider()
col_btn, col_info = st.columns([1, 4])
with col_btn:
    if st.button("Refresh Now"):
        st.rerun()
with col_info:
    st.caption("Auto-refreshes every 30 seconds")

# Auto-refresh using Streamlit's fragment / query params approach
import time as _time
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = _time.time()

elapsed = _time.time() - st.session_state["last_refresh"]
if elapsed >= 30:
    st.session_state["last_refresh"] = _time.time()
    st.rerun()
else:
    # Schedule next rerun without blocking
    remaining = int(30 - elapsed)
    st.caption(f"Next refresh in {remaining}s")
