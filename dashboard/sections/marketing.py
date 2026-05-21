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
    load_meetings_for_contacts,
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
    floor_days = st.session_state.get("data_floor_days_back", 180)
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
    # Pull TheraRay-attributed contacts via HubSpot list 6280.
    # Filter by `membershipTimestamp` (when they joined the list), NOT contact
    # createdate — some TheraRay leads are pre-existing contacts who recently
    # filled the TheraRay form.
    theraray_contacts = pd.DataFrame()
    try:
        from dashboard.data.hubspot_loader import (
            load_list_memberships,
            load_contacts_by_ids,
        )
        memberships = load_list_memberships(cfg.THERARAY_HUBSPOT_LIST_ID)
        if not memberships.empty:
            # Filter memberships to the dashboard window first
            mt = pd.to_datetime(memberships["membership_timestamp"],
                                 utc=True, errors="coerce")
            start_ts = pd.Timestamp(year=start.year, month=start.month,
                                     day=start.day, tz="UTC")
            end_ts = pd.Timestamp(year=end.year, month=end.month,
                                   day=end.day, tz="UTC") + pd.Timedelta(days=1)
            in_window = memberships[(mt >= start_ts) & (mt < end_ts)]
            window_ids = in_window["contact_id"].tolist()
            if window_ids:
                theraray_contacts = load_contacts_by_ids(window_ids)
                if not theraray_contacts.empty:
                    # Apply marketing exclusion list
                    theraray_contacts = theraray_contacts[
                        ~theraray_contacts["email"].fillna("").str.lower()
                        .isin(cfg.MARKETING_EXCLUDED_EMAILS)
                    ].copy()
                if not theraray_contacts.empty:
                    # Join membership timestamp onto contacts so we can use it
                    # as the "submitted" date instead of stale createdate
                    ts_map = dict(zip(in_window["contact_id"].astype(str),
                                      in_window["membership_timestamp"]))
                    theraray_contacts = theraray_contacts.copy()
                    theraray_contacts["typeform_asset_download"] = "TheraRay FB Lead"
                    # Override typeform_submission_date with the membership
                    # timestamp so the "Submitted (CT)" column shows the right value
                    theraray_contacts["typeform_submission_date"] = (
                        theraray_contacts["hs_id"].astype(str).map(ts_map)
                    )
                    cfg.ASSET_TO_GROUP["TheraRay FB Lead"] = "TheraRay"
    except Exception as e:
        st.warning(f"TheraRay contacts unavailable: {e}")

    # Merge into the main contacts dataframe (deduplicate by hs_id)
    if not theraray_contacts.empty:
        if contacts.empty:
            contacts = theraray_contacts
        else:
            combined = pd.concat([contacts, theraray_contacts], ignore_index=True)
            contacts = combined.drop_duplicates(subset="hs_id", keep="first").reset_index(drop=True)

    try:
        contact_deals = load_contact_deals(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(start, end, data_floor_days_back=floor_days)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()
    try:
        meetings = load_meetings_for_contacts(contacts["hs_id"].tolist(),
                                              data_floor_days_back=floor_days) \
            if not contacts.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])

    metrics = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=cfg.ASSET_TO_GROUP,
        stages_15min_booked=cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        hyros=hyros,
        stages_strategy=cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        meetings=meetings,
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

    def _fmt_won(row) -> str:
        n = row["closed_won"]
        rev = row["closed_won_revenue"]
        if n is None or pd.isna(n) or int(n) == 0:
            return "—"
        return f"{int(n):,} · ${float(rev):,.0f}"

    display["marketing_leads"] = display.apply(_fmt_marketing_leads, axis=1)
    display["closed_won_display"] = display.apply(_fmt_won, axis=1)
    display["spend"] = display["spend"].map(_fmt_money)
    display["cpl"] = display["cpl"].map(_fmt_money)
    display["cost_per_qualified_call"] = display["cost_per_qualified_call"].map(_fmt_money)
    display["calls_booked"] = display["calls_booked"].map(_fmt_int)
    display["strategy_calls"] = display["strategy_calls"].map(_fmt_int)

    display = display[["group", "spend", "marketing_leads", "cpl",
                       "calls_booked", "strategy_calls", "closed_won_display",
                       "cost_per_qualified_call"]]

    display = display.rename(columns={
        "group": "Group",
        "spend": "Spend",
        "marketing_leads": "Marketing Leads",
        "cpl": "CPL",
        "calls_booked": "15-min Calls",
        "strategy_calls": "Strategy Calls",
        "closed_won_display": "Closed Won",
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

        # Default sort: newest typeform submission first
        detail["_sort_ts"] = pd.to_datetime(
            detail["typeform_submission_date"], utc=True, errors="coerce"
        )
        detail = detail.sort_values("_sort_ts", ascending=False, na_position="last")
        detail = detail.drop(columns=["_sort_ts"])

        detail["group"] = detail["typeform_asset_download"].map(cfg.ASSET_TO_GROUP)
        detail["sdr_owner"] = detail["sdr_owner"].map(cfg.resolve_owner)

        detail["typeform_submission_date"] = cfg.format_ct_series(
            detail["typeform_submission_date"]
        )

        from dashboard.data.reconcile import per_contact_journey
        journey = per_contact_journey(
            contacts, meetings, contact_deals, deals,
            stages_closed_won=cfg.STAGES_CLOSED_WON,
        )
        detail = detail.merge(journey, on="hs_id", how="left")
        detail[["fifteen_min_status", "strategy_status", "closed_won"]] = \
            detail[["fifteen_min_status", "strategy_status", "closed_won"]].fillna("")

        detail["hubspot_link"] = detail["hs_id"].apply(cfg.hubspot_contact_url)
        detail = detail[[
            "hubspot_link",
            "name", "email", "group", "typeform_asset_download",
            "typeform_submission_date", "sdr_owner",
            "fifteen_min_status", "strategy_status", "closed_won",
        ]].rename(columns={
            "hubspot_link": "Open",
            "name": "Name",
            "email": "Email",
            "group": "Group",
            "typeform_asset_download": "Asset",
            "typeform_submission_date": "Submitted (CT)",
            "sdr_owner": "SDR Owner",
            "fifteen_min_status": "15-min Call",
            "strategy_status": "Strategy Call",
            "closed_won": "Closed Won",
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
