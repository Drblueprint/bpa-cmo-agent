"""SALES tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import config as cfg
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
)
from dashboard.data.reconcile import owner_rollup, pipeline_funnel


def _fmt_money(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def _stage_groups() -> dict[str, set[str]]:
    return {
        "15min_booked":    cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        "15min_held":      cfg.STAGES_15MIN_HELD,
        "strategy_booked": cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
        "strategy_held":   cfg.STAGES_STRATEGY_HELD,
        "closedwon":       cfg.STAGES_CLOSED_WON,
    }


def render_sales(start: date, end: date) -> None:
    st.info(
        '**"Marketing-attributed"** below = HubSpot contact has '
        '`typeform_asset_download` populated.',
        icon="ℹ️",
    )

    try:
        marketing = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        marketing = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(marketing["hs_id"].tolist()) \
            if not marketing.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(start, end)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()

    stages = _stage_groups()

    fn_mkt = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=True)
    fn_all = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)

    # --- KPIs ---
    def _v(df, stage, col="count"):
        s = df.loc[df["stage"] == stage, col]
        return s.iloc[0] if not s.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("15-min Calls (Marketing)", _fmt_int(_v(fn_mkt, "15-min Booked")))
    c2.metric("15-min Calls (All)", _fmt_int(_v(fn_all, "15-min Booked")))
    c3.metric("Strategy Calls Held (Mkt)", _fmt_int(_v(fn_mkt, "Strategy Held")))
    c4.metric(
        "Closed-Won (Marketing)",
        f"{_fmt_int(_v(fn_mkt, 'Closed-Won'))} · "
        f"{_fmt_money(_v(fn_mkt, 'Closed-Won', 'revenue'))}",
    )

    st.divider()

    # --- Section A: pipeline funnel ---
    st.subheader("Pipeline Funnel")
    combined = fn_mkt.rename(columns={"count": "Marketing", "revenue": "mkt_rev"}).merge(
        fn_all.rename(columns={"count": "All Sources", "revenue": "all_rev"}),
        on="stage",
    )
    show = combined[["stage", "Marketing", "All Sources"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_trace(go.Funnel(name="Marketing", y=combined["stage"],
                            x=combined["Marketing"]))
    fig.add_trace(go.Funnel(name="All", y=combined["stage"],
                            x=combined["All Sources"]))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Section B: owner breakdowns ---
    col_sdr, col_bds = st.columns(2)

    only_mkt = st.checkbox("Marketing-attributed only", value=True,
                            key="owners_marketing_only")
    # v1 only loads marketing-attributed contacts; the "All" branch is a placeholder
    # for a future enhancement that loads all contacts.
    contacts_view = marketing

    with col_sdr:
        st.subheader("By SDR Owner")
        sdr = owner_rollup(contacts_view, contact_deals, deals,
                           owner_field="sdr_owner", stage_groups=stages)
        st.dataframe(sdr, use_container_width=True, hide_index=True)

    with col_bds:
        st.subheader("By BDS")
        bds = owner_rollup(contacts_view, contact_deals, deals,
                           owner_field="bds", stage_groups=stages)
        st.dataframe(bds, use_container_width=True, hide_index=True)

    st.divider()

    # --- Section C: drill-down ---
    st.subheader("Marketing Lead Detail")
    if marketing.empty:
        st.info("No marketing leads in this window.")
        return
    if deals.empty or contact_deals.empty:
        st.info("No deal data available — drill-down hidden.")
        return

    deals_by_contact = contact_deals.merge(
        deals[["deal_id", "dealstage", "amount", "createdate"]],
        on="deal_id", how="left",
    )
    latest_deal = (
        deals_by_contact.sort_values("createdate", ascending=False)
        .drop_duplicates("contact_id")
        .rename(columns={"contact_id": "hs_id"})
    )
    detail = marketing.merge(
        latest_deal[["hs_id", "dealstage", "amount"]],
        on="hs_id", how="left",
    )
    detail = detail[[
        "name", "email", "typeform_asset_download", "typeform_submission_date",
        "fifteen_min_call_date", "lifecycle_stage",
        "sdr_owner", "bds", "dealstage", "amount",
    ]].rename(columns={
        "typeform_asset_download": "Asset",
        "typeform_submission_date": "Submitted",
        "fifteen_min_call_date": "15-min Call Date",
        "lifecycle_stage": "Lifecycle",
        "sdr_owner": "SDR Owner",
        "bds": "BDS",
        "dealstage": "Current Stage",
        "amount": "Deal $",
    })
    st.dataframe(detail, use_container_width=True, hide_index=True)
