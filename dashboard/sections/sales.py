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
    load_closed_deals_ytd,
)
from dashboard.data.reconcile import (
    build_closed_deals_table,
    compute_speed_to_lead,
    pipeline_funnel,
    sales_bds_rollup,
    sales_sdr_rollup,
    sales_sme_rollup,
    windowed_sales_money,
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


def _fmt_minutes(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:.0f}"


def _stage_groups() -> dict[str, set[str]]:
    return {
        "15min_booked":    cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        "15min_held":      cfg.STAGES_15MIN_HELD,
        "strategy_booked": cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
        "strategy_held":   cfg.STAGES_STRATEGY_HELD,
        "closedwon":       cfg.STAGES_CLOSED_WON,
    }


def render_sales(start: date, end: date) -> None:
    floor_days = st.session_state.get("data_floor_days_back", 180)
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
        deals = load_deals_in_window(start, end, data_floor_days_back=floor_days)
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
        meetings = load_meetings_for_contacts(marketing["hs_id"].tolist(),
                                              data_floor_days_back=floor_days) \
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

    # YTD closed deals (used by Money cards + Closed Deals YTD section)
    try:
        deals_ytd, contact_deals_ytd, contacts_ytd = load_closed_deals_ytd(
            closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
        )
    except Exception as e:
        st.warning(f"YTD closed deals unavailable: {e}")
        deals_ytd = pd.DataFrame()
        contact_deals_ytd = pd.DataFrame(columns=["contact_id", "deal_id"])
        contacts_ytd = pd.DataFrame()

    stages = _stage_groups()

    fn_mkt = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=True)
    fn_all = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)

    # ----- Row 1: Pipeline KPIs (existing) -----
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

    # ----- Row 2: Money + Time-to-Close (window-bounded, all sources) -----
    money = windowed_sales_money(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        start=start, end=end,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        stages_closed_won_no_closedate=cfg.STAGES_CLOSED_WON_NO_CLOSEDATE,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        group_cash_per_deal=cfg.GROUP_CASH_COLLECTED_PER_DEAL,
    )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(
        "Total Sales (window)",
        _fmt_int(money["window_closed_count"]),
        help="Closed-won deals (all sources) within the current date range.",
    )
    m2.metric(
        "Total Revenue (window)",
        _fmt_money(money["window_revenue"]),
        help="Sum of effective deal $ for closed deals in the date range "
             "(HubSpot amount with group-default fallback).",
    )
    m3.metric(
        "Cash Collection",
        _fmt_money(money["window_cash_collection"]),
        help="Sum of per-deal cash collected (Chiro $47,928 / PT $23,928 per "
             "closed deal). Diverges from Revenue once payment-plan tracking "
             "is wired.",
    )
    m4.metric(
        "Avg Deal Size",
        _fmt_money(money["window_avg_deal_size"]),
        help="Total Revenue / Total Sales for the date range.",
    )
    m5.metric(
        "Avg Time-to-Close (days)",
        _fmt_minutes(money["window_cycle_median_days"]),
        help="Median days from typeform opt-in (createdate fallback) to "
             "deal close, across deals closed in this window.",
    )

    # ----- Row 3: Speed to Lead (existing) -----
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
        help="Median minutes from typeform submission to first outbound AirCall.")
    s2.metric(
        "% Under 5 min",
        _fmt_pct(pct_under_5),
        help="Share of leads whose first outbound call landed within 5 minutes "
             "of opt-in. Hormozi's 80% target.")
    s3.metric(
        "% Under 60 sec",
        _fmt_pct(pct_under_60s),
        help="Share within 60 seconds. Hormozi's stretch goal (50%).")

    st.divider()

    # ----- Section: SDR Performance (Wave 1 + Wave 2) -----
    st.subheader("SDR Performance")
    st.caption(
        "Dials + pick-ups + real conversations + appointments from AirCall + "
        "HubSpot. **Pick Up** = call answered. **Contact Made** = answered + "
        f"≥{cfg.AIRCALL_CONNECT_DURATION_SEC}s (real conversation, filters "
        "voicemail). **Booking %** = Appts Booked / Contacts Made."
    )
    sdr = sales_sdr_rollup(
        contacts=marketing,
        calls=aircall_calls,
        meetings=meetings,
        aircall_user_names=cfg.AIRCALL_USER_NAMES,
        excluded_users=cfg.AIRCALL_EXCLUDED_USERS,
        aircall_to_sdr_owner=cfg.AIRCALL_TO_SDR_OWNER,
        connect_duration_sec=cfg.AIRCALL_CONNECT_DURATION_SEC,
        conv_window_hours=cfg.AIRCALL_CONV_TO_DISCO_WINDOW_HOURS,
    )
    if sdr.empty:
        st.info("No SDR activity in this window.")
    else:
        display = sdr.copy()
        display["talk_time_min"] = display["talk_time_min"].map(_fmt_minutes)
        display["booking_rate"] = display["booking_rate"].map(_fmt_pct)
        display["median_speed_to_lead_min"] = display["median_speed_to_lead_min"].map(
            lambda x: f"{x:.1f} min" if x is not None and not pd.isna(x) else "—"
        )
        display = display[[
            "user_name", "dials", "pick_ups", "contacts_made", "talk_time_min",
            "appointments_booked", "booking_rate",
            "median_speed_to_lead_min",
        ]].rename(columns={
            "user_name": "SDR",
            "dials": "Dials",
            "pick_ups": "Pick Ups",
            "contacts_made": "Contacts Made",
            "talk_time_min": "Talk Time (min)",
            "appointments_booked": "Appts Booked",
            "booking_rate": "Booking %",
            "median_speed_to_lead_min": "Median Speed",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.divider()

    # ----- Section: BDS Performance (Wave 1) -----
    st.subheader("BDS Performance")
    st.caption(
        "BDS holds the 15-min Discovery, qualifies the prospect, and books the "
        "Strategy when qualified. **Show %** = Shows / Appointments · "
        "**Booking %** = SME Booked / Shows · **DQ %** = Disqualified / Shows."
    )
    bds = sales_bds_rollup(
        contacts=marketing,
        meetings=meetings,
        contact_deals=contact_deals,
        deals=deals,
        stages_15min_dq=cfg.STAGES_15MIN_DQ,
    )
    if bds.empty:
        st.info("No BDS activity in this window.")
    else:
        display = bds.copy()
        display["bds_id"] = display["bds_id"].map(cfg.resolve_owner)
        display["show_rate"] = display["show_rate"].map(_fmt_pct)
        display["booking_rate"] = display["booking_rate"].map(_fmt_pct)
        display["dq_rate"] = display["dq_rate"].map(_fmt_pct)
        display = display.rename(columns={
            "bds_id": "BDS",
            "appointments": "Appointments",
            "shows": "Shows",
            "sme_booked": "SME Booked",
            "disqualified": "Disqualified",
            "show_rate": "Show %",
            "booking_rate": "Booking %",
            "dq_rate": "DQ %",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.divider()

    # ----- Section: SME Performance (Wave 1 + Wave 2) -----
    st.subheader("SME Performance")
    st.caption(
        "SME holds the Strategy and closes. **First Close** = closed on the "
        "first Strategy call · **FU Close** = closed after a follow-up call. "
        "**Close %** = total closed / showed. **DQ %** = disqualified / showed."
    )
    sme = sales_sme_rollup(
        contacts=marketing,
        meetings=meetings,
        contact_deals=contact_deals,
        deals=deals,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        stages_strategy_dq=cfg.STAGES_STRATEGY_DQ,
    )
    if sme.empty:
        st.info("No SME activity in this window.")
    else:
        display = sme.copy()
        display["sme_id"] = display["sme_id"].map(cfg.resolve_owner)
        display["show_rate"] = display["show_rate"].map(_fmt_pct)
        display["close_rate"] = display["close_rate"].map(_fmt_pct)
        display["first_close_rate"] = display["first_close_rate"].map(_fmt_pct)
        display["fu_close_rate"] = display["fu_close_rate"].map(_fmt_pct)
        display["dq_rate"] = display["dq_rate"].map(_fmt_pct)
        display["revenue"] = display["revenue"].map(_fmt_money)
        display = display[[
            "sme_id", "appointments", "showed", "deals_closed",
            "first_closes", "fu_closes", "disqualified",
            "show_rate", "close_rate", "first_close_rate", "fu_close_rate",
            "dq_rate", "revenue",
        ]].rename(columns={
            "sme_id": "SME",
            "appointments": "Appointments",
            "showed": "Showed",
            "deals_closed": "Closed",
            "first_closes": "First Close",
            "fu_closes": "FU Close",
            "disqualified": "DQ",
            "show_rate": "Show %",
            "close_rate": "Close %",
            "first_close_rate": "First %",
            "fu_close_rate": "FU %",
            "dq_rate": "DQ %",
            "revenue": "Revenue",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.divider()

    # ----- Section: Bottleneck — Where Leads Drop Off (Wave 2) -----
    st.subheader("Bottleneck — Where Leads Drop Off")
    st.caption(
        "Conversion rate at each stage transition. The lowest-converting stage "
        "(your bottleneck) is highlighted in red."
    )
    # Build stage counts: Marketing Leads → 15-min Booked → Held → Strategy Booked → Held → Closed-Won.
    # Uses the marketing-only funnel for consistency with the rest of this tab.
    lead_count = int(len(marketing)) if not marketing.empty else 0
    stage_counts = [
        ("Marketing Leads", lead_count),
        ("15-min Booked", int(_v(fn_mkt, "15-min Booked"))),
        ("15-min Held", int(_v(fn_mkt, "15-min Held"))),
        ("Strategy Booked", int(_v(fn_mkt, "Strategy Booked"))),
        ("Strategy Held", int(_v(fn_mkt, "Strategy Held"))),
        ("Closed-Won", int(_v(fn_mkt, "Closed-Won"))),
    ]
    transitions = []
    for i in range(len(stage_counts) - 1):
        from_s, from_c = stage_counts[i]
        to_s, to_c = stage_counts[i + 1]
        rate = (to_c / from_c) if from_c else None
        transitions.append({
            "label": f"{from_s} → {to_s}",
            "rate": rate,
            "from_count": from_c,
            "to_count": to_c,
        })
    trans_df = pd.DataFrame(transitions)
    non_null = trans_df["rate"].dropna()
    min_rate = float(non_null.min()) if not non_null.empty else None
    trans_df["color"] = trans_df["rate"].apply(
        lambda r: "#d62728" if (r is not None and not pd.isna(r) and min_rate is not None and r == min_rate)
        else "#1f77b4"
    )
    trans_df["label_text"] = trans_df.apply(
        lambda r: (f"{r['rate']*100:.0f}%  ({r['to_count']}/{r['from_count']})"
                   if r["rate"] is not None and not pd.isna(r["rate"]) else "—"),
        axis=1,
    )
    bottleneck_fig = go.Figure(go.Bar(
        x=[(r * 100 if r is not None and not pd.isna(r) else 0) for r in trans_df["rate"]],
        y=trans_df["label"],
        orientation="h",
        marker_color=trans_df["color"].tolist(),
        text=trans_df["label_text"],
        textposition="outside",
    ))
    bottleneck_fig.update_layout(
        xaxis=dict(title="Conversion rate (%)", range=[0, 110]),
        yaxis=dict(autorange="reversed"),
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
    )
    st.plotly_chart(bottleneck_fig, use_container_width=True)
    if min_rate is not None:
        worst_row = trans_df.loc[trans_df["rate"] == min_rate].iloc[0]
        st.caption(
            f"**Biggest leak:** {worst_row['label']} at "
            f"{min_rate*100:.0f}% ({worst_row['to_count']} of "
            f"{worst_row['from_count']})."
        )

    st.divider()

    # ----- Section: Pipeline Funnel (existing — moved below) -----
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

    # ----- Section: Marketing Lead Detail (existing) -----
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

    detail["_sort_ts"] = pd.to_datetime(
        detail["typeform_submission_date"], utc=True, errors="coerce"
    )
    detail = detail.sort_values("_sort_ts", ascending=False, na_position="last")
    detail = detail.drop(columns=["_sort_ts"])

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

    # ----- Section: Closed Deals YTD (existing) -----
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
        show_marketing_only = st.checkbox(
            "Show marketing-attributed deals only",
            value=False,
            key="sales_closed_deals_marketing_filter",
        )
        if show_marketing_only and not deals_table.empty:
            deals_table = deals_table[deals_table["is_marketing"] == True]

        display_ytd = deals_table.copy()
        display_ytd["hubspot_link"] = display_ytd["hs_id"].apply(cfg.hubspot_contact_url)
        display_ytd["sdr_owner"] = display_ytd["sdr_owner"].map(cfg.resolve_owner)
        display_ytd["bds"] = display_ytd["bds"].map(cfg.resolve_owner)
        display_ytd["sme"] = display_ytd["sme"].map(cfg.resolve_owner)
        close_dt = pd.to_datetime(display_ytd["closedate"], utc=True, errors="coerce")
        close_ct = close_dt.dt.tz_convert("America/Chicago")
        display_ytd["closedate"] = close_ct.apply(
            lambda x: x.strftime("%m/%d/%Y") if pd.notna(x) else "")
        display_ytd["deal_amount"] = display_ytd["deal_amount"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—")
        display_ytd["sales_cycle_days"] = display_ytd["sales_cycle_days"].map(
            lambda x: f"{int(x)}" if pd.notna(x) else "—")
        display_ytd = display_ytd[[
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
        total_in_view = int(len(display_ytd))
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
            display_ytd, use_container_width=True, hide_index=True,
            column_config={
                "Open": st.column_config.LinkColumn(
                    "Open", help="Open contact in HubSpot",
                    display_text="HubSpot ↗"),
            },
        )
