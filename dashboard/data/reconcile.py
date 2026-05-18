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
    meetings: pd.DataFrame | None = None,
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
    - calls_booked: count of contacts with a "15 min call" meeting (source of truth)
    - strategy_calls: count of contacts with a "Strategy Call" meeting
    - cpl: spend / marketing_leads
    - cost_per_qualified_call: spend / calls_booked
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

    # Count 15-min calls + strategy calls via MEETINGS (source of truth in HubSpot).
    if meetings is None or meetings.empty:
        booked_contact_ids: set[str] = set()
        strategy_contact_ids: set[str] = set()
    else:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        fifteen_meetings = meetings[types.str.contains("15 min", na=False)]
        strategy_meetings = meetings[types.str.contains("strategy", na=False)]
        booked_contact_ids = set(
            str(cid) for cid in fifteen_meetings["contact_id"].dropna().unique()
        )
        strategy_contact_ids = set(
            str(cid) for cid in strategy_meetings["contact_id"].dropna().unique()
        )

    # Closed-won via deals (stays deal-based; a closed deal IS the signal)
    won_set = set(stages_closed_won)
    if not deals.empty and not contact_deals.empty:
        won_deal_ids = set(deals.loc[deals["dealstage"].isin(won_set), "deal_id"])
        won_contact_ids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"]
        )
        won_deal_rows = deals[deals["deal_id"].isin(won_deal_ids)][["deal_id", "amount"]]
        won_associations = contact_deals[contact_deals["deal_id"].isin(won_deal_ids)]
        revenue_by_contact = (
            won_associations.merge(won_deal_rows, on="deal_id", how="left")
            .groupby("contact_id")["amount"].sum().to_dict()
        )
    else:
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
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    stages_closed_won: Iterable[str],
) -> pd.DataFrame:
    """Return per-contact stage indicators based on meeting activity_type/outcome.

    Columns: hs_id, fifteen_min_status, strategy_status, closed_won.

    - fifteen_min_status: "Completed" if any 15-min meeting outcome starts with
      "COMPLETE"; else "Scheduled" if any 15-min meeting outcome is SCHEDULED or
      RESCHEDULED; else "".
    - strategy_status: same logic for Strategy Call meetings.
    - closed_won: "Yes" if any deal in stages_closed_won; else "".
    """
    if contacts.empty:
        return pd.DataFrame(columns=["hs_id", "fifteen_min_status",
                                     "strategy_status", "closed_won"])

    # Build per-contact outcome sets for each meeting type
    def _classify(contact_meetings: pd.DataFrame) -> str:
        """Status priority: Completed > Scheduled > No Show > Canceled > blank.

        Handles outcome variants like 'CANCELLED - BY BPA' and 'RESCHEDULED - NO BOFU'
        via prefix matching.
        """
        if contact_meetings.empty:
            return ""
        outcomes = contact_meetings["outcome"].fillna("").astype(str).str.upper().tolist()
        if any(o.startswith("COMPLETE") for o in outcomes):
            return "Completed"
        if any(o.startswith("SCHEDULED") for o in outcomes):
            return "Scheduled"
        if any(o.startswith("RESCHEDULED") for o in outcomes):
            return "Scheduled"  # rescheduled means moved, not lost
        if any("NO_SHOW" in o or o.startswith("NO SHOW") for o in outcomes):
            return "No Show"
        if any(o.startswith("CANCEL") for o in outcomes):  # catches CANCELED, CANCELLED, CANCELLED - BY *
            return "Canceled"
        return ""

    # Group meetings by contact and type for fast lookup
    if meetings.empty:
        fifteen_by_contact: dict[str, str] = {}
        strategy_by_contact: dict[str, str] = {}
    else:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        # Match "15 min call", "PT 15 Min Call", and any other "...15 min..." variant
        fifteen = meetings[types.str.contains("15 min", na=False)]
        # Match "Strategy Call" and any "...strategy..." variant
        strategy = meetings[types.str.contains("strategy", na=False)]
        fifteen_by_contact = {
            cid: _classify(grp)
            for cid, grp in fifteen.groupby("contact_id")
        }
        strategy_by_contact = {
            cid: _classify(grp)
            for cid, grp in strategy.groupby("contact_id")
        }

    # Closed-won via deals
    won_set = set(stages_closed_won)
    if deals.empty or contact_deals.empty or not won_set:
        won_contact_ids: set[str] = set()
    else:
        won_deal_ids = set(deals.loc[deals["dealstage"].isin(won_set), "deal_id"])
        won_contact_ids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"]
        )

    rows = []
    for hs_id in contacts["hs_id"]:
        cid = str(hs_id)
        rows.append({
            "hs_id": hs_id,
            "fifteen_min_status": fifteen_by_contact.get(cid, ""),
            "strategy_status": strategy_by_contact.get(cid, ""),
            "closed_won": "Yes" if cid in won_contact_ids else "",
        })
    return pd.DataFrame(rows)


def executive_kpis(
    *,
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    group_filter: str,
    asset_to_group: dict[str, str],
    group_default_amount: dict[str, float],
    stages_closed_won: Iterable[str],
    sdr_payroll_monthly: float | None,
    sme_payroll_monthly: float | None,
) -> dict:
    """Return the 15 Executive-tab KPI values for a window.

    group_filter is "All" or a specific group label. When a group is selected,
    every metric is restricted to that group.

    Returns dict with keys:
        total_ad_spend, new_leads, engaged_leads, cpl, cost_per_engaged_lead,
        discovery_booked, discovery_held, sme_booked, sme_held, closed_won,
        new_revenue, avg_deal_size, cac_ad_only, cac_full, sales_cycle_days,
        schedule_rate, discovery_show_rate, sme_set_rate, sme_show_rate, close_rate.
    """
    # --- Tag contacts with group via asset map ---
    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    # --- Apply group filter to each frame ---
    if group_filter != "All":
        fb_filtered = fb[fb["group"] == group_filter]
        contacts_filtered = contacts[contacts["group"] == group_filter]
    else:
        fb_filtered = fb
        contacts_filtered = contacts

    contact_ids_in_scope = set(contacts_filtered["hs_id"].astype(str))

    meetings_filtered = meetings[
        meetings["contact_id"].astype(str).isin(contact_ids_in_scope)
    ] if not meetings.empty else meetings

    deals_filtered_ids = set(
        contact_deals[contact_deals["contact_id"].astype(str).isin(contact_ids_in_scope)]["deal_id"]
    ) if not contact_deals.empty else set()
    deals_filtered = deals[deals["deal_id"].isin(deals_filtered_ids)] if not deals.empty else deals

    # --- Row 1: Inputs ---
    total_ad_spend = float(fb_filtered["spend"].sum()) if not fb_filtered.empty else 0.0
    new_leads = int(len(contacts_filtered))
    engaged_set = {"marketingqualifiedlead", "salesqualifiedlead", "opportunity", "customer"}
    if not contacts_filtered.empty:
        ls = contacts_filtered["lifecycle_stage"].fillna("").astype(str).str.lower()
        engaged_leads = int(ls.isin(engaged_set).sum())
    else:
        engaged_leads = 0

    cpl = _safe_div(total_ad_spend, new_leads)
    cost_per_engaged_lead = _safe_div(total_ad_spend, engaged_leads)

    # --- Row 2: Conversions (meeting-based) ---
    def _meetings_of_type(token: str) -> pd.DataFrame:
        if meetings_filtered.empty:
            return meetings_filtered
        types = meetings_filtered["activity_type"].fillna("").astype(str).str.lower()
        return meetings_filtered[types.str.contains(token, na=False)]

    fifteen = _meetings_of_type("15 min")
    strategy = _meetings_of_type("strategy")

    def _has_outcome_prefix(group_df: pd.DataFrame, prefix: str) -> set[str]:
        if group_df.empty:
            return set()
        mask = group_df["outcome"].fillna("").astype(str).str.upper().str.startswith(prefix)
        return set(group_df.loc[mask, "contact_id"].astype(str))

    discovery_booked = len(set(fifteen["contact_id"].astype(str))) if not fifteen.empty else 0
    discovery_held = len(_has_outcome_prefix(fifteen, "COMPLETE"))
    sme_booked = len(set(strategy["contact_id"].astype(str))) if not strategy.empty else 0
    sme_held = len(_has_outcome_prefix(strategy, "COMPLETE"))

    won_set = set(stages_closed_won)
    if not deals_filtered.empty and won_set:
        won_mask = deals_filtered["dealstage"].isin(won_set)
        won_deals_df = deals_filtered[won_mask]
    else:
        won_deals_df = deals_filtered.iloc[0:0] if not deals_filtered.empty else deals_filtered

    closed_won_count = int(len(won_deals_df))

    # --- Row 3: Money ---
    # Revenue Option C: deal.amount if > 0, else group default
    if not won_deals_df.empty:
        # Need to know each won deal's group via its associated contacts
        contact_to_group = dict(zip(contacts["hs_id"].astype(str), contacts["group"]))
        deal_to_contacts = (
            contact_deals[contact_deals["deal_id"].isin(won_deals_df["deal_id"])]
            .groupby("deal_id")["contact_id"].apply(list).to_dict()
        )

        def _deal_revenue(row) -> float:
            amt = float(row.get("amount") or 0)
            if amt > 0:
                return amt
            for cid in deal_to_contacts.get(row["deal_id"], []):
                g = contact_to_group.get(str(cid))
                if g and g in group_default_amount:
                    return float(group_default_amount[g])
            return 0.0

        new_revenue = float(won_deals_df.apply(_deal_revenue, axis=1).sum())
    else:
        new_revenue = 0.0

    avg_deal_size = _safe_div(new_revenue, closed_won_count)

    cac_ad_only = _safe_div(total_ad_spend, closed_won_count)
    if sdr_payroll_monthly is not None and sme_payroll_monthly is not None and closed_won_count:
        cac_full = (total_ad_spend + sdr_payroll_monthly + sme_payroll_monthly) / closed_won_count
    else:
        cac_full = None

    # Sales cycle: median days from contact.createdate to deal.closedate for won deals
    if not won_deals_df.empty:
        cycle_days = []
        for _, deal_row in won_deals_df.iterrows():
            for cid in deal_to_contacts.get(deal_row["deal_id"], []):
                contact = contacts[contacts["hs_id"].astype(str) == str(cid)]
                if contact.empty:
                    continue
                try:
                    created = pd.to_datetime(contact.iloc[0]["createdate"], utc=True, errors="coerce")
                    closed = pd.to_datetime(deal_row.get("closedate"), utc=True, errors="coerce")
                    if pd.notna(created) and pd.notna(closed):
                        cycle_days.append((closed - created).days)
                except Exception:
                    continue
        sales_cycle_days = float(pd.Series(cycle_days).median()) if cycle_days else None
    else:
        sales_cycle_days = None

    # --- Conversion rates ---
    schedule_rate = _safe_div(discovery_booked, new_leads)
    discovery_show_rate = _safe_div(discovery_held, discovery_booked)
    sme_set_rate = _safe_div(sme_booked, discovery_held)
    sme_show_rate = _safe_div(sme_held, sme_booked)
    close_rate = _safe_div(closed_won_count, sme_held)

    return {
        # Row 1
        "total_ad_spend": total_ad_spend,
        "new_leads": new_leads,
        "engaged_leads": engaged_leads,
        "cpl": cpl,
        "cost_per_engaged_lead": cost_per_engaged_lead,
        # Row 2 raw counts
        "discovery_booked": discovery_booked,
        "discovery_held": discovery_held,
        "sme_booked": sme_booked,
        "sme_held": sme_held,
        "closed_won": closed_won_count,
        # Row 2 rates
        "schedule_rate": schedule_rate,
        "discovery_show_rate": discovery_show_rate,
        "sme_set_rate": sme_set_rate,
        "sme_show_rate": sme_show_rate,
        "close_rate": close_rate,
        # Row 3 money
        "new_revenue": new_revenue,
        "avg_deal_size": avg_deal_size,
        "cac_ad_only": cac_ad_only,
        "cac_full": cac_full,
        "sales_cycle_days": sales_cycle_days,
    }


def executive_sdr_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
) -> pd.DataFrame:
    """Per-SDR-owner rollup for the Executive tab.

    Columns: sdr_id, leads_worked, discovery_booked, schedule_rate,
             discovery_held, show_rate.
    """
    if contacts.empty:
        return pd.DataFrame(columns=["sdr_id", "leads_worked", "discovery_booked",
                                     "schedule_rate", "discovery_held", "show_rate"])

    types = meetings["activity_type"].fillna("").astype(str).str.lower() \
        if not meetings.empty else pd.Series(dtype=str)
    fifteen = meetings[types.str.contains("15 min", na=False)] if not meetings.empty else meetings

    # Per-contact stage flags
    booked_contact_ids = set(fifteen["contact_id"].astype(str)) if not fifteen.empty else set()
    held_contact_ids = set()
    if not fifteen.empty:
        out = fifteen["outcome"].fillna("").astype(str).str.upper()
        held_contact_ids = set(fifteen.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str))

    rows = []
    for sdr_id, grp in contacts.groupby("sdr_owner", dropna=False):
        worked = int(len(grp))
        ids = set(grp["hs_id"].astype(str))
        booked = len(ids & booked_contact_ids)
        held = len(ids & held_contact_ids)
        rows.append({
            "sdr_id": str(sdr_id) if pd.notna(sdr_id) else "",
            "leads_worked": worked,
            "discovery_booked": booked,
            "schedule_rate": _safe_div(booked, worked),
            "discovery_held": held,
            "show_rate": _safe_div(held, booked),
        })
    return pd.DataFrame(rows).sort_values("discovery_booked", ascending=False)


def executive_sme_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    group_default_amount: dict[str, float],
    stages_closed_won: Iterable[str],
) -> pd.DataFrame:
    """Per-SME (BDS) rollup for the Executive tab.

    Columns: sme_id, sme_calls_held, deals_closed, close_rate, revenue, revenue_per_call.
    """
    cols = ["sme_id", "sme_calls_held", "deals_closed", "close_rate",
            "revenue", "revenue_per_call"]
    if contacts.empty:
        return pd.DataFrame(columns=cols)

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    # Strategy meetings, COMPLETE-prefix outcomes
    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        strategy = meetings[types.str.contains("strategy", na=False)]
        if not strategy.empty:
            out = strategy["outcome"].fillna("").astype(str).str.upper()
            sme_held_contact_ids = set(
                strategy.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str)
            )
        else:
            sme_held_contact_ids = set()
    else:
        sme_held_contact_ids = set()

    # Closed-won deals + contacts associated
    won_set = set(stages_closed_won)
    if not deals.empty and not contact_deals.empty and won_set:
        won_deal_ids = set(deals.loc[deals["dealstage"].isin(won_set), "deal_id"])
        won_contact_ids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"].astype(str)
        )
        # Revenue per contact (Option C)
        contact_to_group = dict(zip(contacts["hs_id"].astype(str), contacts["group"]))

        def _deal_revenue(row) -> float:
            amt = float(row.get("amount") or 0)
            if amt > 0:
                return amt
            cids = contact_deals[contact_deals["deal_id"] == row["deal_id"]]["contact_id"].astype(str)
            for cid in cids:
                g = contact_to_group.get(cid)
                if g and g in group_default_amount:
                    return float(group_default_amount[g])
            return 0.0

        won_deals = deals[deals["dealstage"].isin(won_set)].copy()
        won_deals["effective_amount"] = won_deals.apply(_deal_revenue, axis=1)

        deal_revenue_map = dict(zip(won_deals["deal_id"], won_deals["effective_amount"]))
        contact_revenue: dict[str, float] = {}
        for _, row in contact_deals.iterrows():
            cid = str(row["contact_id"])
            did = row["deal_id"]
            if did in deal_revenue_map:
                contact_revenue[cid] = contact_revenue.get(cid, 0.0) + deal_revenue_map[did]
    else:
        won_contact_ids = set()
        contact_revenue = {}

    rows = []
    for sme_id, grp in contacts.groupby("bds", dropna=False):
        cids = set(grp["hs_id"].astype(str))
        held = len(cids & sme_held_contact_ids)
        closed = len(cids & won_contact_ids)
        revenue = sum(contact_revenue.get(c, 0.0) for c in cids)
        rows.append({
            "sme_id": str(sme_id) if pd.notna(sme_id) else "",
            "sme_calls_held": held,
            "deals_closed": closed,
            "close_rate": _safe_div(closed, held),
            "revenue": revenue,
            "revenue_per_call": _safe_div(revenue, held),
        })
    return pd.DataFrame(rows, columns=cols).sort_values("revenue", ascending=False)
