"""SALES tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import config as cfg
from dashboard.data.aircall_loader import load_aircall_calls
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
    load_meetings_for_contacts,
)
from dashboard.data.reconcile import (
    compute_speed_to_lead,
    owner_rollup,
    pipeline_funnel,
    sdr_call_activity,
)


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
    try:
        aircall_calls = load_aircall_calls(start, end)
    except Exception as e:
        st.warning(f"AirCall unavailable: {e}")
        aircall_calls = pd.DataFrame(columns=[
            "call_id", "started_at_utc", "answered_at_utc", "duration",
            "direction", "status", "user_id", "user_name",
            "raw_digits", "phone_normalized",
        ])
    try:
        meetings = load_meetings_for_contacts(marketing["hs_id"].tolist()) \
            if not marketing.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])

    # Closed-deal attribution: pull any contact tied to a closed-won deal in
    # the window who isn't already in our fresh-leads pull. Sales cycles can
    # be 3-6 months; this preserves asset attribution for long-cycle closes.
    try:
        from dashboard.data.hubspot_loader import load_contacts_by_ids
        if not deals.empty and not contact_deals.empty:
            won_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_CLOSED_WON), "deal_id"])
            won_contact_ids = set(
                contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"].astype(str)
            )
            known_ids = set(marketing["hs_id"].astype(str)) if not marketing.empty else set()
            missing_ids = list(won_contact_ids - known_ids)
            if missing_ids:
                extra = load_contacts_by_ids(missing_ids)
                if not extra.empty:
                    marketing = pd.concat([marketing, extra], ignore_index=True)
    except Exception as e:
        st.warning(f"Closed-deal attribution lookup failed: {e}")

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

    # === NEW: Speed to Lead KPI row ===
    st.divider()
    st.subheader("Speed to Lead")
    speed_df = compute_speed_to_lead(marketing, aircall_calls)
    speeds = speed_df["speed_to_lead_minutes"].dropna()

    if speeds.empty:
        median_speed = None
        pct_under_5 = None
        pct_under_60s = None
    else:
        median_speed = float(speeds.median())
        pct_under_5 = float((speeds <= 5).mean())
        pct_under_60s = float((speeds <= 1).mean())

    s1, s2, s3 = st.columns(3)
    s1.metric(
        "Median Speed to Lead",
        f"{median_speed:.1f} min" if median_speed is not None else "—",
        help="Median minutes from HubSpot lead created to first outbound AirCall.")
    s2.metric(
        "% Under 5 min",
        f"{pct_under_5*100:.0f}%" if pct_under_5 is not None else "—",
        help="Share of leads whose first outbound call landed within 5 minutes "
             "of creation. Hormozi's 80% target.")
    s3.metric(
        "% Under 60 sec",
        f"{pct_under_60s*100:.0f}%" if pct_under_60s is not None else "—",
        help="Share within 60 seconds. Hormozi's stretch goal (50%).")

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
        sdr["owner"] = sdr["owner"].map(cfg.resolve_owner)
        st.dataframe(sdr, use_container_width=True, hide_index=True)

    with col_bds:
        st.subheader("By BDS")
        bds = owner_rollup(contacts_view, contact_deals, deals,
                           owner_field="bds", stage_groups=stages)
        bds["owner"] = bds["owner"].map(cfg.resolve_owner)
        st.dataframe(bds, use_container_width=True, hide_index=True)

    st.divider()

    # === NEW: SDR Call Activity table ===
    st.subheader("SDR Call Activity (AirCall)")
    st.caption("Outbound dial volume + connect rate + speed metrics per SDR. "
               "A 'connect' is an outbound call where the prospect answered "
               f"and the call lasted at least {cfg.AIRCALL_CONNECT_DURATION_SEC} seconds.")
    activity = sdr_call_activity(
        contacts=marketing,
        calls=aircall_calls,
        meetings=meetings,
        aircall_user_names=cfg.AIRCALL_USER_NAMES,
        excluded_users=cfg.AIRCALL_EXCLUDED_USERS,
        connect_duration_sec=cfg.AIRCALL_CONNECT_DURATION_SEC,
        conv_window_hours=cfg.AIRCALL_CONV_TO_DISCO_WINDOW_HOURS,
    )

    if activity.empty:
        st.info("No AirCall data in this window.")
    else:
        display = activity.copy()
        display["connect_rate"] = display["connect_rate"].map(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) and x is not None else "—"
        )
        display["conv_to_discovery_rate"] = display["conv_to_discovery_rate"].map(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) and x is not None else "—"
        )
        display["talk_time_min"] = display["talk_time_min"].map(
            lambda x: f"{x:.0f}" if pd.notna(x) else "—"
        )
        display["median_speed_to_lead_min"] = display["median_speed_to_lead_min"].map(
            lambda x: f"{x:.1f} min" if pd.notna(x) and x is not None else "—"
        )
        display = display[[
            "user_name", "dials", "connects", "connect_rate",
            "talk_time_min", "conv_to_discovery_rate", "median_speed_to_lead_min",
        ]].rename(columns={
            "user_name": "SDR",
            "dials": "Dials",
            "connects": "Connects",
            "connect_rate": "Connect %",
            "talk_time_min": "Talk Time (min)",
            "conv_to_discovery_rate": "Conv → Discovery %",
            "median_speed_to_lead_min": "Median Speed to Lead",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

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
    detail["sdr_owner"] = detail["sdr_owner"].map(cfg.resolve_owner)
    detail["bds"] = detail["bds"].map(cfg.resolve_owner)
    detail["hubspot_link"] = detail["hs_id"].apply(cfg.hubspot_contact_url)
    detail = detail[[
        "hubspot_link",
        "name", "email", "typeform_asset_download", "typeform_submission_date",
        "fifteen_min_call_date", "lifecycle_stage",
        "sdr_owner", "bds", "dealstage", "amount",
    ]].rename(columns={
        "hubspot_link": "Open",
        "typeform_asset_download": "Asset",
        "typeform_submission_date": "Submitted",
        "fifteen_min_call_date": "15-min Call Date",
        "lifecycle_stage": "Lifecycle",
        "sdr_owner": "SDR Owner",
        "bds": "BDS",
        "dealstage": "Current Stage",
        "amount": "Deal $",
    })
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Open": st.column_config.LinkColumn(
                "Open",
                help="Open contact in HubSpot",
                display_text="HubSpot ↗",
            ),
        },
    )
