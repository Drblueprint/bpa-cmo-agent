"""BPA CMO Dashboard entrypoint."""
from __future__ import annotations

import os
import sys

# Ensure repo root is on the path so `dashboard.*` imports resolve on Streamlit Cloud
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import streamlit as st

from dashboard.auth import require_password
from dashboard.sections.executive import render_executive
from dashboard.sections.metrics import render_metrics
from dashboard.sections.sales import render_sales


st.set_page_config(
    page_title="BPA CMO Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

require_password()

# --- Global header ---
st.title("BPA CMO Dashboard")

col_preset, col_dates, col_refresh = st.columns([1.2, 3, 1])

with col_preset:
    preset = st.selectbox(
        "Quick range",
        ["Custom", "Last 7 days", "Last 14 days", "Last 30 days",
         "This Month", "Last Month", "Last 90 days", "Year to Date"],
        index=4,  # default = This Month (MTD)
        key="date_preset",
        help="Pick a preset and the date range updates automatically. "
             "Choose 'Custom' to set dates manually.",
    )

with col_dates:
    today = date.today()
    if preset == "Last 7 days":
        preset_start, preset_end = today - timedelta(days=7), today
    elif preset == "Last 14 days":
        preset_start, preset_end = today - timedelta(days=14), today
    elif preset == "Last 30 days":
        preset_start, preset_end = today - timedelta(days=30), today
    elif preset == "This Month":
        preset_start = today.replace(day=1)
        preset_end = today
    elif preset == "Last Month":
        first_of_this_month = today.replace(day=1)
        last_of_prev = first_of_this_month - timedelta(days=1)
        preset_start = last_of_prev.replace(day=1)
        preset_end = last_of_prev
    elif preset == "Last 90 days":
        preset_start, preset_end = today - timedelta(days=90), today
    elif preset == "Year to Date":
        preset_start = date(today.year, 1, 1)
        preset_end = today
    else:  # Custom — default to month-to-date as a starting point
        preset_start, preset_end = today.replace(day=1), today

    # Key includes the preset name so the widget refreshes when preset changes
    date_range = st.date_input(
        "Date range",
        value=(preset_start, preset_end),
        max_value=today,
        key=f"date_range_{preset}",
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
tab_executive, tab_sales, tab_metrics = st.tabs(
    ["EXECUTIVE", "SALES", "METRICS"])

with tab_executive:
    render_executive(start_date, end_date)

with tab_sales:
    render_sales(start_date, end_date)

with tab_metrics:
    render_metrics()
