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
        hyros=hyros,
    )

    # --- Top-row KPIs ---
    total_spend = metrics["spend"].sum()
    total_marketing_leads = metrics["marketing_leads"].sum()
    total_hyros = metrics["hyros_leads"].sum()
    total_booked = metrics["calls_booked"].sum()
    cpl = (total_spend / total_marketing_leads) if total_marketing_leads else None

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Ad Spend", _fmt_money(total_spend))
    c2.metric("Marketing Leads", _fmt_int(total_marketing_leads),
              help="HubSpot contacts whose typeform was submitted in the window. "
                   "Source of truth - anyone who filled the typeform is a marketing "
                   "lead. Falls back to FB lead count for groups that don't use a "
                   "typeform (e.g., TheraRay).")
    c3.metric("CPL", _fmt_money(cpl),
              help="Spend / Marketing Leads")
    c4.metric("Ad Clicks Tracked (Hyros)", _fmt_int(total_hyros),
              help="Ad clicks Hyros could fully attribute to a paid source. "
                   "Lower than Marketing Leads when UTMs are stripped or "
                   "attribution breaks - diagnostic, not source of truth.")
    c5.metric("15-min Calls Booked", _fmt_int(total_booked),
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
    display["hyros_leads"] = display["hyros_leads"].map(
        lambda x: "—" if (x is None or pd.isna(x) or x == 0) else f"{int(x):,}"
    )

    display = display[["group", "spend", "marketing_leads", "cpl",
                       "hyros_leads", "calls_booked", "cost_per_qualified_call"]]

    display = display.rename(columns={
        "group": "Group",
        "spend": "Spend",
        "marketing_leads": "Marketing Leads",
        "cpl": "CPL",
        "hyros_leads": "Ad Clicks (Hyros)",
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
    st.caption(
        "**Marketing Leads** above is the source of truth (anyone who submitted "
        "the typeform). The reconciliation table below cross-checks against FB's "
        "pixel-reported figure and Hyros's tracked attributions - gaps indicate "
        "UTM tracking issues (currently: HubSpot calendar thank-you page isn't "
        "passing UTMs through), not missing leads."
    )

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
