"""BPA CMO Dashboard entrypoint."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from dashboard.auth import require_password
from dashboard.sections.marketing import render_marketing


st.set_page_config(
    page_title="BPA CMO Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

require_password()

# --- Global header ---
st.title("BPA CMO Dashboard")

col_dates, col_refresh = st.columns([4, 1])
with col_dates:
    today = date.today()
    default_start = today - timedelta(days=7)
    date_range = st.date_input(
        "Date range",
        value=(default_start, today),
        max_value=today,
    )
with col_refresh:
    st.write("")  # spacing
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    st.warning("Pick a start and end date.")
    st.stop()

st.caption(f"Window: {start_date} → {end_date}")

# --- Tabs ---
tab_marketing, tab_sales = st.tabs(["MARKETING", "SALES"])

with tab_marketing:
    render_marketing(start_date, end_date)

with tab_sales:
    st.info("Sales tab — wired in Phase 5.")
