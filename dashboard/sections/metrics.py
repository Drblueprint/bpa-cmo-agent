"""METRICS tab — 8-week scoreboard grid."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
    load_meetings_for_contacts,
    load_contacts_by_ids,
)
from dashboard.data.hubspot_forms_loader import load_form_submissions
from dashboard.data.reconcile import weekly_metrics


def _week_ranges(weeks_back: int) -> list[tuple[date, date]]:
    """Return Mon->Sun ranges for the last N weeks, NEWEST FIRST.

    Index 0 = current week, index 1 = one week back, etc.
    """
    today = date.today()
    # Find this week's Monday (Mon=0..Sun=6)
    this_monday = today - timedelta(days=today.weekday())
    ranges = []
    for i in range(weeks_back):
        start = this_monday - timedelta(days=7 * i)
        end = start + timedelta(days=6)
        ranges.append((start, end))
    return ranges


def _fmt_money(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    try:
        return f"{int(x):,}"
    except (ValueError, TypeError):
        return "—"


def _money_metric_ids() -> set[str]:
    return {"chiro_ad_spend", "chiro_cpc", "pt_ad_spend", "pt_cpc",
            "theraray_ad_spend", "emx_ad_spend"}


def render_metrics() -> None:
    ranges = _week_ranges(cfg.METRICS_WEEKS_BACK)
    # ranges[0] = newest week, ranges[-1] = oldest week
    overall_start = ranges[-1][0]   # oldest week start
    overall_end = ranges[0][1]      # newest week end

    st.subheader("BPA Weekly Metrics")
    st.caption(
        f"{cfg.METRICS_WEEKS_BACK}-week rolling view · Newest week ending "
        f"{ranges[0][1].strftime('%b')} {ranges[0][1].day}, {ranges[0][1].year} · "
        f"oldest week starting {ranges[-1][0].strftime('%b')} {ranges[-1][0].day}"
    )

    # --- Data loaders, each in its own try/except ---
    try:
        fb = load_fb_insights(overall_start, overall_end, time_increment_days=7)
    except Exception as e:
        st.warning(f"FB Ads unavailable: {e}")
        fb = pd.DataFrame(columns=["campaign_name", "group", "spend",
                                   "impressions", "clicks", "fb_leads",
                                   "date_start", "date_stop"])
    try:
        contacts = load_marketing_contacts(overall_start, overall_end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        contacts = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(overall_start, overall_end)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()
    try:
        meetings = load_meetings_for_contacts(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])
    try:
        bofu = load_form_submissions(cfg.BOFU_FORM_IDS, overall_start, overall_end)
    except Exception as e:
        st.warning(f"HubSpot Forms (BOFU) unavailable: {e}")
        bofu = pd.DataFrame(columns=["form_id", "submission_id", "submitted_at", "email"])

    # Closed-deal attribution lookup for long sales cycles
    try:
        if not deals.empty and not contact_deals.empty:
            won_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_CLOSED_WON), "deal_id"])
            won_contact_ids = set(
                contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"].astype(str)
            )
            known_ids = set(contacts["hs_id"].astype(str)) if not contacts.empty else set()
            missing_ids = list(won_contact_ids - known_ids)
            if missing_ids:
                extra = load_contacts_by_ids(missing_ids)
                if not extra.empty:
                    contacts = pd.concat([contacts, extra], ignore_index=True)
    except Exception as e:
        st.warning(f"Closed-deal attribution lookup failed: {e}")

    metrics = weekly_metrics(
        fb=fb, contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals, bofu_submissions=bofu,
        week_ranges=ranges,
        asset_to_group=cfg.ASSET_TO_GROUP,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        goals=cfg.METRICS_GOALS,
    )

    if metrics.empty:
        st.info("No metric data to display.")
        return

    # --- Spike detection: warn if any New Leads week is 5x+ the median ---
    chiro_new_row = metrics[metrics["metric_id"] == "chiro_new_leads"]
    pt_new_row = metrics[metrics["metric_id"] == "pt_new_leads"]
    week_cols = [c for c in metrics.columns if c.startswith("w")]

    def _has_spike(row_df) -> bool:
        if row_df.empty:
            return False
        vals = [float(row_df.iloc[0][c]) for c in week_cols]
        nonzero = [v for v in vals if v > 0]
        if len(nonzero) < 3:
            return False
        nonzero_sorted = sorted(nonzero)
        median = nonzero_sorted[len(nonzero_sorted) // 2]
        return any(v >= 5 * median for v in vals)

    if _has_spike(chiro_new_row) or _has_spike(pt_new_row):
        st.info(
            "One or more weeks show a New Leads count far above the others. "
            "This is real data, not a calculation bug - most likely a HubSpot "
            "bulk import or a workflow that retroactively stamped "
            "`typeform_submission_date` on historical contacts. The other weekly "
            "numbers are accurate.",
            icon="ℹ️",
        )

    # --- Format the grid for display ---
    money_ids = _money_metric_ids()
    week_cols = [c for c in metrics.columns if c.startswith("w")]
    display = metrics.copy()

    # Rename week columns to date labels
    week_labels = [f"{ws.strftime('%b')} {ws.day} – {we.day}" for (ws, we) in ranges]
    rename_weeks = {f"w{i}": week_labels[i] for i in range(len(ranges))}

    # Format each row's values according to metric type
    def _fmt_cell(metric_id: str, value, *, is_goal: bool = False) -> str:
        if value is None or pd.isna(value):
            return "—"
        if metric_id in money_ids:
            return _fmt_money(value)
        if is_goal:
            if metric_id in money_ids:
                return f">= {_fmt_money(value)}"
            return f">= {_fmt_int(value)}"
        return _fmt_int(value)

    # Build a new DataFrame with formatted strings
    formatted_rows = []
    for _, row in display.iterrows():
        mid = row["metric_id"]
        out = {
            "Metric": row["metric_label"],
            "Goal": _fmt_cell(mid, row["goal"], is_goal=True),
        }
        for i, label in enumerate(week_labels):
            out[label] = _fmt_cell(mid, row[f"w{i}"])
        formatted_rows.append(out)

    formatted_df = pd.DataFrame(formatted_rows)
    st.dataframe(formatted_df, use_container_width=True, hide_index=True)
