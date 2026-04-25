"""
Streamlit monitoring dashboard — OCR Invoice Pilot.
Cloud-compatible: loads data from Google Sheets via st.secrets.

Local:  streamlit run dashboard/app.py
Cloud:  Streamlit Cloud → main file = dashboard/app.py
"""
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="OCR Invoice Pilot — Live Dashboard",
    page_icon="🧾",
    layout="wide",
)

# ── Config ─────────────────────────────────────────────────────────────────────
def _secret(key: str, default: str = "") -> str:
    """Read from st.secrets (cloud) then env vars (local)."""
    try:
        val = st.secrets.get(key)
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


SHEET_ID = _secret("GOOGLE_SHEET_ID")
API_URL  = _secret("API_URL", "http://127.0.0.1:8000")
API_KEY  = _secret("API_KEY", "ocr-pilot-key-2026")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ── Data loading ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_results() -> pd.DataFrame:
    """Load from Google Sheets (cloud secrets or local creds file) → CSV fallback."""
    if SHEET_ID:
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            # Cloud: credentials stored as st.secrets["gcp_service_account"]
            try:
                info = dict(st.secrets["gcp_service_account"])
                creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
            except (KeyError, Exception):
                # Local dev: use credentials.json file
                creds_file = _secret("GOOGLE_CREDENTIALS_FILE", "credentials.json")
                if not Path(creds_file).exists():
                    raise FileNotFoundError(f"credentials file not found: {creds_file}")
                creds = Credentials.from_service_account_file(creds_file, scopes=_SCOPES)

            client = gspread.authorize(creds)
            sheet  = client.open_by_key(SHEET_ID).sheet1
            records = sheet.get_all_records()
            return pd.DataFrame(records) if records else pd.DataFrame()

        except Exception as exc:
            st.warning(f"Google Sheets unavailable: {exc}")

    # Local CSV fallback
    csv_path = Path("output_fallback.csv")
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path)
        except Exception:
            pass

    return pd.DataFrame()


def _compute_stats(df: pd.DataFrame) -> dict:
    base = {"total_processed": 0, "total_success": 0, "total_failed": 0,
            "total_needs_review": 0, "avg_confidence": 0.0}
    if df.empty:
        return base

    total = len(df)
    failed = 0
    if "Status" in df.columns:
        failed = int((df["Status"].astype(str).str.lower() == "failed").sum())
    needs_review = 0
    if "Needs Review" in df.columns:
        needs_review = int((df["Needs Review"].astype(str).str.strip().str.lower() == "yes").sum())
    avg_conf = 0.0
    if "Confidence" in df.columns:
        vals = pd.to_numeric(df["Confidence"], errors="coerce").dropna()
        avg_conf = float(vals.mean()) if not vals.empty else 0.0

    return {
        "total_processed": total,
        "total_success": total - failed,
        "total_failed": failed,
        "total_needs_review": needs_review,
        "avg_confidence": avg_conf,
    }


# ── Sidebar: upload & extract ──────────────────────────────────────────────────
with st.sidebar:
    st.header("Upload Invoice")
    if not API_URL or "127.0.0.1" in API_URL:
        st.info("Upload requires the OCR API.\n\n"
                "Set `API_URL` in Streamlit secrets to a hosted API endpoint, "
                "or run the API locally and use the local dashboard.")
    else:
        import requests as _req
        uploaded = st.file_uploader(
            "Choose invoice (PNG, JPG, PDF)",
            type=["png", "jpg", "jpeg", "pdf"],
        )
        if uploaded and st.button("Extract Now", type="primary"):
            with st.spinner("Processing…"):
                try:
                    resp = _req.post(
                        f"{API_URL}/extract",
                        files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                        headers={"X-API-Key": API_KEY},
                        timeout=120,
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        f = d.get("fields", {})
                        st.success(f"Done — confidence {d.get('confidence', 0):.1f}%")
                        st.json({"Vendor": f.get("vendor_name"),
                                 "Invoice #": f.get("invoice_number"),
                                 "Date": f.get("invoice_date"),
                                 "Total": f.get("total_amount"),
                                 "Needs Review": d.get("needs_review")})
                    else:
                        st.error(f"API error {resp.status_code}: {resp.text[:200]}")
                except Exception as exc:
                    st.error(f"Error: {exc}")

    st.divider()
    st.caption(f"API: {API_URL}")


# ── Main content ───────────────────────────────────────────────────────────────
st.title("OCR Invoice Pilot — Live Dashboard")
st.caption(f"Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

df    = load_results()
stats = _compute_stats(df)

# Metric cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Processed", stats["total_processed"])
success_rate = (stats["total_success"] / max(stats["total_processed"], 1)) * 100
c2.metric("Success Rate",   f"{success_rate:.1f}%")
c3.metric("Avg Confidence", f"{stats['avg_confidence']:.1f}%")
c4.metric("Needs Review",   stats["total_needs_review"])

st.divider()

if df.empty:
    if not SHEET_ID:
        st.warning("No data source configured.\n\n"
                   "Add `GOOGLE_SHEET_ID` (and `gcp_service_account`) to Streamlit secrets, "
                   "or run the pipeline locally so `output_fallback.csv` is populated.")
    else:
        st.info("No invoices processed yet. Drop files into `inbox/` to start.")
else:
    search = st.text_input("Search by vendor or invoice number")
    fdf = df.copy()
    if search:
        mask = (
            fdf.get("Vendor", pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
            | fdf.get("Invoice No", pd.Series(dtype=str)).astype(str).str.contains(search, case=False, na=False)
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

    display_cols = [c for c in ["Timestamp", "Vendor", "Invoice No", "Invoice Date",
                                 "Total", "Confidence", "Needs Review", "Status"]
                    if c in fdf.columns]
    st.subheader(f"Processed Invoices ({len(fdf)} results)")
    st.dataframe(fdf[display_cols].style.apply(_row_color, axis=1),
                 use_container_width=True, height=400)

    st.divider()

    # Charts
    ch1, ch2, ch3 = st.columns(3)

    with ch1:
        st.subheader("Invoices per Day")
        if "Timestamp" in df.columns:
            try:
                tmp = df.copy()
                tmp["Date"] = pd.to_datetime(tmp["Timestamp"], errors="coerce").dt.date
                daily = tmp.dropna(subset=["Date"]).groupby("Date").size().reset_index(name="Count")
                st.bar_chart(daily.set_index("Date"))
            except Exception:
                st.write("No date data.")

    with ch2:
        st.subheader("Status Breakdown")
        breakdown = {"Success": stats["total_success"],
                     "Needs Review": stats["total_needs_review"],
                     "Failed": stats["total_failed"]}
        pie_df = pd.DataFrame(list(breakdown.items()), columns=["Status", "Count"])
        pie_df = pie_df[pie_df["Count"] > 0]
        if not pie_df.empty:
            try:
                import altair as alt
                chart = (alt.Chart(pie_df)
                         .mark_arc()
                         .encode(theta="Count:Q", color="Status:N",
                                 tooltip=["Status", "Count"])
                         .properties(height=200))
                st.altair_chart(chart, use_container_width=True)
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

# Failed documents (from Sheets data)
st.subheader("Failed Documents")
if not df.empty and "Status" in df.columns:
    failed_rows = df[df["Status"].astype(str).str.lower() == "failed"]
    if not failed_rows.empty:
        show_cols = [c for c in ["Filename", "Vendor", "Invoice No", "Timestamp"] if c in failed_rows.columns]
        st.dataframe(failed_rows[show_cols] if show_cols else failed_rows,
                     use_container_width=True)
    else:
        st.write("No failed documents.")
else:
    st.write("No failed documents.")

# Auto-refresh
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

if time.time() - st.session_state["last_refresh"] >= 30:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    remaining = int(30 - (time.time() - st.session_state["last_refresh"]))
    st.caption(f"Next refresh in {remaining}s")
