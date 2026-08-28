"""PAID MEDIA tab: daily MQL summary and per-segment funnel economics.

Two different dating conventions live on this page ON PURPOSE, and each
table says which it uses:
  - Daily MQL Summary is ACTIVITY dated, so past rows never move.
  - Results by Segment is COHORT dated, so spend matches the leads it bought.
Confusing the two produces wrong conclusions, hence the visible captions.

Spec: docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.hubspot_loader import (
    load_closed_deals_in_window, load_deal_contacts, load_marketing_contacts,
    load_meetings_in_window, load_mql_entries,
)
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.paid_mql import (
    daily_mql_summary, resolve_segment, segment_results,
)
from dashboard.data.reconcile import (
    DISCOVERY_MEETING_SUBSTRINGS, build_closed_deals_table,
    compute_close_commissions,
)


def _dash(v, kind: str = "money") -> str:
    """None means the denominator was zero. Render a dash, never $0.00,
    which would read as 'free'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    if kind == "money":
        return f"${v:,.2f}"
    if kind == "pct":
        return f"{v:.1%}"
    return f"{v:,.0f}"


def _iso_day(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)[:10]


def render_paid_media(start_date: date, end_date: date) -> None:
    st.header("Paid Media")
    st.caption(
        f"Window {start_date} to {end_date}. Data refreshes every 15 minutes; "
        "use Refresh data to clear the cache."
    )

    fb_daily = load_fb_insights(start_date, end_date, time_increment_days=1)
    fb_window = load_fb_insights(start_date, end_date)
    contacts = load_marketing_contacts(start_date, end_date)
    mqls = load_mql_entries(start_date, end_date)
    meetings = load_meetings_in_window(start_date, end_date)

    # Leads carry their segment from the typeform asset, which is the best
    # lead attribution available and identifies the funnel they came from.
    leads = pd.DataFrame({
        "email": contacts["email"].fillna("").str.strip().str.lower(),
        "lead_date": contacts["recent_conversion_date"].apply(_iso_day),
        "segment": contacts["typeform_asset_download"].map(
            cfg.ASSET_TO_GROUP).map(
            lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
    }).dropna(subset=["lead_date"])
    leads = leads[leads["email"] != ""]

    mql_frame = pd.DataFrame({
        "email": mqls["email"].fillna("").str.strip().str.lower(),
        "mql_date": mqls["mql_entered_at"].apply(_iso_day),
        "segment": mqls["typeform_asset_download"].map(
            cfg.ASSET_TO_GROUP).map(
            lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
    }).dropna(subset=["mql_date"])
    mql_frame = mql_frame[mql_frame["email"] != ""]

    # --- Table 1 ---
    st.subheader("Daily MQL Summary")
    st.caption(
        "Dated by event: a lead counts the day it arrived, a callable MQL "
        "counts the day it entered MQL. Past rows never change. Lead to "
        "Callable % on a single row is a ratio of that day's two counts, not "
        "a cohort conversion rate."
    )
    available = sorted({s for s in leads["segment"].dropna().unique()}
                       | {resolve_segment(n, segment_rollup=cfg.SEGMENT_ROLLUP)
                          for n in fb_window["campaign_name"].dropna()})
    picked = st.multiselect("Segments", available, default=available,
                            key="paid_media_segments")

    daily = daily_mql_summary(
        fb_daily, leads, mql_frame,
        segment_rollup=cfg.SEGMENT_ROLLUP,
        segments=tuple(picked) if picked else None,
    )
    st.dataframe(pd.DataFrame({
        "Date": daily["date"],
        "Leads": daily["leads"].map(lambda v: _dash(v, "int")),
        "Callable MQL": daily["callable_mql"].map(lambda v: _dash(v, "int")),
        "Lead to Callable %": daily["lead_to_callable_pct"].map(
            lambda v: _dash(v, "pct")),
        "Cost Per Lead": daily["cost_per_lead"].map(_dash),
        "Cost Per Callable MQL": daily["cost_per_callable_mql"].map(_dash),
    }), use_container_width=True, hide_index=True)

    # --- Table 2 ---
    st.subheader("Results by Segment")
    st.caption(
        "Dated by lead cohort: spend is matched to the leads it bought. "
        "Because closes lag lead arrival, Sales and both cost-per-close "
        "columns read low on recent windows. Money columns are acquisition "
        "cost only; revenue and ROAS are omitted because every closed-won "
        "deal in HubSpot carries an identical $40,000 placeholder amount."
    )

    disco = meetings[meetings["activity_type"].fillna("").str.lower().apply(
        lambda s: any(sub in s for sub in DISCOVERY_MEETING_SUBSTRINGS))]
    email_by_id = dict(zip(contacts["hs_id"].astype(str),
                           contacts["email"].fillna("").str.strip().str.lower()))
    call_emails = {email_by_id.get(str(c)) for c in disco["contact_id"].dropna()}
    call_emails.discard(None)
    call_emails.discard("")

    deals = load_closed_deals_in_window(
        start_date, end_date,
        tuple(cfg.STAGES_CLOSED_WON),
        tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE),
    )
    # The deal-to-contact associations are REQUIRED, not optional. Passing an
    # empty frame here makes build_closed_deals_table produce a table with no
    # contact linkage, so sale_emails comes back empty and every Sales cell
    # silently reads 0 while looking perfectly healthy.
    contact_deals = (load_deal_contacts(tuple(deals["deal_id"].astype(str)))
                     if not deals.empty else
                     pd.DataFrame(columns=["contact_id", "deal_id"]))
    try:
        deals_table = build_closed_deals_table(
            deals, contact_deals, contacts,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
            stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"Closed-deal attribution unavailable: {e}")
        deals_table = pd.DataFrame()

    # Sales are counted cohort-style: of the leads that arrived in this
    # window, how many closed. So resolving deal contacts against the
    # in-window contact frame is correct, not a shortcut. A closed deal whose
    # contact arrived before the window is intentionally not counted here.
    sale_emails: set[str] = set()
    if not contact_deals.empty:
        for cid in contact_deals["contact_id"].dropna().astype(str):
            em = email_by_id.get(cid)
            if em:
                sale_emails.add(em)

    commissions_by_segment: dict[str, float] = {}
    if not deals_table.empty and "group" in deals_table.columns:
        for grp, sub in deals_table.groupby("group"):
            seg = cfg.SEGMENT_ROLLUP.get(grp, grp)
            comm = compute_close_commissions(
                sub,
                sdr_close=cfg.SDR_CLOSE_COMMISSION,
                bds_close=cfg.BDS_CLOSE_COMMISSION,
                sme_close=cfg.SME_CLOSE_COMMISSION,
                flat_close=cfg.FLAT_CLOSE_COMMISSION,
            )
            commissions_by_segment[seg] = (
                commissions_by_segment.get(seg, 0.0) + comm["total"])

    # Ruling P3: the brief's rename to "_d" targeted a column the very next
    # selector discards, so it is a no-op. Select the two needed columns
    # directly.
    seg_df = segment_results(
        fb_window, leads[["email", "segment"]],
        mql_emails=set(mql_frame["email"]),
        call_emails=call_emails,
        sale_emails=sale_emails,
        commissions_by_segment=commissions_by_segment,
        segment_rollup=cfg.SEGMENT_ROLLUP,
    )
    st.dataframe(pd.DataFrame({
        "Segment": seg_df["segment"],
        "Spend": seg_df["spend"].map(_dash),
        "Leads": seg_df["leads"].map(lambda v: _dash(v, "int")),
        "Callable MQL": seg_df["callable_mql"].map(lambda v: _dash(v, "int")),
        "Cost CMQL": seg_df["cost_cmql"].map(_dash),
        "Lead to Callable %": seg_df["lead_to_callable_pct"].map(
            lambda v: _dash(v, "pct")),
        "Calls": seg_df["calls"].map(lambda v: _dash(v, "int")),
        "Cost per Call": seg_df["cost_per_call"].map(_dash),
        "Callable to Call %": seg_df["callable_to_call_pct"].map(
            lambda v: _dash(v, "pct")),
        "Sales": seg_df["sales"].map(lambda v: _dash(v, "int")),
        "Call to Sale %": seg_df["call_to_sale_pct"].map(
            lambda v: _dash(v, "pct")),
        "Cost per Close": seg_df["cost_per_close"].map(_dash),
        "Segment CAC": seg_df["segment_cac"].map(_dash),
    }), use_container_width=True, hide_index=True)

    if "(unmatched)" in set(seg_df["segment"]):
        st.warning(
            "An (unmatched) row is present: a campaign is running whose name "
            "matches no segment pattern in CAMPAIGN_GROUPS. Its spend is "
            "reported but its leads are not attributed. Add the pattern to "
            "config.CAMPAIGN_GROUPS and the matching typeform label to "
            "config.ASSET_TO_GROUP."
        )
