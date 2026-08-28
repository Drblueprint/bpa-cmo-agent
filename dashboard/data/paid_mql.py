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
