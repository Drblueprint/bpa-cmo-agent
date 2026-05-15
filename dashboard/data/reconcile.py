"""Cross-source aggregation. Typeform submissions are the headline Marketing Leads;
FB is the source of truth for spend; Hyros is a secondary diagnostic for ad attribution."""
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
    stages_strategy: Iterable[str] = (),
    stages_closed_won: Iterable[str] = (),
) -> pd.DataFrame:
    """Return per-group marketing metrics.

    Columns: group, spend, marketing_leads, marketing_leads_source, hyros_leads,
             calls_booked, strategy_calls, closed_won, closed_won_revenue,
             cpl, cost_per_qualified_call.

    - spend: sum of FB spend rows whose group matches
    - marketing_leads: typeform submissions (source of truth); falls back to FB lead
      count for groups that don't use a typeform (e.g. TheraRay)
    - marketing_leads_source: "typeform" | "fb" | "none"
    - hyros_leads: Hyros-attributed ad click count (diagnostic, not source of truth)
    - calls_booked: count of contacts with fifteen_min_call_date populated OR
      lifecycle_stage == "marketingqualifiedlead" (contact-property source of truth)
    - cpl: spend / marketing_leads
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

    # Per-contact deal-stage progression
    strategy_set = set(stages_strategy)
    won_set = set(stages_closed_won)
    if not deals.empty and not contact_deals.empty:
        strategy_deal_ids = set(
            deals.loc[deals["dealstage"].isin(strategy_set), "deal_id"]
        )
        won_deal_ids = set(
            deals.loc[deals["dealstage"].isin(won_set), "deal_id"]
        )
        strategy_contact_ids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(strategy_deal_ids), "contact_id"]
        )
        won_contact_ids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"]
        )
        # Revenue per contact (sum of amounts from won deals associated to them)
        won_deal_rows = deals[deals["deal_id"].isin(won_deal_ids)][["deal_id", "amount"]]
        won_associations = contact_deals[contact_deals["deal_id"].isin(won_deal_ids)]
        revenue_by_contact = (
            won_associations.merge(won_deal_rows, on="deal_id", how="left")
            .groupby("contact_id")["amount"].sum().to_dict()
        )
    else:
        strategy_contact_ids = set()
        won_contact_ids = set()
        revenue_by_contact = {}

    groups = sorted({*fb_by_group.keys(),
                     *contacts["group"].dropna().unique(),
                     *hyros_by_group.keys()})
    rows = []
    for g in groups:
        hyros_count = int(hyros_by_group.get(g, 0))
        fb_count = int(fb_leads_by_group.get(g, 0))
        typeform_count = int((contacts["group"] == g).sum())
        # "Marketing Leads" = typeform submissions, with FB fallback for groups
        # that don't use a typeform (e.g. TheraRay).
        marketing_leads = typeform_count if typeform_count > 0 else fb_count
        marketing_leads_source = "typeform" if typeform_count > 0 else \
            ("fb" if fb_count > 0 else "none")
        booked = int(((contacts["group"] == g) &
                      contacts["hs_id"].isin(booked_contact_ids)).sum())
        spend = float(fb_by_group.get(g, 0.0))
        group_mask = (contacts["group"] == g)
        strategy = int((group_mask & contacts["hs_id"].isin(strategy_contact_ids)).sum())
        won = int((group_mask & contacts["hs_id"].isin(won_contact_ids)).sum())
        won_revenue = float(
            sum(revenue_by_contact.get(cid, 0.0)
                for cid in contacts.loc[group_mask & contacts["hs_id"].isin(won_contact_ids), "hs_id"])
        )
        rows.append({
            "group": g,
            "spend": spend,
            "marketing_leads": marketing_leads,
            "marketing_leads_source": marketing_leads_source,
            "hyros_leads": hyros_count,
            "calls_booked": booked,
            "strategy_calls": strategy,
            "closed_won": won,
            "closed_won_revenue": won_revenue,
            "cpl": _safe_div(spend, marketing_leads),
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


def per_contact_journey(
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    stages_15min_booked: Iterable[str],
    stages_15min_held: Iterable[str],
    stages_strategy_booked: Iterable[str],
    stages_strategy_held: Iterable[str],
    stages_closed_won: Iterable[str],
) -> pd.DataFrame:
    """Return per-contact stage indicators.

    Columns: hs_id, fifteen_min_status, strategy_status, closed_won.
    - fifteen_min_status: "Completed" if any deal in 15min_held; else "Scheduled" if
      n15_min_call_date set OR lifecycle=MQL OR any deal in 15min_booked; else "".
    - strategy_status: "Completed" if any deal in strategy_held; else "Scheduled" if
      any deal in strategy_booked; else "".
    - closed_won: "Yes" if any deal in closed_won; else "".
    """
    if contacts.empty:
        return pd.DataFrame(columns=["hs_id", "fifteen_min_status",
                                     "strategy_status", "closed_won"])

    def _stage_contact_ids(stages: Iterable[str]) -> set[str]:
        s = set(stages)
        if deals.empty or contact_deals.empty or not s:
            return set()
        deal_ids = set(deals.loc[deals["dealstage"].isin(s), "deal_id"])
        if not deal_ids:
            return set()
        return set(contact_deals.loc[contact_deals["deal_id"].isin(deal_ids), "contact_id"])

    ids_15min_scheduled = _stage_contact_ids(stages_15min_booked)
    ids_15min_completed = _stage_contact_ids(stages_15min_held)
    ids_strategy_scheduled = _stage_contact_ids(stages_strategy_booked)
    ids_strategy_completed = _stage_contact_ids(stages_strategy_held)
    ids_won = _stage_contact_ids(stages_closed_won)

    # Contact-property signals for 15-min
    has_call_date = contacts.get("fifteen_min_call_date", pd.Series(dtype=str)) \
        .fillna("").astype(str).str.strip() != ""
    is_mql = contacts.get("lifecycle_stage", pd.Series(dtype=str)) \
        .fillna("").astype(str).str.lower().eq("marketingqualifiedlead")

    rows = []
    for i, hs_id in enumerate(contacts["hs_id"]):
        prop_scheduled = bool(has_call_date.iloc[i] or is_mql.iloc[i])
        if hs_id in ids_15min_completed:
            fifteen = "Completed"
        elif prop_scheduled or hs_id in ids_15min_scheduled:
            fifteen = "Scheduled"
        else:
            fifteen = ""

        if hs_id in ids_strategy_completed:
            strategy = "Completed"
        elif hs_id in ids_strategy_scheduled:
            strategy = "Scheduled"
        else:
            strategy = ""

        won = "Yes" if hs_id in ids_won else ""
        rows.append({
            "hs_id": hs_id,
            "fifteen_min_status": fifteen,
            "strategy_status": strategy,
            "closed_won": won,
        })
    return pd.DataFrame(rows)
