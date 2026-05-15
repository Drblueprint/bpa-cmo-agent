"""MARKETING tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
)
from dashboard.data.hyros_loader import load_hyros_leads
from dashboard.data.reconcile import group_marketing_metrics


def _fmt_money(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def render_marketing(start: date, end: date) -> None:
    try:
        fb = load_fb_insights(start, end)
    except Exception as e:
        st.warning(f"FB Ads unavailable: {e}")
        fb = pd.DataFrame(columns=["campaign_name", "group", "spend",
                                   "impressions", "clicks", "fb_leads"])
    try:
        contacts = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        contacts = pd.DataFrame()
    try:
        hyros = load_hyros_leads(start, end)
    except Exception as e:
        st.warning(f"Hyros unavailable: {e}")
        hyros = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(start, end)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()

    metrics = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=cfg.ASSET_TO_GROUP,
        stages_15min_booked=cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        hyros=hyros,
    )

    # --- Top-row KPIs ---
    total_spend = metrics["spend"].sum()
    total_marketing_leads = metrics["marketing_leads"].sum()
    total_booked = metrics["calls_booked"].sum()
    cpl = (total_spend / total_marketing_leads) if total_marketing_leads else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ad Spend", _fmt_money(total_spend))
    c2.metric("Marketing Leads", _fmt_int(total_marketing_leads),
              help="HubSpot contacts whose typeform was submitted in the window. "
                   "Source of truth - anyone who filled the typeform is a marketing "
                   "lead. Falls back to FB lead count for groups that don't use a "
                   "typeform (e.g., TheraRay).")
    c3.metric("CPL", _fmt_money(cpl),
              help="Spend / Marketing Leads")
    c4.metric("15-min Calls Booked", _fmt_int(total_booked),
              help="Contacts with a 15 Min Call Date set OR lifecycle = MQL.")

    st.divider()

    # --- Section A: campaign group table ---
    st.subheader("By Campaign Group")
    display = metrics.copy()

    def _fmt_marketing_leads(row) -> str:
        v = row["marketing_leads"]
        if v is None or pd.isna(v):
            return "—"
        if row["marketing_leads_source"] == "fb":
            return f"{int(v):,} (FB)"
        if row["marketing_leads_source"] == "typeform":
            return f"{int(v):,}"
        return "—"

    display["marketing_leads"] = display.apply(_fmt_marketing_leads, axis=1)
    display["spend"] = display["spend"].map(_fmt_money)
    display["cpl"] = display["cpl"].map(_fmt_money)
    display["cost_per_qualified_call"] = display["cost_per_qualified_call"].map(_fmt_money)
    display["calls_booked"] = display["calls_booked"].map(_fmt_int)

    display = display[["group", "spend", "marketing_leads", "cpl",
                       "calls_booked", "cost_per_qualified_call"]]

    display = display.rename(columns={
        "group": "Group",
        "spend": "Spend",
        "marketing_leads": "Marketing Leads",
        "cpl": "CPL",
        "calls_booked": "15-min Calls",
        "cost_per_qualified_call": "Cost / Qualified Call",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Unmatched campaigns warning
    unmatched = fb[fb["group"].isna()]
    if not unmatched.empty:
        with st.expander(f"⚠️ {len(unmatched)} unmatched campaign(s) — review naming"):
            st.dataframe(unmatched[["campaign_name", "spend", "fb_leads"]],
                         hide_index=True)

    st.divider()

    # --- Section C: per-lead detail ---
    st.subheader("Marketing Lead Detail")
    if contacts.empty:
        st.info("No marketing leads in this window.")
    else:
        detail = contacts.copy()
        detail["group"] = detail["typeform_asset_download"].map(cfg.ASSET_TO_GROUP)
        detail["sdr_owner"] = detail["sdr_owner"].map(cfg.resolve_owner)

        # Convert UTC ISO timestamps to America/Chicago, MM/DD/YYYY hh:mm AM/PM.
        # Use errors="coerce" so unparseable values become NaT instead of raising.
        submitted_utc = pd.to_datetime(
            detail["typeform_submission_date"], utc=True, errors="coerce"
        )
        submitted_cst = submitted_utc.dt.tz_convert("America/Chicago")
        detail["typeform_submission_date"] = submitted_cst.apply(
            lambda x: x.strftime("%m/%d/%Y %I:%M %p") if pd.notna(x) else ""
        )

        # 15-min call indicator: "Scheduled" if call date is set OR lifecycle = MQL.
        has_call_date = detail["fifteen_min_call_date"].fillna("").astype(str).str.strip() != ""
        is_mql = detail["lifecycle_stage"].fillna("").astype(str).str.lower() == "marketingqualifiedlead"
        detail["fifteen_min_status"] = (has_call_date | is_mql).map(
            lambda x: "Scheduled" if x else ""
        )

        detail = detail[[
            "name", "email", "group", "typeform_asset_download",
            "typeform_submission_date", "sdr_owner", "fifteen_min_status",
        ]].rename(columns={
            "name": "Name",
            "email": "Email",
            "group": "Group",
            "typeform_asset_download": "Asset",
            "typeform_submission_date": "Submitted (CT)",
            "sdr_owner": "SDR Owner",
            "fifteen_min_status": "15-min Call",
        })
        st.dataframe(detail, use_container_width=True, hide_index=True)
