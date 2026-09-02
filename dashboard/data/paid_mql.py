"""Pure rollup logic for the PAID MEDIA tab. No I/O.

Config values arrive as parameters rather than imports, matching the
convention in reconcile.py and paid_media.py, so every function here is
testable without touching Streamlit secrets or any API.

Spec: docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md
"""
from __future__ import annotations

import pandas as pd

from dashboard.data.groups import match_group

UNMATCHED = "(unmatched)"


def _safe_div(num: float, den: float) -> float | None:
    """None on a zero denominator, never 0. A zero denominator and a genuine
    zero are different facts and must render differently.

    Deliberately duplicates reconcile._safe_div to avoid coupling a small pure
    module to a 3,240-line module for a one-liner.
    """
    if not den:
        return None
    return num / den


def _frame_preserving_none(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Build a frame WITHOUT letting pandas turn None into NaN.

    pandas coerces a column holding both None and float to float64, which
    silently rewrites None as NaN. These frames are small display tables
    whose None values mean "no value, render a dash", and callers test that
    with `is None`, so object dtype is the correct trade here.
    """
    out = pd.DataFrame(rows, columns=columns).astype(object)
    return out.where(out.notna(), None)


def resolve_segment(campaign_name, *, segment_rollup: dict[str, str],
                    unmatched_label: str = UNMATCHED) -> str:
    """Map an FB campaign name to a PAID MEDIA segment.

    Applies the existing CAMPAIGN_GROUPS match, then folds groups into their
    roll-up segment (EMX and Practice Growth Workshop both become Event).
    A campaign matching nothing returns the unmatched label rather than None,
    so it surfaces as a visible row instead of vanishing.

    Ruling P7: NaN-safe. Any non-string input (including pandas NaN) is
    treated as unmatched.
    """
    if not isinstance(campaign_name, str) or not campaign_name:
        return unmatched_label
    group = match_group(campaign_name)
    if not group:
        return unmatched_label
    return segment_rollup.get(group, group)


DAILY_COLUMNS = ["date", "leads", "callable_mql", "lead_to_callable_pct",
                 "cost_per_lead", "cost_per_callable_mql"]


def daily_mql_summary(fb_daily: pd.DataFrame,
                      leads: pd.DataFrame,
                      mql_entries: pd.DataFrame,
                      *,
                      segment_rollup: dict[str, str],
                      segments: tuple[str, ...] | None = None,
                      ) -> pd.DataFrame:
    """One row per calendar day, ACTIVITY dated, plus a Total row.

    A lead counts on the day it was created; a callable MQL counts on the day
    it entered MQL. For one contact those are usually different days. That is
    intentional: it keeps every past row frozen, which is what makes this the
    morning operations read.

    lead_to_callable_pct on a single row is therefore a ratio of two counts
    over the same day, NOT a cohort conversion rate. The segment table is
    where true conversion lives.
    """
    fb = fb_daily.copy() if fb_daily is not None else pd.DataFrame()
    lds = leads.copy() if leads is not None else pd.DataFrame()
    mqs = mql_entries.copy() if mql_entries is not None else pd.DataFrame()

    if not fb.empty:
        fb["segment"] = fb["campaign_name"].apply(
            lambda n: resolve_segment(n, segment_rollup=segment_rollup))
    if segments is not None:
        keep = set(segments)
        if not fb.empty:
            fb = fb[fb["segment"].isin(keep)]
        if not lds.empty:
            lds = lds[lds["segment"].isin(keep)]
        if not mqs.empty:
            mqs = mqs[mqs["segment"].isin(keep)]

    spend_by_day = (fb.groupby("date_start")["spend"].sum().to_dict()
                    if not fb.empty else {})
    leads_by_day = (lds.groupby("lead_date")["email"].nunique().to_dict()
                    if not lds.empty else {})
    mql_by_day = (mqs.groupby("mql_date")["email"].nunique().to_dict()
                  if not mqs.empty else {})

    days = sorted(set(spend_by_day) | set(leads_by_day) | set(mql_by_day))
    rows = []
    for d in days:
        spend = float(spend_by_day.get(d, 0.0))
        n_leads = int(leads_by_day.get(d, 0))
        n_mql = int(mql_by_day.get(d, 0))
        rows.append({
            "date": d,
            "leads": n_leads,
            "callable_mql": n_mql,
            "lead_to_callable_pct": _safe_div(n_mql, n_leads),
            "cost_per_lead": _safe_div(spend, n_leads),
            "cost_per_callable_mql": _safe_div(spend, n_mql),
        })

    tot_spend = float(sum(spend_by_day.values()))
    tot_leads = int(sum(leads_by_day.values()))
    tot_mql = int(sum(mql_by_day.values()))
    rows.append({
        "date": "Total",
        "leads": tot_leads,
        "callable_mql": tot_mql,
        # Ratios come from the totals, never from averaging the per-day
        # ratios, which would weight a $10 day the same as a $3,000 day.
        "lead_to_callable_pct": _safe_div(tot_mql, tot_leads),
        "cost_per_lead": _safe_div(tot_spend, tot_leads),
        "cost_per_callable_mql": _safe_div(tot_spend, tot_mql),
    })
    return _frame_preserving_none(rows, DAILY_COLUMNS)


SEGMENT_COLUMNS = ["segment", "spend", "leads", "callable_mql", "cost_cmql",
                   "lead_to_callable_pct", "calls", "cost_per_call",
                   "callable_to_call_pct", "sales", "call_to_sale_pct",
                   "cost_per_close", "segment_cac"]


def segment_results(fb: pd.DataFrame,
                    leads: pd.DataFrame,
                    mql_emails: set[str],
                    call_emails: set[str],
                    sale_emails: set[str],
                    commissions_by_segment: dict[str, float],
                    *,
                    segment_rollup: dict[str, str],
                    ) -> pd.DataFrame:
    """One row per segment, COHORT dated, plus a Total row.

    Every downstream count is attributed to the lead that generated it, so
    spend is matched to the leads it actually bought. Because closes lag lead
    arrival, sales and both cost-per-close columns read low on recent windows.
    That is inherent to cohort dating and is surfaced on the page rather than
    engineered around.

    segment_cac mirrors the existing blended_cac: (spend + close commissions)
    / sales. Payroll is excluded, exactly as blended_cac excludes it.
    """
    fb = fb.copy() if fb is not None else pd.DataFrame()
    lds = leads.copy() if leads is not None else pd.DataFrame()

    if not fb.empty:
        fb["segment"] = fb["campaign_name"].apply(
            lambda n: resolve_segment(n, segment_rollup=segment_rollup))
        spend_by_seg = fb.groupby("segment")["spend"].sum().to_dict()
    else:
        spend_by_seg = {}
    # A segment with no spend at all is dormant and is omitted. It reappears
    # automatically the moment spend resumes, because rows are enumerated
    # from the data rather than hardcoded.
    spend_by_seg = {k: float(v) for k, v in spend_by_seg.items() if v}

    leads_by_seg: dict[str, set[str]] = {}
    if not lds.empty:
        for seg, grp in lds.groupby("segment"):
            leads_by_seg[seg] = set(grp["email"].dropna())

    rows = []
    for seg in sorted(set(spend_by_seg) | set(leads_by_seg)):
        spend = spend_by_seg.get(seg, 0.0)
        emails = leads_by_seg.get(seg, set())
        n_leads = len(emails)
        n_mql = len(emails & mql_emails)
        n_call = len(emails & call_emails)
        n_sale = len(emails & sale_emails)
        commission = float(commissions_by_segment.get(seg, 0.0))
        rows.append({
            "segment": seg,
            "spend": spend,
            "leads": n_leads,
            "callable_mql": n_mql,
            "cost_cmql": _safe_div(spend, n_mql),
            "lead_to_callable_pct": _safe_div(n_mql, n_leads),
            "calls": n_call,
            "cost_per_call": _safe_div(spend, n_call),
            "callable_to_call_pct": _safe_div(n_call, n_mql),
            "sales": n_sale,
            "call_to_sale_pct": _safe_div(n_sale, n_call),
            "cost_per_close": _safe_div(spend, n_sale),
            "segment_cac": _safe_div(spend + commission, n_sale),
        })

    all_emails = set().union(*leads_by_seg.values()) if leads_by_seg else set()
    t_spend = float(sum(spend_by_seg.values()))
    t_leads = len(all_emails)
    t_mql = len(all_emails & mql_emails)
    t_call = len(all_emails & call_emails)
    t_sale = len(all_emails & sale_emails)
    t_comm = float(sum(commissions_by_segment.values()))
    rows.append({
        "segment": "Total",
        "spend": t_spend,
        "leads": t_leads,
        "callable_mql": t_mql,
        "cost_cmql": _safe_div(t_spend, t_mql),
        "lead_to_callable_pct": _safe_div(t_mql, t_leads),
        "calls": t_call,
        "cost_per_call": _safe_div(t_spend, t_call),
        "callable_to_call_pct": _safe_div(t_call, t_mql),
        "sales": t_sale,
        "call_to_sale_pct": _safe_div(t_sale, t_call),
        "cost_per_close": _safe_div(t_spend, t_sale),
        "segment_cac": _safe_div(t_spend + t_comm, t_sale),
    })
    return _frame_preserving_none(rows, SEGMENT_COLUMNS)


CREATIVE_COLUMNS = ["ad_id", "ad_name", "segment", "format", "launched",
                    "status", "story_id", "spend", "callable_mql",
                    "cost_cmql", "calls", "cost_per_call", "sales",
                    "performance"]

NOT_ENOUGH_DATA = "Not enough data"


def creative_tracker(ad_insights: pd.DataFrame,
                     ad_entities: pd.DataFrame,
                     ad_emails: dict[str, set[str]],
                     mql_emails: set[str],
                     call_emails: set[str],
                     sale_emails: set[str],
                     *,
                     segment_rollup: dict[str, str],
                     spend_floor: float,
                     winner_pct: float,
                     standout_pct: float,
                     min_mql: int,
                     ) -> pd.DataFrame:
    """One row per ad above the spend floor, scored within its own segment.

    Performance compares each ad's cost per callable MQL against the average
    for its own segment, so a Chiro ad is judged against Chiro rather than
    against NLAP. An ad must clear the spend floor AND have at least min_mql
    callable MQLs to earn any label; below that it reads "Not enough data"
    rather than being silently ranked on noise.
    """
    ads = ad_insights.copy() if ad_insights is not None else pd.DataFrame()
    if ads.empty:
        return pd.DataFrame(columns=CREATIVE_COLUMNS)

    ads = ads[ads["spend"].astype(float) >= float(spend_floor)]
    if ads.empty:
        return pd.DataFrame(columns=CREATIVE_COLUMNS)

    if ad_entities is not None and not ad_entities.empty:
        _ents = ad_entities.copy()
        _ents["ad_id"] = _ents["ad_id"].astype(str)
        ents = _ents.set_index("ad_id").to_dict("index")
    else:
        ents = {}

    rows = []
    for r in ads.itertuples(index=False):
        aid = str(r.ad_id)
        emails = ad_emails.get(aid, set())
        n_mql = len(emails & mql_emails)
        spend = float(r.spend)
        ent = ents.get(aid, {})
        rows.append({
            "ad_id": aid,
            "ad_name": r.ad_name,
            "segment": resolve_segment(r.campaign_name,
                                       segment_rollup=segment_rollup),
            # The creative object reports object_type SHARE and a null
            # video_id on every ad in this account, so video plays are the
            # only reliable format signal.
            "format": "Video" if float(getattr(r, "video_plays", 0) or 0) > 0
                      else "Static",
            "launched": str(ent.get("created_time") or "")[:10] or None,
            "status": ent.get("effective_status"),
            "story_id": ent.get("story_id"),
            "spend": spend,
            "callable_mql": n_mql,
            "cost_cmql": _safe_div(spend, n_mql),
            "calls": len(emails & call_emails),
            "cost_per_call": _safe_div(spend, len(emails & call_emails)),
            "sales": len(emails & sale_emails),
            "performance": "",
        })

    # Segment averages use only ads that cleared the volume guard, so a
    # single thin ad cannot drag its segment's benchmark around.
    per_segment: dict[str, list[float]] = {}
    for row in rows:
        if row["callable_mql"] >= min_mql and row["cost_cmql"] is not None:
            per_segment.setdefault(row["segment"], []).append(row["cost_cmql"])
    seg_avg = {s: sum(v) / len(v) for s, v in per_segment.items() if v}

    for row in rows:
        if row["callable_mql"] < min_mql or row["cost_cmql"] is None:
            row["performance"] = NOT_ENOUGH_DATA
            continue
        avg = seg_avg.get(row["segment"])
        if not avg:
            row["performance"] = NOT_ENOUGH_DATA
            continue
        delta = (avg - row["cost_cmql"]) / avg  # positive means cheaper
        if delta >= winner_pct:
            row["performance"] = "Winner"
        elif delta >= standout_pct:
            row["performance"] = "Stand Out"
        else:
            row["performance"] = ""

    out = _frame_preserving_none(rows, CREATIVE_COLUMNS)
    return out.sort_values("launched", ascending=False, na_position="last")
