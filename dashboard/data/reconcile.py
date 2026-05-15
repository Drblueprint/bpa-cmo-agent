"""Cross-source aggregation. Hyros is the headline source for leads;
FB is the source of truth for spend; HubSpot tracks MQL (typeform completions)."""
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
    hyros: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return per-group marketing metrics.

    Columns: group, spend, leads, mql, calls_booked, cpl, cost_per_qualified_call.

    - spend: sum of FB spend rows whose group matches
    - leads: Hyros-attributed lead count (top-of-funnel, ad-attributed)
    - mql: count of HubSpot contacts who completed the typeform (deeper funnel stage)
    - calls_booked: count of contacts with fifteen_min_call_date populated OR
      lifecycle_stage == "marketingqualifiedlead" (contact-property source of truth)
    - cpl: spend / leads (Hyros)
    - cost_per_qualified_call: spend / calls_booked

    Note: `contact_deals` and `stages_15min_booked` are kept in the signature
    for API compatibility but no longer drive any counts.
    """
    fb_by_group = fb.groupby("group", dropna=True)["spend"].sum().to_dict()
    fb_leads_by_group = fb.groupby("group", dropna=True)["fb_leads"].sum().to_dict() \
        if "fb_leads" in fb.columns else {}

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    # Hyros leads -> grouped via regex on first_source (campaign-name match)
    from dashboard.data.groups import match_group
    if hyros is None or hyros.empty:
        hyros_by_group: dict[str, int] = {}
    else:
        h = hyros.copy()
        h["group"] = h["first_source"].map(match_group)
        hyros_by_group = h.groupby("group", dropna=True).size().to_dict()

    # Calls booked uses contact-level n15_min_call_date OR lifecycle=MQL
    # The legacy deal-stage parameters `contact_deals` and `stages_15min_booked` are
    # kept in the signature for API compatibility but no longer drive the count.
    has_call_date = contacts.get("fifteen_min_call_date").notna() \
        if "fifteen_min_call_date" in contacts.columns else pd.Series(False, index=contacts.index)
    has_call_date = has_call_date & (contacts.get("fifteen_min_call_date") != "")
    is_mql = contacts.get("lifecycle_stage", pd.Series(dtype=str)).fillna("") \
        .astype(str).str.lower().eq("marketingqualifiedlead")
    booked_mask = has_call_date | is_mql
    booked_contact_ids = set(contacts.loc[booked_mask, "hs_id"])

    groups = sorted({*fb_by_group.keys(),
                     *contacts["group"].dropna().unique(),
                     *hyros_by_group.keys()})
    rows = []
    for g in groups:
        hyros_count = int(hyros_by_group.get(g, 0))
        fb_count = int(fb_leads_by_group.get(g, 0))
        leads = hyros_count if hyros_count > 0 else fb_count
        leads_source = "hyros" if hyros_count > 0 else ("fb" if fb_count > 0 else "none")
        mql = int((contacts["group"] == g).sum())      # <- HubSpot typeform completions
        booked = int(((contacts["group"] == g) &
                      contacts["hs_id"].isin(booked_contact_ids)).sum())
        spend = float(fb_by_group.get(g, 0.0))
        rows.append({
            "group": g,
            "spend": spend,
            "leads": leads,
            "leads_source": leads_source,
            "mql": mql,
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


STAGE_LABELS = [
    ("15-min Booked", "15min_booked"),
    ("15-min Held", "15min_held"),
    ("Strategy Booked", "strategy_booked"),
    ("Strategy Held", "strategy_held"),
    ("Closed-Won", "closedwon"),
]


def pipeline_funnel(
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    stage_groups: dict[str, set[str]],
    marketing_only: bool,
) -> pd.DataFrame:
    """Return funnel counts and revenue per stage.

    Columns: stage, count, revenue.
    - marketing_only=True restricts to deals whose contacts have a typeform asset.
    - stage_groups maps logical stage keys (e.g. "15min_booked") to sets of
      HubSpot dealstage internal IDs that count for that stage.
    """
    if marketing_only and not contacts.empty:
        marketing_ids = set(contacts["hs_id"])
        marketing_deals = set(
            contact_deals.loc[contact_deals["contact_id"].isin(marketing_ids), "deal_id"]
        )
        d = deals[deals["deal_id"].isin(marketing_deals)]
    else:
        d = deals

    rows = []
    for label, key in STAGE_LABELS:
        stages = stage_groups.get(key, set())
        sub = d[d["dealstage"].isin(stages)]
        rows.append({
            "stage": label,
            "count": int(len(sub)),
            "revenue": float(sub["amount"].sum()),
        })
    return pd.DataFrame(rows)


def owner_rollup(
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    owner_field: str,
    stage_groups: dict[str, set[str]],
) -> pd.DataFrame:
    """Aggregate funnel metrics by a contact-level owner field.

    Columns: owner, calls_15min, strategy_calls, closed_won, closed_won_revenue.
    """
    if contacts.empty:
        return pd.DataFrame(columns=["owner", "calls_15min", "strategy_calls",
                                     "closed_won", "closed_won_revenue"])

    cd = contact_deals.merge(
        contacts[["hs_id", owner_field]].rename(columns={"hs_id": "contact_id"}),
        on="contact_id", how="left",
    )
    cd = cd.merge(deals[["deal_id", "dealstage", "amount"]],
                   on="deal_id", how="left")

    s15 = stage_groups.get("15min_booked", set())
    sst = stage_groups.get("strategy_booked", set())
    scw = stage_groups.get("closedwon", set())

    rows = []
    for owner, sub in cd.groupby(owner_field, dropna=False):
        rows.append({
            "owner": owner or "(unassigned)",
            "calls_15min": int(sub["dealstage"].isin(s15).sum()),
            "strategy_calls": int(sub["dealstage"].isin(sst).sum()),
            "closed_won": int(sub["dealstage"].isin(scw).sum()),
            "closed_won_revenue": float(sub.loc[sub["dealstage"].isin(scw), "amount"].sum()),
        })
    columns = ["owner", "calls_15min", "strategy_calls",
               "closed_won", "closed_won_revenue"]
    return pd.DataFrame(rows, columns=columns).sort_values(
        "closed_won_revenue", ascending=False)
