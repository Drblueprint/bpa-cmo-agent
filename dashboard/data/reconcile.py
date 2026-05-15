"""Cross-source aggregation. HubSpot is the source of truth for leads and
calls; FB is the source of truth for spend; Hyros is the cross-check."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def _safe_div(num: float, den: float) -> float | None:
    if not den:
        return None
    return num / den


def group_marketing_metrics(
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    stages_15min_booked: Iterable[str],
) -> pd.DataFrame:
    """Return per-group marketing metrics.

    Columns: group, spend, leads, calls_booked, cpl, cost_per_qualified_call.

    - spend: sum of FB spend rows whose group matches
    - leads: count of contacts whose typeform_asset_download maps to the group
    - calls_booked: count of contacts whose deals contain a 15-min stage
    - cpl: spend / leads
    - cost_per_qualified_call: spend / calls_booked
    """
    fb_by_group = fb.groupby("group", dropna=True)["spend"].sum().to_dict()

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    stages_set = set(stages_15min_booked)
    booked_deal_ids = set(deals.loc[deals["dealstage"].isin(stages_set), "deal_id"])
    booked_contact_ids = set(
        contact_deals.loc[contact_deals["deal_id"].isin(booked_deal_ids), "contact_id"]
    )

    groups = sorted({*fb_by_group.keys(), *contacts["group"].dropna().unique()})
    rows = []
    for g in groups:
        leads = int((contacts["group"] == g).sum())
        booked = int(((contacts["group"] == g) &
                      contacts["hs_id"].isin(booked_contact_ids)).sum())
        spend = float(fb_by_group.get(g, 0.0))
        rows.append({
            "group": g,
            "spend": spend,
            "leads": leads,
            "calls_booked": booked,
            "cpl": _safe_div(spend, leads),
            "cost_per_qualified_call": _safe_div(spend, booked),
        })
    return pd.DataFrame(rows)


def reconciliation_panel(
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    hyros: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
) -> pd.DataFrame:
    """Return per-group lead counts from each source for cross-check.

    Columns: group, fb_leads, hyros_leads, hubspot_leads, match_rate.

    match_rate = min(hyros_leads, hubspot_leads) / hubspot_leads. This is "how
    much of HubSpot's lead count Hyros covers" — values approach 1.0 when Hyros
    and HubSpot agree; lower values mean Hyros is missing leads HubSpot has.
    Returns None when HubSpot has zero leads.

    Note: callers must pass an `fb` DataFrame that includes both `spend` (used
    by group_marketing_metrics) and `fb_leads` (used here) columns.
    """
    fb_by_group = fb.groupby("group", dropna=True)["fb_leads"].sum().to_dict()

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)
    hs_by_group = contacts.groupby("group", dropna=True).size().to_dict()

    # Hyros first_source typically contains the FB campaign name — match groups by regex
    from dashboard.data.groups import match_group
    if not hyros.empty:
        hyros = hyros.copy()
        hyros["group"] = hyros["first_source"].map(match_group)
        hy_by_group = hyros.groupby("group", dropna=True).size().to_dict()
    else:
        hy_by_group = {}

    groups = sorted({*fb_by_group.keys(), *hs_by_group.keys(), *hy_by_group.keys()})
    rows = []
    for g in groups:
        hs = int(hs_by_group.get(g, 0))
        hy = int(hy_by_group.get(g, 0))
        rate = (min(hy, hs) / hs) if hs else None
        rows.append({
            "group": g,
            "fb_leads": int(fb_by_group.get(g, 0)),
            "hyros_leads": hy,
            "hubspot_leads": hs,
            "match_rate": rate,
        })
    return pd.DataFrame(rows)
