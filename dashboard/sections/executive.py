"""EXECUTIVE tab rendering — 3-row funnel view + per-rep tables."""
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
    load_contacts_by_ids,
    load_closed_deals_ytd,
)
from dashboard.data.reconcile import (
    executive_kpis,
    executive_sdr_rollup,
    executive_sme_rollup,
    build_closed_deals_table,
    compute_ytd_money,
)


def _fmt_money(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def _fmt_pct(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:.0f}%"


def _fmt_days(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x)} days"


def render_executive(start: date, end: date) -> None:
    floor_days = st.session_state.get("data_floor_days_back", 90)
    # --- Group filter (inside the tab, not global) ---
    group_filter = st.radio(
        "Group",
        ["All", "Chiro", "PT Recovery", "TheraRay", "EMX"],
        horizontal=True,
        key="executive_group_filter",
    )
    st.divider()

    # --- Load data (try/except per source) ---
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
            known_ids = set(contacts["hs_id"].astype(str)) if not contacts.empty else set()
            missing_ids = list(won_contact_ids - known_ids)
            if missing_ids:
                extra = load_contacts_by_ids(missing_ids)
                if not extra.empty:
                    contacts = pd.concat([contacts, extra], ignore_index=True)
    except Exception as e:
        st.warning(f"Closed-deal attribution lookup failed: {e}")

    # === YTD closed-deal data (separate pull -- always Jan 1 -> today) ===
    try:
        deals_ytd, contact_deals_ytd, contacts_ytd = load_closed_deals_ytd(
            closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
        )
    except Exception as e:
        st.warning(f"YTD closed deals unavailable: {e}")
        deals_ytd = pd.DataFrame()
        contact_deals_ytd = pd.DataFrame(columns=["contact_id", "deal_id"])
        contacts_ytd = pd.DataFrame()

    ytd_money = compute_ytd_money(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
    )

    kpis = executive_kpis(
        fb=fb, contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        group_filter=group_filter,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        sdr_payroll_monthly=cfg.SDR_PAYROLL_MONTHLY,
        sme_payroll_monthly=cfg.SME_PAYROLL_MONTHLY,
    )

    # === ROW 1 — INPUTS ===
    st.subheader("Inputs")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Ad Spend", _fmt_money(kpis["total_ad_spend"]))
    c2.metric("New Leads", _fmt_int(kpis["new_leads"]),
              help="Marketing-attributed contacts with typeform submitted in window. "
                   "FB lead count is used as a fallback for groups that don't use a typeform.")
    c3.metric("Engaged Leads (MQL+)", _fmt_int(kpis["engaged_leads"]),
              help="Leads whose HubSpot lifecycle stage has reached "
                   "Marketing Qualified Lead or beyond.")
    c4.metric("CPL", _fmt_money(kpis["cpl"]), help="Spend / New Leads")
    c5.metric("Cost / Engaged Lead", _fmt_money(kpis["cost_per_engaged_lead"]),
              help="Spend / Engaged Leads. Hormozi prefers this over raw CPL "
                   "because it weights for quality.")

    st.divider()

    # === ROW 2 — CONVERSIONS ===
    st.subheader("Conversions")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Schedule Rate", _fmt_pct(kpis["schedule_rate"]),
              delta=f"{kpis['discovery_booked']} / {kpis['new_leads']}",
              delta_color="off",
              help="Discovery (15-min) calls booked ÷ New Leads. Phase A definition; "
                   "will upgrade to leads-worked denominator in Phase B with AirCall data.")
    c2.metric("Discovery Show %", _fmt_pct(kpis["discovery_show_rate"]),
              delta=f"{kpis['discovery_held']} / {kpis['discovery_booked']}",
              delta_color="off",
              help="15-min meetings that COMPLETED ÷ total 15-min meetings.")
    c3.metric("Disco → SME Set %", _fmt_pct(kpis["sme_set_rate"]),
              delta=f"{kpis['sme_booked']} / {kpis['discovery_held']}",
              delta_color="off",
              help="Strategy meetings booked ÷ Discovery meetings completed.")
    c4.metric("SME Show %", _fmt_pct(kpis["sme_show_rate"]),
              delta=f"{kpis['sme_held']} / {kpis['sme_booked']}",
              delta_color="off",
              help="Strategy meetings COMPLETED ÷ Strategy meetings booked.")
    c5.metric("Close Rate", _fmt_pct(kpis["close_rate"]),
              delta=f"{kpis['closed_won']} / {kpis['sme_held']}",
              delta_color="off",
              help="Closed-won deals ÷ Strategy meetings completed.")

    st.divider()

    # === ROW 3 — MONEY ===
    st.subheader("Money")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("New Revenue", _fmt_money(kpis["new_revenue"]))
    c2.metric("Avg Deal Size", _fmt_money(kpis["avg_deal_size"]))
    cac_label = "CAC"
    cac_value = kpis["cac_full"] if kpis["cac_full"] is not None else kpis["cac_ad_only"]
    cac_help = "Customer Acquisition Cost."
    if kpis["cac_full"] is None:
        cac_label = "CAC (ad-only)"
        cac_help += " SDR / SME payroll not yet wired — actual CAC is higher."
    c3.metric(cac_label, _fmt_money(cac_value), help=cac_help)
    c4.metric("Sales Cycle", _fmt_days(kpis["sales_cycle_days"]),
              help="Median days from lead created to deal closed-won.")
    c5.metric("LTGP : CAC", "—",
              help="Phase C: needs retention + cost-to-serve data.")

    st.divider()

    # === MONEY — YEAR TO DATE ===
    st.subheader("Money — Year to Date (Total)")
    st.caption("All closed-won deals since Jan 1 — includes sales outreach and referrals.")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("New Revenue", _fmt_money(ytd_money["total_new_revenue"]))
    t2.metric("Avg Deal Size", _fmt_money(ytd_money["total_avg_deal_size"]))
    t3.metric("New Customers", _fmt_int(ytd_money["total_new_customers"]))
    t4.metric("Sales Cycle (median)",
              _fmt_days(ytd_money["total_sales_cycle_median"]),
              help="Median days from typeform submission to close. Excludes "
                   "non-marketing leads (no submission date).")

    st.subheader("Money — Year to Date (From Marketing)")
    st.caption("Subset: closed-won deals attributed to marketing efforts only.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Marketing Revenue", _fmt_money(ytd_money["mkt_new_revenue"]))
    m2.metric("Marketing Avg Deal", _fmt_money(ytd_money["mkt_avg_deal_size"]))
    m3.metric("Marketing Customers", _fmt_int(ytd_money["mkt_new_customers"]))
    m4.metric("Marketing Sales Cycle",
              _fmt_days(ytd_money["mkt_sales_cycle_median"]))

    st.divider()

    # === BY-REP TABLES ===
    contacts_for_reps = contacts.copy()
    if group_filter != "All" and not contacts_for_reps.empty:
        contacts_for_reps["group"] = contacts_for_reps["typeform_asset_download"] \
            .map(cfg.ASSET_TO_GROUP)
        contacts_for_reps = contacts_for_reps[contacts_for_reps["group"] == group_filter]

    # SDR table — full width
    st.subheader("SDR Performance")
    st.caption("SDR books the 15-min discovery call. Tracks: leads worked → "
               "discovery booked → discovery held.")
    sdr = executive_sdr_rollup(contacts_for_reps, meetings)
    if sdr.empty:
        st.info("No SDR data for this window.")
    else:
        sdr_display = sdr.copy()
        sdr_display["sdr_id"] = sdr_display["sdr_id"].map(cfg.resolve_owner)
        sdr_display["schedule_rate"] = sdr_display["schedule_rate"].map(_fmt_pct)
        sdr_display["show_rate"] = sdr_display["show_rate"].map(_fmt_pct)
        sdr_display = sdr_display.rename(columns={
            "sdr_id": "SDR Owner",
            "leads_worked": "Leads Worked",
            "discovery_booked": "Discovery Booked",
            "schedule_rate": "Schedule %",
            "discovery_held": "Discovery Held",
            "show_rate": "Show %",
        })
        st.dataframe(sdr_display, use_container_width=True, hide_index=True)

    st.divider()

    # BDS + SME side by side
    col_bds, col_sme = st.columns(2)

    with col_bds:
        st.subheader("BDS Performance")
        st.caption("BDS holds the 15-min and books the Strategy call. Tracks: "
                   "discovery held → strategy set → strategy held.")
        from dashboard.data.reconcile import executive_bds_rollup
        bds = executive_bds_rollup(contacts_for_reps, meetings)
        if bds.empty:
            st.info("No BDS data for this window.")
        else:
            bds_display = bds.copy()
            bds_display["bds_id"] = bds_display["bds_id"].map(cfg.resolve_owner)
            bds_display["set_rate"] = bds_display["set_rate"].map(_fmt_pct)
            bds_display["show_rate"] = bds_display["show_rate"].map(_fmt_pct)
            bds_display = bds_display.rename(columns={
                "bds_id": "BDS",
                "discovery_held": "Discovery Held",
                "strategy_booked": "Strategy Booked",
                "set_rate": "Set %",
                "strategy_held": "Strategy Held",
                "show_rate": "Show %",
            })
            st.dataframe(bds_display, use_container_width=True, hide_index=True)

    with col_sme:
        st.subheader("SME Performance")
        st.caption("SME holds the Strategy call and closes the deal. Tracks: "
                   "strategy held → deals closed → revenue.")
        sme = executive_sme_rollup(
            contacts_for_reps, meetings, contact_deals, deals,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            stages_closed_won=cfg.STAGES_CLOSED_WON,
        )
        if sme.empty:
            st.info("No SME data for this window.")
        else:
            sme_display = sme.copy()
            sme_display["sme_id"] = sme_display["sme_id"].map(cfg.resolve_owner)
            sme_display["close_rate"] = sme_display["close_rate"].map(_fmt_pct)
            sme_display["revenue"] = sme_display["revenue"].map(_fmt_money)
            sme_display["revenue_per_call"] = sme_display["revenue_per_call"].map(_fmt_money)
            sme_display = sme_display.rename(columns={
                "sme_id": "SME",
                "sme_calls_held": "Strategy Held",
                "deals_closed": "Deals Closed",
                "close_rate": "Close %",
                "revenue": "Revenue",
                "revenue_per_call": "Revenue / Call",
            })
            st.dataframe(sme_display, use_container_width=True, hide_index=True)

    # =============================================================
    # Per-call detail tables — every 15-min and Strategy call with
    # the assigned BDS / SME visible. Lets Dr. Gumm see who's on
    # which calls and which leads are in play.
    # =============================================================
    if not meetings.empty and not contacts_for_reps.empty:
        # Contact lookup with needed properties
        contact_lookup = contacts_for_reps[[
            "hs_id", "name", "email", "bds", "sme", "typeform_asset_download",
        ]].rename(columns={"hs_id": "contact_id"})
        contact_lookup["contact_id"] = contact_lookup["contact_id"].astype(str)

        meetings_x = meetings.copy()
        meetings_x["contact_id"] = meetings_x["contact_id"].astype(str)
        meetings_x = meetings_x.merge(contact_lookup, on="contact_id", how="inner")

        # Format start_time to Central Time
        st_dt = pd.to_datetime(meetings_x["start_time"], utc=True, errors="coerce")
        st_dt_ct = st_dt.dt.tz_convert("America/Chicago")
        meetings_x["scheduled_ct"] = st_dt_ct.apply(
            lambda x: x.strftime("%m/%d/%Y %I:%M %p") if pd.notna(x) else ""
        )

        types = meetings_x["activity_type"].fillna("").astype(str).str.lower()
        fifteen_detail = meetings_x[types.str.contains("15 min", na=False)].copy()
        strategy_detail = meetings_x[types.str.contains("strategy", na=False)].copy()

        st.divider()
        st.subheader("BDS Call Detail")
        st.caption("Every 15-min discovery call, with the BDS assigned to hold it.")
        if fifteen_detail.empty:
            st.info("No 15-min calls in this window.")
        else:
            fifteen_detail["bds"] = fifteen_detail["bds"].map(cfg.resolve_owner)
            fifteen_detail["hubspot_link"] = fifteen_detail["contact_id"].apply(cfg.hubspot_contact_url)
            fifteen_view = fifteen_detail[[
                "hubspot_link",
                "bds", "name", "email", "typeform_asset_download",
                "outcome", "scheduled_ct",
            ]].rename(columns={
                "hubspot_link": "Open",
                "bds": "BDS",
                "name": "Contact",
                "email": "Email",
                "typeform_asset_download": "Asset",
                "outcome": "Outcome",
                "scheduled_ct": "Scheduled (CT)",
            }).sort_values(["BDS", "Scheduled (CT)"], ascending=[True, False])
            st.dataframe(
                fifteen_view,
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

        st.divider()
        st.subheader("SME Call Detail")
        st.caption("Every Strategy call, with the SME assigned to hold it.")
        if strategy_detail.empty:
            st.info("No Strategy calls in this window.")
        else:
            strategy_detail["sme"] = strategy_detail["sme"].map(cfg.resolve_owner)
            strategy_detail["hubspot_link"] = strategy_detail["contact_id"].apply(cfg.hubspot_contact_url)
            strategy_view = strategy_detail[[
                "hubspot_link",
                "sme", "name", "email", "typeform_asset_download",
                "outcome", "scheduled_ct",
            ]].rename(columns={
                "hubspot_link": "Open",
                "sme": "SME",
                "name": "Contact",
                "email": "Email",
                "typeform_asset_download": "Asset",
                "outcome": "Outcome",
                "scheduled_ct": "Scheduled (CT)",
            }).sort_values(["SME", "Scheduled (CT)"], ascending=[True, False])
            st.dataframe(
                strategy_view,
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

    # === CLOSED DEALS (YTD) -- full detail ===
    st.divider()
    st.subheader("Closed Deals — Year to Date")
    st.caption("Every closed-won deal since Jan 1, with original asset attribution + sales cycle days.")
    deals_table = build_closed_deals_table(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
    )
    if deals_table.empty:
        st.info("No closed-won deals YTD.")
    else:
        # Filter toggle
        show_marketing_only = st.checkbox(
            "Show marketing-attributed deals only",
            value=False,
            key="closed_deals_marketing_filter",
        )
        if show_marketing_only and not deals_table.empty:
            deals_table = deals_table[deals_table["is_marketing"] == True]

        display = deals_table.copy()
        display["hubspot_link"] = display["hs_id"].apply(cfg.hubspot_contact_url)
        display["sdr_owner"] = display["sdr_owner"].map(cfg.resolve_owner)
        display["bds"] = display["bds"].map(cfg.resolve_owner)
        display["sme"] = display["sme"].map(cfg.resolve_owner)
        # Format close date to CT
        close_dt = pd.to_datetime(display["closedate"], utc=True, errors="coerce")
        close_ct = close_dt.dt.tz_convert("America/Chicago")
        display["closedate"] = close_ct.apply(
            lambda x: x.strftime("%m/%d/%Y") if pd.notna(x) else "")
        display["deal_amount"] = display["deal_amount"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—")
        display["sales_cycle_days"] = display["sales_cycle_days"].map(
            lambda x: f"{int(x)}" if pd.notna(x) else "—")
        display = display[[
            "hubspot_link", "closedate", "contact_name", "email", "typeform",
            "group", "tier", "source", "deal_amount", "sales_cycle_days",
            "sdr_owner", "bds", "sme",
        ]].rename(columns={
            "hubspot_link": "Open",
            "closedate": "Closed",
            "contact_name": "Contact",
            "email": "Email",
            "typeform": "Typeform",
            "group": "Group",
            "tier": "Plan",
            "source": "Source",
            "deal_amount": "Deal $",
            "sales_cycle_days": "Cycle (days)",
            "sdr_owner": "SDR",
            "bds": "BDS",
            "sme": "SME",
        })
        total_in_view = int(len(display))
        # Compute the marketing subset count for context
        marketing_count = int(deals_table["is_marketing"].sum()) if "is_marketing" in deals_table.columns else None
        if show_marketing_only:
            st.caption(f"Showing {total_in_view} marketing-attributed deal(s).")
        else:
            if marketing_count is not None:
                st.caption(
                    f"Showing {total_in_view} closed deal(s) total · "
                    f"{marketing_count} marketing-attributed · "
                    f"{total_in_view - marketing_count} non-marketing."
                )
            else:
                st.caption(f"Showing {total_in_view} closed deal(s) total.")
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Open": st.column_config.LinkColumn(
                    "Open", help="Open contact in HubSpot",
                    display_text="HubSpot ↗"),
            },
        )
