"""MARKETING tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
)
from dashboard.data.hyros_loader import load_hyros_leads
from dashboard.data.reconcile import (
    group_marketing_metrics,
    reconciliation_panel,
)


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
    )

    # --- Top-row KPIs ---
    total_spend = metrics["spend"].sum()
    total_leads = metrics["leads"].sum()
    total_booked = metrics["calls_booked"].sum()
    cpl = (total_spend / total_leads) if total_leads else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ad Spend", _fmt_money(total_spend))
    c2.metric("Marketing Leads", _fmt_int(total_leads))
    c3.metric("CPL", _fmt_money(cpl))
    c4.metric("15-min Calls Booked", _fmt_int(total_booked))

    st.divider()

    # --- Section A: campaign group table ---
    st.subheader("By Campaign Group")
    display = metrics.copy()
    display["spend"] = display["spend"].map(_fmt_money)
    display["cpl"] = display["cpl"].map(_fmt_money)
    display["cost_per_qualified_call"] = display["cost_per_qualified_call"].map(_fmt_money)
    display["leads"] = display["leads"].map(_fmt_int)
    display["calls_booked"] = display["calls_booked"].map(_fmt_int)
    display = display.rename(columns={
        "group": "Group",
        "spend": "Spend",
        "leads": "Leads",
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

    # --- Section B: reconciliation panel ---
    st.subheader("Lead Reconciliation (diagnostic)")
    recon = reconciliation_panel(fb, contacts, hyros,
                                  asset_to_group=cfg.ASSET_TO_GROUP)
    if not recon.empty:
        recon_display = recon.copy()
        recon_display["match_rate"] = recon_display["match_rate"].map(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) else "—"
        )
        recon_display = recon_display.rename(columns={
            "group": "Group", "fb_leads": "FB", "hyros_leads": "Hyros",
            "hubspot_leads": "HubSpot (truth)", "match_rate": "Hyros↔HubSpot",
        })
        st.dataframe(recon_display, use_container_width=True, hide_index=True)
    st.caption("HubSpot is the headline number above. FB and Hyros shown here "
               "for cross-check only.")

    st.divider()

    # --- Section C: trend chart ---
    st.subheader("Leads & Spend Over Time")
    if not contacts.empty and not fb.empty:
        trend = contacts.copy()
        trend["created_date"] = pd.to_datetime(trend["created"]).dt.date
        trend["group"] = trend["typeform_asset_download"].map(cfg.ASSET_TO_GROUP)
        daily_leads = trend.groupby(["created_date", "group"]).size().reset_index(name="leads")
        fig = px.bar(daily_leads, x="created_date", y="leads", color="group",
                     title="Marketing leads per day by group")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data to plot for selected window.")
