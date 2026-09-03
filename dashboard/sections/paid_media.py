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
from dashboard.data.fb_loader import (
    load_fb_ad_entities, load_fb_ad_insights, load_fb_insights,
)
from dashboard.data.groups import merge_list_group
from dashboard.data.hubspot_loader import (
    load_closed_deals_in_window, load_contacts_by_ids, load_deal_contacts,
    load_list_memberships, load_marketing_contacts, load_meetings_in_window,
    load_mql_entries,
)
from dashboard.data.hyros_loader import load_hyros_leads_with_ads
from dashboard.data.paid_mql import (
    UNMATCHED_LEADS, creative_tracker, daily_mql_summary, resolve_segment,
    segment_results,
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


# A single stray contact should not nag. This is the number of in-window
# leads that unmapped asset labels must carry between them before the tripwire
# fires. Set low on purpose: five orphaned leads is already enough to move a
# cost-per-lead number, and the whole point is to catch a rename early.
UNMAPPED_ASSET_WARN_MIN = 3


def unmapped_asset_counts(leads: pd.DataFrame) -> dict[str, int]:
    """In-window leads per RAW typeform label that maps to no segment.

    The spec requires a check that surfaces unmapped asset labels carrying
    non-trivial volume, because a missing ASSET_TO_GROUP key produces no error
    at all, only a quietly wrong number. Returns {} when every label maps.
    """
    if leads is None or leads.empty or "asset" not in leads.columns:
        return {}
    orphans = leads[leads["segment"].isna()]
    if orphans.empty:
        return {}
    counts = orphans.groupby(
        orphans["asset"].fillna("(no asset recorded)").astype(str)
    )["email"].nunique()
    return {str(k): int(v) for k, v in counts.items()}


def unmapped_asset_warning(counts: dict[str, int], *,
                           minimum: int = UNMAPPED_ASSET_WARN_MIN) -> str | None:
    """Warning text naming the unmapped labels, or None when volume is trivial.

    Modelled on the (unmatched) campaign warning below the segment table. The
    threshold applies to the TOTAL across labels, not to any single label, so
    five orphaned leads spread across five renamed labels still fires.
    """
    total = sum(counts.values())
    if total < minimum:
        return None
    listed = ", ".join(f'"{label}" ({n})'
                       for label, n in sorted(counts.items(),
                                              key=lambda kv: (-kv[1], kv[0])))
    return (
        f"{total} leads in this window carry a typeform asset label that maps "
        f"to no segment, so they are grouped under {UNMATCHED_LEADS} instead "
        f"of the funnel they came from: {listed}. This is usually a label "
        "renamed in HubSpot. Add each one to config.ASSET_TO_GROUP."
    )


def build_lead_frames(contacts: pd.DataFrame,
                      mqls: pd.DataFrame,
                      start_date: date,
                      end_date: date,
                      *,
                      asset_to_group: dict,
                      segment_rollup: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (leads, mql_frame) from the POST-MERGE contacts frame.

    Extracted from render_paid_media so the segment derivation is testable
    without a Streamlit runtime. Config arrives as parameters, matching the
    convention in paid_mql.py.

    leads carry their segment from the typeform asset, which is the best lead
    attribution available and identifies the funnel they came from.

    lead_date comes from typeform_submission_date (the generation event), NOT
    recent_conversion_date. HubSpot ADVANCES recent_conversion_date whenever a
    lead later books a call, so a lead generated months ago who merely booked a
    call in this window would otherwise be counted as a lead of THIS window,
    inflating the count and understating cost per lead. load_marketing_contacts
    windows on recent_conversion_date (that is why these contacts arrive at
    all), so a contact whose typeform_submission_date is null or falls outside
    [start_date, end_date] is dropped here rather than counted. This matches
    Daily Summary, Weekly Metrics, and the Executive tab (commit 32da534).

    An MQL is segmented the SAME way its own contact was segmented as a lead,
    by email against this merged frame, NOT by mapping the MQL loader's raw
    asset value a second time. merge_list_group re-tags TheraRay and NLAP list
    members with the synthetic labels "TheraRay FB Lead" / "NLAP FB Lead" and
    registers those in ASSET_TO_GROUP, while load_mql_entries returns the same
    contacts' RAW HubSpot labels ("NLAP User ", "TheraRay Device "), which are
    deliberately and permanently absent from ASSET_TO_GROUP. Mapping the raw
    value therefore segmented one person one way as a lead and another way as
    an MQL: every NLAP and TheraRay MQL was dropped by the segment filter while
    all of their spend was kept, overstating Cost Per Callable MQL.
    """
    _start_iso, _end_iso = str(start_date), str(end_date)

    def _segment_of(asset):
        group = asset_to_group.get(asset) if isinstance(asset, str) else None
        return segment_rollup.get(group, group) if group else None

    emails = contacts["email"].fillna("").str.strip().str.lower()
    segments = contacts["typeform_asset_download"].map(_segment_of)
    leads = pd.DataFrame({
        "email": emails,
        "lead_date": contacts["typeform_submission_date"].apply(_iso_day),
        "segment": segments,
        # The raw label is carried so the unmapped-asset tripwire can name the
        # labels that need adding to ASSET_TO_GROUP.
        "asset": contacts["typeform_asset_download"],
    }).dropna(subset=["lead_date"])
    leads = leads[(leads["email"] != "")
                  & (leads["lead_date"] >= _start_iso)
                  & (leads["lead_date"] <= _end_iso)]

    # Every known email is a key, including one whose segment is None. An
    # unresolvable contact must stay unresolvable on the MQL side too, or the
    # two halves of the page drift apart again; the asset fallback applies
    # only to an MQL this contacts frame never saw.
    contact_segment: dict[str, str | None] = {}
    for _email, _seg in zip(emails, segments):
        if not _email:
            continue
        if contact_segment.get(_email) is None:
            contact_segment[_email] = _seg

    mql_emails = mqls["email"].fillna("").str.strip().str.lower()
    mql_segments = pd.Series(
        [contact_segment[e] if e in contact_segment else _segment_of(a)
         for e, a in zip(mql_emails, mqls["typeform_asset_download"])],
        index=mqls.index, dtype=object)

    mql_frame = pd.DataFrame({
        "email": mql_emails,
        "mql_date": mqls["mql_entered_at"].apply(_iso_day),
        "segment": mql_segments,
    }).dropna(subset=["mql_date"])
    mql_frame = mql_frame[mql_frame["email"] != ""]
    return leads, mql_frame


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

    # Merge list-based groups (TheraRay, NLAP): their opt-ins are captured via
    # HubSpot list membership, not a typeform, because FB lead reporting is
    # unreliable for them. Without this, TheraRay/NLAP spend shows up with
    # zero leads -- the exact failure this tab exists to prevent. Mirrors
    # executive.py:120-136. merge_list_group tags each merged contact's
    # typeform_submission_date with its membership timestamp (always inside
    # [start_date, end_date] by construction), so the lead-dating fix below
    # dates list members correctly automatically, and it registers
    # cfg.ASSET_TO_GROUP[asset_label] so segment mapping picks them up too.
    _list_groups = [
        (cfg.THERARAY_HUBSPOT_LIST_ID, "TheraRay FB Lead", "TheraRay"),
        (cfg.NLAP_HUBSPOT_LIST_ID, "NLAP FB Lead", "NLAP"),
    ]
    for _lid, _label, _grp in _list_groups:
        try:
            contacts = merge_list_group(
                contacts, list_id=_lid, asset_label=_label, group=_grp,
                start=start_date, end=end_date,
                load_memberships=load_list_memberships,
                load_contacts=load_contacts_by_ids,
                excluded_emails=cfg.MARKETING_EXCLUDED_EMAILS,
                asset_to_group=cfg.ASSET_TO_GROUP,
            )
        except Exception as e:  # noqa: BLE001
            st.warning(f"{_grp} merge failed: {e}")

    leads, mql_frame = build_lead_frames(
        contacts, mqls, start_date, end_date,
        asset_to_group=cfg.ASSET_TO_GROUP,
        segment_rollup=cfg.SEGMENT_ROLLUP,
    )

    # --- Table 1 ---
    st.subheader("Daily MQL Summary")
    st.caption(
        "Dated by event: a lead counts the day it arrived, a callable MQL "
        "counts the day it entered MQL. Past rows never change. Lead to "
        "Callable % on a single row is a ratio of that day's two counts, not "
        "a cohort conversion rate."
    )
    _lead_segments = {s for s in leads["segment"].dropna().unique()}
    # Leads whose asset maps to nothing are a selectable segment of their own,
    # so they are visible and counted by default instead of being deleted by
    # the filter, and Table 1 reconciles with Table 2's (unmatched leads) row.
    if leads["segment"].isna().any():
        _lead_segments.add(UNMATCHED_LEADS)
    available = sorted(_lead_segments
                       | {resolve_segment(n, segment_rollup=cfg.SEGMENT_ROLLUP)
                          for n in fb_window["campaign_name"].dropna()})
    picked = st.multiselect("Segments", available, default=available,
                            key="paid_media_segments")
    if not picked:
        # An empty selection means an empty table. Falling back to None here
        # showed MORE rows than any partial selection, which read as a bug.
        st.info("No segments selected, so the table below is empty. Pick at "
                "least one segment.")

    daily = daily_mql_summary(
        fb_daily, leads, mql_frame,
        segment_rollup=cfg.SEGMENT_ROLLUP,
        segments=tuple(picked),
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

    # The campaign-side tripwire above covers the failure mode that already
    # announces itself. A missing ASSET key is the silent one: it produces no
    # error at all, only a quietly wrong number, because the spend survives
    # and the leads it bought do not.
    _unmapped = unmapped_asset_warning(unmapped_asset_counts(leads))
    if _unmapped:
        st.warning(_unmapped)

    # --- Table 3 ---
    st.subheader("Creative Tracker")
    floor = st.number_input(
        "Minimum spend to appear", min_value=0.0, step=100.0,
        value=float(cfg.CREATIVE_SPEND_FLOOR), key="paid_media_floor")
    st.caption(
        "One row per ad above the spend floor, newest first. Performance "
        "compares each ad's cost per callable MQL against the average for "
        "its OWN segment, so a Chiro ad is judged against Chiro. An ad needs "
        f"at least {cfg.CREATIVE_MIN_MQL} callable MQLs to earn a label. "
        "Revenue and ROAS are omitted for the same reason as the segment "
        "table."
    )

    ad_ins = load_fb_ad_insights(start_date, end_date)
    kept = ad_ins[ad_ins["spend"] >= floor]
    ad_ents = load_fb_ad_entities(tuple(kept["ad_id"]))
    hyros = load_hyros_leads_with_ads(start_date, end_date)

    ad_emails: dict[str, set[str]] = {}
    for r in hyros.itertuples(index=False):
        if r.ad_id:
            ad_emails.setdefault(str(r.ad_id), set()).add(r.email)

    tracker = creative_tracker(
        kept, ad_ents, ad_emails,
        mql_emails=set(mql_frame["email"]),
        call_emails=call_emails,
        sale_emails=sale_emails,
        segment_rollup=cfg.SEGMENT_ROLLUP,
        spend_floor=floor,
        winner_pct=cfg.CREATIVE_WINNER_PCT,
        standout_pct=cfg.CREATIVE_STANDOUT_PCT,
        min_mql=cfg.CREATIVE_MIN_MQL,
    )

    if tracker.empty:
        st.info(f"No ads spent {_dash(floor)} or more in this window.")
    else:
        st.dataframe(pd.DataFrame({
            "Ad Name": tracker["ad_name"],
            "Ad Link": tracker["story_id"].map(
                lambda s: f"https://www.facebook.com/{str(s).replace('_', '/posts/')}"
                if s else ""),
            "Funnel": tracker["segment"],
            "Format": tracker["format"],
            "Launched": tracker["launched"],
            "Status": tracker["status"],
            "Performance": tracker["performance"],
            "Spend": tracker["spend"].map(_dash),
            "Callable MQL": tracker["callable_mql"].map(
                lambda v: _dash(v, "int")),
            "Cost per CMQL": tracker["cost_cmql"].map(_dash),
            "Calls": tracker["calls"].map(lambda v: _dash(v, "int")),
            "Cost per Call": tracker["cost_per_call"].map(_dash),
            "Units Sold": tracker["sales"].map(lambda v: _dash(v, "int")),
        }), use_container_width=True, hide_index=True,
            column_config={"Ad Link": st.column_config.LinkColumn(
                "Ad Link", display_text="open")})

        # The denominator is reported because without it a total attribution
        # outage reads as perfect coverage: an empty Hyros pull makes isna()
        # count 0 and prints "0 records carry no ad id", which is maximally
        # reassuring exactly when it is maximally wrong.
        hyros_records = int(len(hyros))
        untracked = int(hyros["ad_id"].isna().sum()) if hyros_records else 0
        st.caption(
            "Ad-level lead counts come from Hyros ad attribution, while the "
            "segment table's counts come from HubSpot typeform submissions. "
            "These are different keys reading different systems, so the two "
            "tables will NOT sum identically. Hyros only sees leads it "
            f"tracked. In this window {untracked} of {hyros_records} Hyros "
            "lead records carry no ad id and are therefore absent from every "
            "ad row above."
        )
        if hyros_records == 0:
            st.warning(
                "The Hyros pull returned no lead records at all for this "
                "window, so every Callable MQL, Calls and Units Sold count in "
                "the table above is zero for want of data rather than for "
                "want of results. Ad-level attribution is unavailable."
            )
