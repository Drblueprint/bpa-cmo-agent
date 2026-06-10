"""Cross-source aggregation. Typeform submissions are the headline Marketing Leads;
FB is the source of truth for spend; Hyros is a secondary diagnostic for ad attribution."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def _group_from_tier(tier: str | None) -> str | None:
    """Derive group (Chiro / PT Recovery) from contract_tier suffix.

    Tiers follow pattern '<n> <PLAN> - <SUFFIX>' where suffix is:
      C / CC  -> Chiro
      PT / PTC -> PT Recovery

    Returns None for unrecognized or missing tiers.
    """
    if not tier:
        return None
    t = str(tier).upper().strip()
    # Check suffix tokens (most-specific first)
    if t.endswith(" - PTC") or t.endswith(" - PT") or t.endswith("- PT"):
        return "PT Recovery"
    if t.endswith(" - CC") or t.endswith(" - C") or t.endswith("- C"):
        return "Chiro"
    # Free-form tiers (METABOLIC, TRIAL, BASIC - NOT CERTIFIED, etc.)
    return None


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
    - marketing_only=True restricts to deals whose contacts have a typeform
      asset populated. Callers may pass an expanded contacts DataFrame (all
      contacts associated with deals in the window, including non-marketing
      ones); this function does the typeform filter itself so callers can
      pass the same contacts to fn_mkt and fn_all.
    - stage_groups maps logical stage keys (e.g. "15min_booked") to sets of
      HubSpot dealstage internal IDs that count for that stage.
    """
    if marketing_only and not contacts.empty:
        if "typeform_asset_download" in contacts.columns:
            mkt = contacts[
                contacts["typeform_asset_download"].notna()
                & (contacts["typeform_asset_download"].astype(str).str.strip() != "")
            ]
        else:
            mkt = contacts
        marketing_ids = set(mkt["hs_id"])
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

    # Funnel-stage contact sets — intersection-based so each stage is a strict
    # subset of the previous. Guarantees the funnel rates can never exceed 100%.
    discovery_booked_cids = set(fifteen["contact_id"].astype(str)) if not fifteen.empty else set()
    discovery_held_cids = _has_outcome_prefix(fifteen, "COMPLETE")
    strategy_booked_cids_raw = set(strategy["contact_id"].astype(str)) if not strategy.empty else set()
    strategy_held_cids_raw = _has_outcome_prefix(strategy, "COMPLETE")
    # Intersect strategy_booked with discovery_held so the rate measures
    # "of disco-holds, how many advanced to a strategy booking".
    sme_booked_cids = strategy_booked_cids_raw & discovery_held_cids
    sme_held_cids = strategy_held_cids_raw & sme_booked_cids

    discovery_booked = len(discovery_booked_cids)
    discovery_held = len(discovery_held_cids)
    sme_booked = len(sme_booked_cids)
    sme_held = len(sme_held_cids)

    won_set = set(stages_closed_won)
    if not deals_filtered.empty and won_set:
        won_mask = deals_filtered["dealstage"].isin(won_set)
        won_deals_df = deals_filtered[won_mask]
    else:
        won_deals_df = deals_filtered.iloc[0:0] if not deals_filtered.empty else deals_filtered

    # closed_won_count = unique CONTACTS with a closed-won deal (not raw deal
    # count) — drives Avg Deal Size + CAC + Money cards.
    # closed_won_from_funnel = subset that also held a Strategy — drives the
    # Close Rate funnel card so it stays monotonic ≤ 100%.
    won_contact_ids: set = set()
    if not won_deals_df.empty and not contact_deals.empty:
        won_contact_ids = set(
            contact_deals[contact_deals["deal_id"].isin(won_deals_df["deal_id"])]
            ["contact_id"].astype(str)
        )
    closed_won_count = len(won_contact_ids)
    closed_won_from_funnel = len(won_contact_ids & sme_held_cids)

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

    # --- Conversion rates (each stage strictly subset of the prior) ---
    schedule_rate = _safe_div(discovery_booked, new_leads)
    discovery_show_rate = _safe_div(discovery_held, discovery_booked)
    sme_set_rate = _safe_div(sme_booked, discovery_held)
    sme_show_rate = _safe_div(sme_held, sme_booked)
    close_rate = _safe_div(closed_won_from_funnel, sme_held)

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
        "closed_won_from_funnel": closed_won_from_funnel,
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
    for sme_id, grp in contacts.groupby("sme", dropna=False):
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


def executive_bds_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
) -> pd.DataFrame:
    """Per-BDS rollup for the Executive tab.

    BDS holds the 15-min discovery and books the Strategy call. Metrics track
    the BDS funnel: held a discovery, advanced to strategy (set rate),
    strategy held (show rate).

    Columns: bds_id, discovery_held, strategy_booked, set_rate,
             strategy_held, show_rate.
    """
    cols = ["bds_id", "discovery_held", "strategy_booked",
            "set_rate", "strategy_held", "show_rate"]
    if contacts.empty:
        return pd.DataFrame(columns=cols)

    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        fifteen = meetings[types.str.contains("15 min", na=False)]
        strategy = meetings[types.str.contains("strategy", na=False)]

        held_disco_ids: set[str] = set()
        if not fifteen.empty:
            out = fifteen["outcome"].fillna("").astype(str).str.upper()
            held_disco_ids = set(
                fifteen.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str)
            )

        booked_strat_ids = set(strategy["contact_id"].astype(str)) \
            if not strategy.empty else set()

        held_strat_ids: set[str] = set()
        if not strategy.empty:
            out = strategy["outcome"].fillna("").astype(str).str.upper()
            held_strat_ids = set(
                strategy.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str)
            )
    else:
        held_disco_ids = set()
        booked_strat_ids = set()
        held_strat_ids = set()

    rows = []
    for bds_id, grp in contacts.groupby("bds", dropna=False):
        ids = set(grp["hs_id"].astype(str))
        disco_held = len(ids & held_disco_ids)
        strat_booked = len(ids & booked_strat_ids)
        strat_held = len(ids & held_strat_ids)
        rows.append({
            "bds_id": str(bds_id) if pd.notna(bds_id) else "",
            "discovery_held": disco_held,
            "strategy_booked": strat_booked,
            "set_rate": _safe_div(strat_booked, disco_held),
            "strategy_held": strat_held,
            "show_rate": _safe_div(strat_held, strat_booked),
        })
    return pd.DataFrame(rows, columns=cols).sort_values("strategy_held", ascending=False)


def normalize_phone(s) -> str:
    """Last-10-digits normalization. US phone format-agnostic."""
    if s is None:
        return ""
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def compute_speed_to_lead(
    contacts: pd.DataFrame,
    calls: pd.DataFrame,
    *,
    lead_window_start=None,
) -> pd.DataFrame:
    """For each contact, find the first OUTBOUND AirCall to their phone AFTER
    their typeform_submission_date. (Falls back to HubSpot createdate if the
    submission timestamp is missing.)

    - lead_window_start: optional date. Contacts whose lead_in_ts is before
      this cutoff are EXCLUDED from the result. Use when callers pass an
      expanded contacts list that may include older typeform submissions
      whose first call in the AirCall window is meaningless (they weren't
      actually "called fast" — there were months of calls in between that
      we just don't have loaded).

    Returns DataFrame with columns: hs_id, speed_to_lead_minutes (NaN if no match).
    """
    if contacts.empty:
        return pd.DataFrame(columns=["hs_id", "speed_to_lead_minutes"])

    contacts = contacts.copy()
    contacts["phone_norm"] = contacts.apply(
        lambda r: normalize_phone(r.get("phone")) or normalize_phone(r.get("mobilephone")),
        axis=1,
    )

    # Lead-in moment: typeform submission timestamp (when they actually filled
    # the form this cycle). Falls back to createdate only when submission_date
    # is missing -- rare, for contacts that pre-date the typeform property.
    def _lead_in_ts(row) -> float:
        for col in ("typeform_submission_date", "created"):
            val = row.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
                continue
            try:
                ts = pd.to_datetime(val, utc=True, errors="coerce")
                if pd.notna(ts):
                    return int(ts.timestamp())
            except Exception:
                continue
        return float("nan")

    contacts["lead_in_ts"] = contacts.apply(_lead_in_ts, axis=1)

    # Apply lead-window cutoff so stale leads (whose typeform predates the
    # call window) don't pollute the median.
    if lead_window_start is not None:
        cutoff_ts = int(pd.Timestamp(lead_window_start).tz_localize("UTC").timestamp())
        contacts = contacts[
            contacts["lead_in_ts"].notna()
            & (contacts["lead_in_ts"] >= cutoff_ts)
        ]
        if contacts.empty:
            return pd.DataFrame(columns=["hs_id", "speed_to_lead_minutes"])

    outbound = calls[calls["direction"] == "outbound"] if not calls.empty else calls

    rows = []
    for _, contact in contacts.iterrows():
        phone = contact["phone_norm"]
        lead_in_ts = contact["lead_in_ts"]
        if not phone or pd.isna(lead_in_ts):
            rows.append({"hs_id": contact["hs_id"],
                         "speed_to_lead_minutes": float("nan")})
            continue
        matched = outbound[
            (outbound["phone_normalized"] == phone)
            & (outbound["started_at_utc"] >= lead_in_ts)
        ] if not outbound.empty else outbound
        if matched.empty:
            rows.append({"hs_id": contact["hs_id"],
                         "speed_to_lead_minutes": float("nan")})
            continue
        first_ts = matched["started_at_utc"].min()
        minutes = (first_ts - lead_in_ts) / 60.0
        rows.append({"hs_id": contact["hs_id"],
                     "speed_to_lead_minutes": float(minutes)})

    return pd.DataFrame(rows)


def sdr_call_activity(
    contacts: pd.DataFrame,
    calls: pd.DataFrame,
    meetings: pd.DataFrame,
    *,
    aircall_user_names: dict,
    excluded_users: set,
    connect_duration_sec: int,
    conv_window_hours: int,
    lead_window_start=None,
) -> pd.DataFrame:
    """Per-AirCall-user dial activity for the SALES tab SDR Call Activity table.

    Columns: user_id, user_name, dials, connects, connect_rate, talk_time_min,
             conv_to_discovery_rate, median_speed_to_lead_min.
    """
    cols = ["user_id", "user_name", "dials", "connects", "connect_rate",
            "talk_time_min", "conv_to_discovery_rate", "median_speed_to_lead_min"]

    if calls.empty:
        return pd.DataFrame(columns=cols)

    outbound = calls[calls["direction"] == "outbound"].copy()
    if excluded_users:
        outbound = outbound[~outbound["user_id"].isin(excluded_users)]

    # Connect = outbound + answered + duration >= threshold
    is_connect = (
        outbound["answered_at_utc"].notna()
        & (outbound["duration"] >= connect_duration_sec)
    )
    outbound = outbound.copy()
    outbound["is_connect"] = is_connect

    # Pre-compute speed to lead per contact for downstream attribution
    speed_df = compute_speed_to_lead(
        contacts, calls, lead_window_start=lead_window_start
    )
    speed_map = dict(zip(speed_df["hs_id"].astype(str),
                         speed_df["speed_to_lead_minutes"]))

    # Phone -> list of contact_ids for joining
    contacts_x = contacts.copy()
    if not contacts_x.empty:
        contacts_x["phone_norm"] = contacts_x.apply(
            lambda r: normalize_phone(r.get("phone")) or normalize_phone(r.get("mobilephone")),
            axis=1,
        )
        phone_to_contacts: dict = {}
        for _, c in contacts_x.iterrows():
            phone_to_contacts.setdefault(c["phone_norm"], []).append(str(c["hs_id"]))
    else:
        phone_to_contacts = {}

    # 15-min meetings indexed by contact_id + start ts
    fifteen_meetings = pd.DataFrame()
    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        fifteen_meetings = meetings[types.str.contains("15 min", na=False)].copy()
        if not fifteen_meetings.empty:
            # Prefer an explicit created_at_utc if present; else parse start_time
            if "created_at_utc" not in fifteen_meetings.columns:
                fifteen_meetings["created_at_utc"] = (
                    pd.to_datetime(fifteen_meetings["start_time"], utc=True, errors="coerce")
                    .apply(lambda x: int(x.timestamp()) if pd.notna(x) else float("nan"))
                )
            fifteen_meetings["contact_id"] = fifteen_meetings["contact_id"].astype(str)

    conv_window_sec = conv_window_hours * 3600

    rows = []
    for user_id, grp in outbound.groupby("user_id"):
        if not user_id:
            continue
        dials = int(len(grp))
        connects = int(grp["is_connect"].sum())
        connect_rate = _safe_div(connects, dials)
        talk_time_min = float(grp.loc[grp["is_connect"], "duration"].sum() / 60.0)

        # Conv -> Discovery: of the connects, what fraction had a 15-min booked
        # for any matched contact within the window AFTER the call?
        connect_rows = grp[grp["is_connect"]]
        if connect_rows.empty or fifteen_meetings.empty:
            conv_to_discovery_rate = None
        else:
            attributable = 0
            countable = 0
            for _, call_row in connect_rows.iterrows():
                phone = call_row["phone_normalized"]
                cids = phone_to_contacts.get(phone, [])
                if not cids:
                    continue
                countable += 1
                call_ts = call_row["started_at_utc"]
                # Did ANY of these contacts get a 15-min booked within window?
                booked = fifteen_meetings[
                    fifteen_meetings["contact_id"].isin(cids)
                    & (fifteen_meetings["created_at_utc"] >= call_ts)
                    & (fifteen_meetings["created_at_utc"] <= call_ts + conv_window_sec)
                ]
                if not booked.empty:
                    attributable += 1
            conv_to_discovery_rate = _safe_div(attributable, countable)

        # Median speed-to-lead across contacts this user called
        user_speeds = []
        for phone in grp["phone_normalized"].unique():
            for cid in phone_to_contacts.get(phone, []):
                m = speed_map.get(cid)
                if m is not None and not pd.isna(m):
                    user_speeds.append(m)
        median_speed = float(pd.Series(user_speeds).median()) if user_speeds else None

        rows.append({
            "user_id": str(user_id),
            "user_name": aircall_user_names.get(str(user_id), f"(user {user_id})"),
            "dials": dials,
            "connects": connects,
            "connect_rate": connect_rate,
            "talk_time_min": talk_time_min,
            "conv_to_discovery_rate": conv_to_discovery_rate,
            "median_speed_to_lead_min": median_speed,
        })

    # Build as object dtype first to preserve None vs NaN distinction for rate columns.
    df = pd.DataFrame(rows, columns=cols)
    for rate_col in ("connect_rate", "conv_to_discovery_rate", "median_speed_to_lead_min"):
        if rate_col in df.columns:
            df[rate_col] = pd.array([r.get(rate_col) for r in rows], dtype=object)
    return df.sort_values("dials", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# SALES tab Wave 1 rollups — SDR / BDS / SME with appt-booked + DQ
# ---------------------------------------------------------------------------

def sales_sdr_rollup(
    contacts: pd.DataFrame,
    calls: pd.DataFrame,
    meetings: pd.DataFrame,
    *,
    aircall_user_names: dict,
    excluded_users: set,
    aircall_to_sdr_owner: dict,
    connect_duration_sec: int,
    conv_window_hours: int,
    lead_window_start=None,
) -> pd.DataFrame:
    """Per-SDR activity for the SALES tab.

    Combines AirCall dial activity with HubSpot meeting booking attribution.

    Columns: user_id, user_name, dials, pick_ups, contacts_made,
             talk_time_min, appointments_booked, booking_rate,
             median_speed_to_lead_min.

    - pick_ups: outbound calls answered (any duration). They picked up the
      phone.
    - contacts_made: outbound calls answered AND duration >= connect threshold
      (filters voicemails and instant hang-ups — a real conversation).
    - talk_time_min: sum of duration on contacts_made calls only.
    - appointments_booked: count of distinct contacts with a 15-min meeting
      whose contact.sdr_owner = the SDR's HubSpot owner_id
      (mapped via aircall_to_sdr_owner).
    - booking_rate: appointments_booked / contacts_made (real conversations
      that converted to a booked appointment).
    """
    cols = ["user_id", "user_name", "dials", "pick_ups", "contacts_made",
            "talk_time_min", "appointments_booked", "booking_rate",
            "median_speed_to_lead_min"]

    activity = sdr_call_activity(
        contacts=contacts, calls=calls, meetings=meetings,
        aircall_user_names=aircall_user_names,
        excluded_users=excluded_users,
        connect_duration_sec=connect_duration_sec,
        conv_window_hours=conv_window_hours,
        lead_window_start=lead_window_start,
    )
    if activity.empty:
        return pd.DataFrame(columns=cols)

    # pick_ups (answered, any duration) — recompute directly from calls.
    pick_ups_by_user: dict[str, int] = {}
    if not calls.empty:
        outbound = calls[calls["direction"] == "outbound"].copy()
        if excluded_users:
            outbound = outbound[~outbound["user_id"].isin(excluded_users)]
        if not outbound.empty:
            mask = outbound["answered_at_utc"].notna()
            for uid, n in outbound.loc[mask].groupby("user_id").size().items():
                pick_ups_by_user[str(uid)] = int(n)

    # appointments_booked per SDR: distinct contacts with a 15-min meeting
    # where contact.sdr_owner maps to this SDR.
    sdr_appts: dict[str, int] = {}
    if not meetings.empty and not contacts.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        fifteen = meetings[types.str.contains("15 min", na=False)]
        if not fifteen.empty and "sdr_owner" in contacts.columns:
            owner_map = dict(zip(
                contacts["hs_id"].astype(str),
                contacts["sdr_owner"].fillna("").astype(str),
            ))
            booked_contact_ids = set(fifteen["contact_id"].astype(str))
            for cid in booked_contact_ids:
                owner = owner_map.get(cid, "")
                if owner:
                    sdr_appts[owner] = sdr_appts.get(owner, 0) + 1

    out = activity.rename(columns={"connects": "contacts_made"}).copy()
    out["pick_ups"] = out["user_id"].apply(
        lambda uid: pick_ups_by_user.get(str(uid), 0)
    )
    out["appointments_booked"] = out["user_id"].apply(
        lambda uid: int(sdr_appts.get(aircall_to_sdr_owner.get(str(uid), ""), 0))
    )
    out["booking_rate"] = [
        _safe_div(r["appointments_booked"], r["contacts_made"])
        for _, r in out.iterrows()
    ]
    return out[cols].reset_index(drop=True)


def _contacts_with_deal_in_stages(
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    stages: set,
) -> set:
    """Return the set of contact_ids with any deal in the given stages."""
    if deals.empty or contact_deals.empty or not stages:
        return set()
    deal_ids = set(deals.loc[deals["dealstage"].isin(stages), "deal_id"])
    return set(
        contact_deals.loc[contact_deals["deal_id"].isin(deal_ids), "contact_id"].astype(str)
    )


def sales_bds_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    stages_15min_dq: set,
) -> pd.DataFrame:
    """Per-BDS rollup with DQ tracking.

    BDS owns the 15-min Discovery: they hold it, qualify or disqualify the
    prospect, and book the Strategy when qualified.

    Columns: bds_id, appointments, shows, sme_booked, disqualified,
             show_rate, booking_rate, dq_rate.

    - appointments: contacts in this BDS group with a 15-min meeting (any outcome).
    - shows: 15-min meetings with COMPLETE outcome.
    - sme_booked: contacts who SHOWED the 15-min (COMPLETE) AND booked a
      Strategy meeting. Restricted to the showed set so booking_rate is a true
      post-show conversion and cannot exceed 100%.
    - disqualified: contacts who SHOWED the 15-min AND have a deal in
      STAGES_15MIN_DQ. Restricted to the showed set so dq_rate cannot exceed
      100%.
    - show_rate: shows / appointments.
    - booking_rate: sme_booked / shows.
    - dq_rate: disqualified / shows.
    """
    cols = ["bds_id", "appointments", "shows", "sme_booked", "disqualified",
            "show_rate", "booking_rate", "dq_rate"]
    if contacts.empty:
        return pd.DataFrame(columns=cols)

    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        fifteen = meetings[types.str.contains("15 min", na=False)]
        strategy = meetings[types.str.contains("strategy", na=False)]

        booked_15_ids = set(fifteen["contact_id"].astype(str)) \
            if not fifteen.empty else set()
        held_15_ids: set = set()
        if not fifteen.empty:
            out = fifteen["outcome"].fillna("").astype(str).str.upper()
            held_15_ids = set(
                fifteen.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str)
            )
        booked_strat_ids = set(strategy["contact_id"].astype(str)) \
            if not strategy.empty else set()
    else:
        booked_15_ids = set()
        held_15_ids = set()
        booked_strat_ids = set()

    dq_contact_ids = _contacts_with_deal_in_stages(
        contact_deals, deals, set(stages_15min_dq),
    )

    rows = []
    for bds_id, grp in contacts.groupby("bds", dropna=False):
        ids = set(grp["hs_id"].astype(str))
        appts = len(ids & booked_15_ids)
        shows = len(ids & held_15_ids)
        sme_booked = len(ids & held_15_ids & booked_strat_ids)
        dq = len(ids & held_15_ids & dq_contact_ids)
        rows.append({
            "bds_id": str(bds_id) if pd.notna(bds_id) else "",
            "appointments": appts,
            "shows": shows,
            "sme_booked": sme_booked,
            "disqualified": dq,
            "show_rate": _safe_div(shows, appts),
            "booking_rate": _safe_div(sme_booked, shows),
            "dq_rate": _safe_div(dq, shows),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        "appointments", ascending=False
    ).reset_index(drop=True)


def sales_sme_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict,
    group_default_amount: dict,
    stages_closed_won,
    stages_strategy_dq: set,
) -> pd.DataFrame:
    """Per-SME rollup with appointments + DQ + first/FU close split.

    SME owns the Strategy call: they hold it and close.

    Columns: sme_id, appointments, showed, deals_closed, first_closes,
             fu_closes, disqualified, show_rate, close_rate,
             first_close_rate, fu_close_rate, dq_rate, revenue.

    - appointments: contacts in this SME group with a Strategy meeting booked.
    - showed: Strategy meetings with COMPLETE outcome.
    - deals_closed: contacts with a deal in stages_closed_won.
    - first_closes: closed-won contacts with exactly 1 Strategy meeting at-or-
      before the deal closedate (closed on the first Strategy call).
    - fu_closes: closed-won contacts with 2+ Strategy meetings at-or-before
      the closedate (a closing/follow-up call happened after the first
      Strategy).
    - disqualified: contacts with a deal in stages_strategy_dq.
    - show_rate: showed / appointments.
    - close_rate: deals_closed / showed.
    - first_close_rate: first_closes / showed.
    - fu_close_rate: fu_closes / showed.
    - dq_rate: disqualified / showed.
    - revenue: sum of effective deal amounts (Option C — deal.amount with
      group_default_amount fallback).
    """
    cols = ["sme_id", "appointments", "showed", "deals_closed",
            "first_closes", "fu_closes", "disqualified",
            "show_rate", "close_rate", "first_close_rate", "fu_close_rate",
            "dq_rate", "revenue"]
    if contacts.empty:
        return pd.DataFrame(columns=cols)

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        strategy = meetings[types.str.contains("strategy", na=False)]
        booked_strat_ids = set(strategy["contact_id"].astype(str)) \
            if not strategy.empty else set()
        held_strat_ids: set = set()
        if not strategy.empty:
            out = strategy["outcome"].fillna("").astype(str).str.upper()
            held_strat_ids = set(
                strategy.loc[out.str.startswith("COMPLETE"), "contact_id"].astype(str)
            )
    else:
        booked_strat_ids = set()
        held_strat_ids = set()

    # Closed-won + revenue (Option C)
    won_set = set(stages_closed_won)
    won_contact_ids = _contacts_with_deal_in_stages(contact_deals, deals, won_set)
    contact_revenue: dict[str, float] = {}
    if not deals.empty and not contact_deals.empty and won_set:
        contact_to_group = dict(zip(
            contacts["hs_id"].astype(str), contacts["group"]
        ))

        def _deal_revenue(row) -> float:
            amt = float(row.get("amount") or 0)
            if amt > 0:
                return amt
            cids = contact_deals[
                contact_deals["deal_id"] == row["deal_id"]
            ]["contact_id"].astype(str)
            for cid in cids:
                g = contact_to_group.get(cid)
                if g and g in group_default_amount:
                    return float(group_default_amount[g])
            return 0.0

        won_deals = deals[deals["dealstage"].isin(won_set)].copy()
        won_deals["effective_amount"] = won_deals.apply(_deal_revenue, axis=1)
        deal_revenue_map = dict(zip(
            won_deals["deal_id"], won_deals["effective_amount"]
        ))
        for _, row in contact_deals.iterrows():
            cid = str(row["contact_id"])
            did = row["deal_id"]
            if did in deal_revenue_map:
                contact_revenue[cid] = contact_revenue.get(cid, 0.0) + deal_revenue_map[did]

    dq_contact_ids = _contacts_with_deal_in_stages(
        contact_deals, deals, set(stages_strategy_dq),
    )

    # First-Close vs FU-Close detection.
    # For each closed-won contact, count distinct Strategy meetings whose
    # start_time is at or before the deal's closedate. If 1 → First Close,
    # if 2+ → FU Close (a closing call happened after the first Strategy).
    first_close_contact_ids: set[str] = set()
    fu_close_contact_ids: set[str] = set()
    if won_contact_ids and not meetings.empty and not deals.empty \
            and not contact_deals.empty:
        # Build contact_id -> earliest won-deal close date.
        # createdate fallback covers DIY/90-Day stages without a closedate.
        won_set_local = set(won_set)
        won_deals_local = deals[deals["dealstage"].isin(won_set_local)].copy()
        won_deals_local["_close"] = pd.to_datetime(
            won_deals_local.get("closedate"), utc=True, errors="coerce"
        )
        if "createdate" in won_deals_local.columns:
            won_create = pd.to_datetime(
                won_deals_local["createdate"], utc=True, errors="coerce"
            )
            won_deals_local["_close"] = won_deals_local["_close"].fillna(won_create)
        won_deal_close = dict(zip(
            won_deals_local["deal_id"], won_deals_local["_close"]
        ))
        contact_close: dict[str, pd.Timestamp] = {}
        for _, cd_row in contact_deals.iterrows():
            cid = str(cd_row["contact_id"])
            did = cd_row["deal_id"]
            close_dt = won_deal_close.get(did)
            if close_dt is not None and pd.notna(close_dt):
                prior = contact_close.get(cid)
                if prior is None or close_dt < prior:
                    contact_close[cid] = close_dt

        types_local = meetings["activity_type"].fillna("").astype(str).str.lower()
        strategy_meets = meetings[types_local.str.contains("strategy", na=False)].copy()
        if not strategy_meets.empty:
            strategy_meets["_start"] = pd.to_datetime(
                strategy_meets["start_time"], utc=True, errors="coerce"
            )
            strategy_meets["_cid"] = strategy_meets["contact_id"].astype(str)
            for cid in won_contact_ids:
                close_dt = contact_close.get(cid)
                sub = strategy_meets[strategy_meets["_cid"] == cid]
                if close_dt is not None and pd.notna(close_dt):
                    sub = sub[sub["_start"].fillna(close_dt) <= close_dt]
                n = int(len(sub))
                if n == 1:
                    first_close_contact_ids.add(cid)
                elif n >= 2:
                    fu_close_contact_ids.add(cid)

    rows = []
    for sme_id, grp in contacts.groupby("sme", dropna=False):
        cids = set(grp["hs_id"].astype(str))
        appts = len(cids & booked_strat_ids)
        showed = len(cids & held_strat_ids)
        closed = len(cids & won_contact_ids)
        first_c = len(cids & first_close_contact_ids)
        fu_c = len(cids & fu_close_contact_ids)
        dq = len(cids & dq_contact_ids)
        rev = sum(contact_revenue.get(c, 0.0) for c in cids)
        rows.append({
            "sme_id": str(sme_id) if pd.notna(sme_id) else "",
            "appointments": appts,
            "showed": showed,
            "deals_closed": closed,
            "first_closes": first_c,
            "fu_closes": fu_c,
            "disqualified": dq,
            "show_rate": _safe_div(showed, appts),
            "close_rate": _safe_div(closed, showed),
            "first_close_rate": _safe_div(first_c, showed),
            "fu_close_rate": _safe_div(fu_c, showed),
            "dq_rate": _safe_div(dq, showed),
            "revenue": rev,
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        "revenue", ascending=False
    ).reset_index(drop=True)


def asset_performance_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict,
    group_default_amount: dict,
    stages_closed_won,
    closed_deals_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per marketing-asset performance summary.

    One row per asset (blank assets excluded). Columns: asset, group, leads,
    fifteen_booked, strategy_booked, closed, revenue, close_rate.

    - leads + fifteen_booked + strategy_booked come from `contacts` (the opt-in
      lead cohort) and `meetings`.
    - closed + revenue are attributed to the asset that ORIGINATED each
      closed-won deal:
        * if `closed_deals_table` (a build_closed_deals_table output) is given,
          closes/revenue are grouped from its `asset` + `deal_amount` columns —
          regardless of when the lead opted in. Closes lag opt-ins, so the lead
          cohort and the closer cohort barely overlap; attributing by the
          closer's asset is what makes (YTD) revenue meaningful.
        * else they fall back to the lead cohort's own won deals (Option-C:
          deal.amount, group_default fallback) — original behavior.
    - Rows are the UNION of lead-bearing and close-bearing assets.
    - close_rate = closed / leads (None when leads == 0).
    Sorted by revenue, then closed, then leads (descending).
    """
    cols = ["asset", "group", "leads", "fifteen_booked", "strategy_booked",
            "closed", "revenue", "close_rate"]

    # ---- Leads + funnel per asset (opt-in cohort) ----
    leads_by_asset: dict[str, int] = {}
    f15_by_asset: dict[str, int] = {}
    strat_by_asset: dict[str, int] = {}
    group_by_asset: dict[str, str] = {}
    if not contacts.empty:
        c = contacts.copy()
        c["asset"] = c["typeform_asset_download"].fillna("").astype(str).str.strip()
        c = c[c["asset"] != ""]
        if not c.empty:
            if not meetings.empty:
                types = meetings["activity_type"].fillna("").astype(str).str.lower()
                booked_15 = set(meetings.loc[types.str.contains("15 min", na=False),
                                             "contact_id"].astype(str))
                booked_strat = set(meetings.loc[types.str.contains("strategy", na=False),
                                                "contact_id"].astype(str))
            else:
                booked_15, booked_strat = set(), set()
            for asset, grp in c.groupby("asset"):
                ids = set(grp["hs_id"].astype(str))
                leads_by_asset[asset] = len(ids)
                f15_by_asset[asset] = len(ids & booked_15)
                strat_by_asset[asset] = len(ids & booked_strat)
                group_by_asset[asset] = asset_to_group.get(asset, "")

    # ---- Closed + revenue per asset ----
    closed_by_asset: dict[str, int] = {}
    rev_by_asset: dict[str, float] = {}
    if closed_deals_table is not None and not closed_deals_table.empty:
        # Attribute each closed-won deal to its originating asset. Restrict to
        # marketing-attributed closers so sales/referral/unattributed source
        # labels don't show up as "assets".
        cdt = closed_deals_table.copy()
        if "is_marketing" in cdt.columns:
            cdt = cdt[cdt["is_marketing"] == True]
        cdt["_asset"] = cdt["asset"].fillna("").astype(str).str.strip()
        cdt = cdt[cdt["_asset"] != ""]
        if not cdt.empty:
            cdt["_amt"] = pd.to_numeric(cdt["deal_amount"], errors="coerce").fillna(0.0)
            for asset, g in cdt.groupby("_asset"):
                closed_by_asset[asset] = int(len(g))
                rev_by_asset[asset] = float(g["_amt"].sum())
                if asset not in group_by_asset:
                    group_by_asset[asset] = (str(g["group"].iloc[0])
                                             if "group" in g.columns
                                             else asset_to_group.get(asset, ""))
    else:
        # Fallback: lead-cohort won deals (original behavior).
        won_set = set(stages_closed_won)
        won_contact_ids = _contacts_with_deal_in_stages(contact_deals, deals, won_set)
        contact_revenue: dict[str, float] = {}
        if not deals.empty and not contact_deals.empty and won_set and leads_by_asset:
            c2 = contacts.copy()
            c2["asset"] = c2["typeform_asset_download"].fillna("").astype(str).str.strip()
            c_group = dict(zip(c2["hs_id"].astype(str), c2["asset"].map(asset_to_group)))
            won_deals = deals[deals["dealstage"].isin(won_set)].copy()

            def _rev(row) -> float:
                amt = float(row.get("amount") or 0)
                if amt > 0:
                    return amt
                cids = contact_deals[
                    contact_deals["deal_id"] == row["deal_id"]
                ]["contact_id"].astype(str)
                for cid in cids:
                    g = c_group.get(cid)
                    if g and g in group_default_amount:
                        return float(group_default_amount[g])
                return 0.0

            won_deals["_rev"] = won_deals.apply(_rev, axis=1)
            rev_map = dict(zip(won_deals["deal_id"], won_deals["_rev"]))
            for _, row in contact_deals.iterrows():
                did = row["deal_id"]
                cid = str(row["contact_id"])
                if did in rev_map:
                    contact_revenue[cid] = contact_revenue.get(cid, 0.0) + rev_map[did]
            # roll cohort closes/revenue up to each lead asset
            c3 = contacts.copy()
            c3["asset"] = c3["typeform_asset_download"].fillna("").astype(str).str.strip()
            for asset, grp in c3[c3["asset"] != ""].groupby("asset"):
                ids = set(grp["hs_id"].astype(str))
                closed_by_asset[asset] = len(ids & won_contact_ids)
                rev_by_asset[asset] = sum(contact_revenue.get(i, 0.0) for i in ids)

    all_assets = set(leads_by_asset) | set(closed_by_asset)
    if not all_assets:
        return pd.DataFrame(columns=cols)
    rows = []
    for asset in all_assets:
        leads = leads_by_asset.get(asset, 0)
        closed = closed_by_asset.get(asset, 0)
        rows.append({
            "asset": asset,
            "group": group_by_asset.get(asset, asset_to_group.get(asset, "")),
            "leads": leads,
            "fifteen_booked": f15_by_asset.get(asset, 0),
            "strategy_booked": strat_by_asset.get(asset, 0),
            "closed": closed,
            "revenue": rev_by_asset.get(asset, 0.0),
            "close_rate": _safe_div(closed, leads),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        ["revenue", "closed", "leads"], ascending=False
    ).reset_index(drop=True)


def team_total_row(df, *, sum_cols, rate_cols, label_col, label="TEAM TOTAL"):
    """Prepend a team-total row to a per-rep rollup.

    - sum_cols: columns summed across rows.
    - rate_cols: {col: (numerator_col, denominator_col)} recomputed from the
      SUMMED totals (not averaged), so a team rate is true aggregate.
    - label_col: column that holds `label`; every other non-sum/non-rate column
      is left blank ("") in the total row.
    Returns a new df with the total row at index 0 and the original rows after.
    """
    if df.empty:
        return df
    total = {c: "" for c in df.columns}
    total[label_col] = label
    for c in sum_cols:
        total[c] = df[c].sum()
    for c, (num, den) in rate_cols.items():
        d = df[den].sum()
        total[c] = (df[num].sum() / d) if d else None
    return pd.concat([pd.DataFrame([total]), df], ignore_index=True)


def windowed_sales_money(
    deals: pd.DataFrame,
    contact_deals: pd.DataFrame,
    contacts: pd.DataFrame,
    *,
    start: 'date',
    end: 'date',
    asset_to_group: dict,
    group_default_amount: dict,
    stages_closed_won,
    stages_closed_won_no_closedate,
    source_overrides: dict | None = None,
    stage_source_fallback: dict | None = None,
    group_cash_per_deal: dict | None = None,
) -> dict:
    """Window-bounded money + cash + time-to-close.

    Filters YTD-loaded closed deals to those CLOSED within [start, end].
    Stages without closedate (DIY, 90-Day) fall back to createdate.

    Returns dict with: window_closed_count, window_revenue,
    window_avg_deal_size, window_cycle_median_days, window_cash_collection.

    - window_revenue: sum of effective deal amounts (HubSpot amount with
      group-default fallback).
    - window_cash_collection: sum of group_cash_per_deal[group] across closed
      deals in the window. Differs from revenue when contract values exceed
      cash-up-front. None when group_cash_per_deal is not provided.
    """
    if deals.empty:
        return {
            "window_closed_count": 0,
            "window_revenue": 0.0,
            "window_avg_deal_size": None,
            "window_cycle_median_days": None,
            "window_cash_collection": 0.0 if group_cash_per_deal else None,
        }

    # Effective close date:
    #   - closedate when present (normal closed-won stages)
    #   - else stage_entry_date for DIY / 90-Day (when the deal entered the
    #     no-closedate stage = the day it actually became a customer)
    #   - else createdate (defensive fallback for legacy rows lacking both)
    no_close_set = set(stages_closed_won_no_closedate)
    close_dt = pd.to_datetime(deals.get("closedate"), utc=True, errors="coerce").dt.date
    stage_entry_dt = pd.to_datetime(
        deals.get("stage_entry_date"), utc=True, errors="coerce"
    ).dt.date if "stage_entry_date" in deals.columns else pd.Series(
        [None] * len(deals), index=deals.index, dtype=object,
    )
    create_dt = pd.to_datetime(deals.get("createdate"), utc=True, errors="coerce").dt.date
    mask_close = close_dt.between(start, end)
    no_close_mask = deals["dealstage"].isin(no_close_set) & close_dt.isna()
    mask_stage_entry = no_close_mask & stage_entry_dt.between(start, end)
    mask_create = no_close_mask & stage_entry_dt.isna() & create_dt.between(start, end)
    window_deals = deals[mask_close | mask_stage_entry | mask_create].copy()

    table = build_closed_deals_table(
        window_deals, contact_deals, contacts,
        asset_to_group=asset_to_group,
        group_default_amount=group_default_amount,
        source_overrides=source_overrides,
        stage_source_fallback=stage_source_fallback,
    )
    n = int(len(table))
    revenue = float(table["deal_amount"].sum()) if n else 0.0
    avg = (revenue / n) if n else None
    cycle_vals = table["sales_cycle_days"].dropna().tolist() if n else []
    cycle_median = float(pd.Series(cycle_vals).median()) if cycle_vals else None

    if group_cash_per_deal:
        cash = float(
            table["group"].map(lambda g: group_cash_per_deal.get(g, 0.0)).sum()
        ) if n else 0.0
    else:
        cash = None

    return {
        "window_closed_count": n,
        "window_revenue": revenue,
        "window_avg_deal_size": avg,
        "window_cycle_median_days": cycle_median,
        "window_cash_collection": cash,
    }


# ---------------------------------------------------------------------------
# Daily VA Summary (Chiro + TheraRay snapshot for morning chat post)
# ---------------------------------------------------------------------------

def daily_va_summary(
    *,
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    theraray_memberships: pd.DataFrame,
    nlap_memberships: pd.DataFrame,
    start: 'date',
    end: 'date',
    asset_to_group: dict,
) -> dict:
    """Numbers for the morning summary the VA posts in chat.

    Mirrors the format:
        Chiro
        Spend, All Leads, Cost / All Leads, New Leads, Cost / New Lead

        TheraRay
        Submissions, Ad Spend

    All Leads  = contacts with typeform_submission_date in [start, end]
                 (regardless of when the contact was created).
    New Leads  = subset whose contact createdate is also in [start, end] —
                 i.e., they didn't exist in HubSpot before this window.
                 Returning leads (createdate before window) are All Leads
                 but NOT New Leads.

    Chiro rolls up Chiro + EMX groups to match METRICS-tab convention.

    Returns a dict with all values; caller formats for display.
    """
    # --- Chiro: tag contacts with group and apply window filters ---
    cx = contacts.copy()
    if not cx.empty:
        cx["group"] = cx["typeform_asset_download"].map(asset_to_group)
        submit_dt = pd.to_datetime(
            cx.get("typeform_submission_date"), utc=True, errors="coerce"
        ).dt.date
        create_dt = pd.to_datetime(
            cx.get("created"), utc=True, errors="coerce"
        ).dt.date
        in_submit_window = submit_dt.between(start, end)
        in_create_window = create_dt.between(start, end)
        chiro_mask = cx["group"].isin(["Chiro", "EMX"])
        chiro_all_leads = int((chiro_mask & in_submit_window).sum())
        chiro_new_leads = int(
            (chiro_mask & in_submit_window & in_create_window).sum()
        )
    else:
        chiro_all_leads = 0
        chiro_new_leads = 0

    # --- FB spend by group within window ---
    if not fb.empty and "date_start" in fb.columns:
        fb_start = pd.to_datetime(
            fb["date_start"], utc=True, errors="coerce"
        ).dt.date
        in_window = fb_start.between(start, end)
        chiro_spend = float(
            fb.loc[in_window & fb["group"].isin(["Chiro", "EMX"]), "spend"].sum()
        )
        theraray_spend = float(
            fb.loc[in_window & (fb["group"] == "TheraRay"), "spend"].sum()
        )
        nlap_spend = float(
            fb.loc[in_window & (fb["group"] == "NLAP"), "spend"].sum()
        )
    else:
        chiro_spend = 0.0
        theraray_spend = 0.0
        nlap_spend = 0.0

    # --- TheraRay submissions: list memberships in window ---
    if not theraray_memberships.empty \
            and "membership_timestamp" in theraray_memberships.columns:
        ts_dt = pd.to_datetime(
            theraray_memberships["membership_timestamp"], utc=True, errors="coerce"
        ).dt.date
        theraray_submissions = int(ts_dt.between(start, end).sum())
    else:
        theraray_submissions = 0

    # --- NLAP submissions: list memberships in window ---
    if not nlap_memberships.empty \
            and "membership_timestamp" in nlap_memberships.columns:
        nlap_ts = pd.to_datetime(
            nlap_memberships["membership_timestamp"], utc=True, errors="coerce"
        ).dt.date
        nlap_submissions = int(nlap_ts.between(start, end).sum())
    else:
        nlap_submissions = 0

    return {
        "chiro_spend": chiro_spend,
        "chiro_all_leads": chiro_all_leads,
        "chiro_cpl_all": (chiro_spend / chiro_all_leads) if chiro_all_leads else None,
        "chiro_new_leads": chiro_new_leads,
        "chiro_cpl_new": (chiro_spend / chiro_new_leads) if chiro_new_leads else None,
        "theraray_submissions": theraray_submissions,
        "theraray_ad_spend": theraray_spend,
        "theraray_cpl": (theraray_spend / theraray_submissions) if theraray_submissions else None,
        "nlap_submissions": nlap_submissions,
        "nlap_ad_spend": nlap_spend,
        "nlap_cpl": (nlap_spend / nlap_submissions) if nlap_submissions else None,
    }


# ---------------------------------------------------------------------------
# Weekly Metrics aggregator
# ---------------------------------------------------------------------------
from datetime import date, datetime, timedelta, timezone  # noqa: E402


# Metric label registry — keep aligned with config.METRICS_GOALS keys.
_METRIC_LABELS: dict[str, str] = {
    "chiro_ad_spend": "Chiro — Ad Spend (incl. EMX)",
    "chiro_link_clicks": "Chiro — Link Clicks (incl. EMX)",
    "chiro_cpc": "Chiro — Cost-Per-Click (incl. EMX)",
    "chiro_lead_magnet_optins": "Chiro — Lead Magnet Opt-Ins (incl. EMX)",
    "chiro_new_leads": "Chiro — New Leads (incl. EMX)",
    "pt_ad_spend": "PT — Ad Spend",
    "pt_link_clicks": "PT — Link Clicks",
    "pt_cpc": "PT — Cost-Per-Click",
    "pt_lead_magnet_optins": "PT — Lead Magnet Opt-Ins",
    "pt_new_leads": "PT — New Leads",
    "theraray_ad_spend": "TheraRay — Ad Spend",
    "theraray_leads": "TheraRay — Leads (FB)",
    "theraray_15min_scheduled": "TheraRay — 15 Min Call Scheduled",
    "emx_ad_spend": "EMX — Ad Spend",
    "emx_leads": "EMX — Leads",
    "webinar_registrations": "Webinar Registrations",
    "webinar_completions": "Webinar Completions",
    "pt_webinar_registrations": "PT Webinar Registrations",
    "pt_webinar_completions": "PT Webinar Completions",
    "bofu_submissions_total": "BOFU Submissions (Total)",
    "fifteen_min_scheduled": "15 Min Calls Scheduled",
    "fifteen_min_completed": "15 Min Calls Completed",
    "pt_fifteen_min_scheduled": "PT 15 Min Calls Scheduled",
    "pt_fifteen_min_completed": "PT 15 Min Calls Completed",
    "strategy_calls_total": "Strategy Calls — Total",
    "strategy_calls_completed": "Strategy Calls — Completed",
    "new_total_customers": "NEW Total Customers",
}


def _date_in_window(dt_str, start: date, end: date) -> bool:
    """True if dt_str parses to a date in [start, end] inclusive."""
    if not dt_str:
        return False
    try:
        d = pd.to_datetime(dt_str, utc=True, errors="coerce")
        if pd.isna(d):
            return False
        return start <= d.date() <= end
    except Exception:
        return False


def _ts_ms_in_window(ts_ms, start: date, end: date) -> bool:
    """True if Unix-ms timestamp falls in [start, end] inclusive."""
    if ts_ms is None or pd.isna(ts_ms):
        return False
    try:
        d = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).date()
        return start <= d <= end
    except Exception:
        return False


def weekly_metrics(
    *,
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    bofu_submissions: pd.DataFrame,
    week_ranges: list[tuple[date, date]],
    asset_to_group: dict[str, str],
    stages_closed_won: set[str],
    new_customer_stages: set[str] | None = None,
    goals: dict[str, float],
) -> pd.DataFrame:
    """Compute weekly metric counts.

    Returns a DataFrame with columns:
        metric_id, metric_label, goal, sum, w0, w1, ..., w{N-1}
    where N = len(week_ranges) and w0 = oldest, w{N-1} = newest.
    """
    n = len(week_ranges)
    week_cols = [f"w{i}" for i in range(n)]

    # Tag contacts with group via asset map
    contacts = contacts.copy()
    if not contacts.empty:
        contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)
    else:
        contacts["group"] = pd.Series(dtype=object)

    # Pre-compute per-row date helpers used below
    # Note: wrap in list() to force Python date objects (avoids NaT comparison issues
    # when pandas keeps the series as DatetimeArray dtype).
    def _to_date_series(col_name: str) -> pd.Series:
        parsed = pd.to_datetime(contacts.get(col_name), utc=True, errors="coerce")
        return pd.Series(
            [d.date() if not pd.isna(d) else None for d in parsed],
            index=contacts.index,
            dtype=object,
        )

    if not contacts.empty:
        contacts["_submit_date"] = _to_date_series("typeform_submission_date")
        contacts["_webinar_reg"] = _to_date_series("webinar_registration_date")
        contacts["_webinar_done"] = _to_date_series("webinar_completed_date")
        contacts["_pt_webinar_reg"] = _to_date_series("pt_webinar_registration_date")
        contacts["_pt_webinar_done"] = _to_date_series("pt_webinar_completed_date")

    if not meetings.empty:
        m_types = meetings["activity_type"].fillna("").astype(str).str.lower()
        m_outcomes = meetings["outcome"].fillna("").astype(str).str.upper()
        m_start = pd.to_datetime(meetings["start_time"], utc=True, errors="coerce").dt.date
    else:
        m_types = pd.Series(dtype=str)
        m_outcomes = pd.Series(dtype=str)
        m_start = pd.Series(dtype=object)

    if not deals.empty:
        d_won = deals["dealstage"].isin(stages_closed_won)
        d_close = pd.to_datetime(deals["closedate"], utc=True, errors="coerce").dt.date
    else:
        d_won = pd.Series(dtype=bool)
        d_close = pd.Series(dtype=object)

    if not fb.empty:
        fb_start = pd.to_datetime(fb.get("date_start"), utc=True, errors="coerce").dt.date
    else:
        fb_start = pd.Series(dtype=object)

    def _fb_sum(group: str, col: str, start: date, end: date) -> float:
        if fb.empty:
            return 0.0
        mask = (fb["group"] == group) & fb_start.between(start, end)
        return float(fb.loc[mask, col].sum()) if mask.any() else 0.0

    def _fb_clicks(group: str, start: date, end: date) -> int:
        """Link clicks (FB's inline_link_clicks). Falls back to 'clicks' if the
        column is not present (e.g., older test fixtures)."""
        col = "inline_link_clicks" if "inline_link_clicks" in fb.columns else "clicks"
        return int(_fb_sum(group, col, start, end))

    def _fb_leads(group: str, start: date, end: date) -> int:
        return int(_fb_sum(group, "fb_leads", start, end))

    def _contacts_in_group_with_submit(group: str, start: date, end: date) -> int:
        if contacts.empty:
            return 0
        in_window = contacts["_submit_date"].apply(
            lambda d: d is not None and isinstance(d, date) and start <= d <= end
        )
        mask = (contacts["group"] == group) & in_window
        return int(mask.sum())

    def _contacts_property_in_window(prop_col: str, start: date, end: date) -> int:
        if contacts.empty or prop_col not in contacts.columns:
            return 0
        col = contacts[prop_col]
        # Column is object dtype with Python date or None; apply handles None safely
        mask = col.apply(
            lambda d: d is not None and isinstance(d, date) and start <= d <= end
        )
        return int(mask.sum())

    def _meetings_count(token: str, start: date, end: date, *,
                       completed_only: bool = False) -> int:
        if meetings.empty:
            return 0
        mask = m_types.str.contains(token, na=False) & m_start.between(start, end)
        if completed_only:
            mask = mask & m_outcomes.str.startswith("COMPLETE")
        return int(mask.sum())

    def _meetings_count_group(token: str, group: str, start: date, end: date,
                              *, completed_only: bool = False) -> int:
        """15-min meetings for contacts whose typeform asset maps to a group."""
        if meetings.empty or contacts.empty:
            return 0
        group_contact_ids = set(
            contacts.loc[contacts["group"] == group, "hs_id"].astype(str)
        )
        if not group_contact_ids:
            return 0
        mask = (
            m_types.str.contains(token, na=False)
            & m_start.between(start, end)
            & meetings["contact_id"].astype(str).isin(group_contact_ids)
        )
        if completed_only:
            mask = mask & m_outcomes.str.startswith("COMPLETE")
        return int(mask.sum())

    def _deals_won_in_week(start: date, end: date,
                           stages_override: set[str] | None = None) -> int:
        if deals.empty:
            return 0
        use_stages = stages_override if stages_override is not None else stages_closed_won
        # Closedate-based deals (standard closed-won)
        mask = deals["dealstage"].isin(use_stages) & d_close.between(start, end)
        # No-closedate deals (DIY, 90-Day): prefer stage-entry date (when the
        # deal entered the stage), fall back to createdate.
        if "stage_entry_date" in deals.columns:
            try:
                d_entry = pd.to_datetime(deals["stage_entry_date"], utc=True,
                                          errors="coerce").dt.date
                mask_entry = (
                    deals["dealstage"].isin(use_stages)
                    & d_entry.between(start, end)
                    & d_close.isna()
                )
                mask = mask | mask_entry
            except Exception:
                pass
        if "createdate" in deals.columns:
            try:
                d_create = pd.to_datetime(deals["createdate"], utc=True,
                                          errors="coerce").dt.date
                if "stage_entry_date" in deals.columns:
                    d_entry_local = pd.to_datetime(deals["stage_entry_date"],
                                                    utc=True, errors="coerce").dt.date
                else:
                    d_entry_local = pd.Series([None] * len(deals), index=deals.index)
                mask_create = (
                    deals["dealstage"].isin(use_stages)
                    & d_create.between(start, end)
                    & d_close.isna()
                    & d_entry_local.isna()
                )
                mask = mask | mask_create
            except Exception:
                pass
        return int(mask.sum())

    def _bofu_in_week(start: date, end: date) -> int:
        if bofu_submissions.empty:
            return 0
        mask = bofu_submissions["submitted_at"].apply(
            lambda x: _ts_ms_in_window(x, start, end)
        )
        return int(mask.sum())

    # Build per-week values per metric
    metric_ids = list(_METRIC_LABELS.keys())
    rows = []
    for metric_id in metric_ids:
        weekly_values = []
        for (ws, we) in week_ranges:
            if metric_id == "chiro_ad_spend":
                weekly_values.append(
                    _fb_sum("Chiro", "spend", ws, we)
                    + _fb_sum("EMX", "spend", ws, we)
                )
            elif metric_id == "chiro_link_clicks":
                weekly_values.append(
                    _fb_clicks("Chiro", ws, we)
                    + _fb_clicks("EMX", ws, we)
                )
            elif metric_id == "chiro_cpc":
                spend = (_fb_sum("Chiro", "spend", ws, we)
                         + _fb_sum("EMX", "spend", ws, we))
                clicks = (_fb_clicks("Chiro", ws, we)
                          + _fb_clicks("EMX", ws, we))
                weekly_values.append(spend / clicks if clicks else 0.0)
            elif metric_id == "chiro_lead_magnet_optins":
                weekly_values.append(
                    _fb_leads("Chiro", ws, we)
                    + _fb_leads("EMX", ws, we)
                )
            elif metric_id == "chiro_new_leads":
                weekly_values.append(
                    _contacts_in_group_with_submit("Chiro", ws, we)
                    + _contacts_in_group_with_submit("EMX", ws, we)
                )
            elif metric_id == "pt_ad_spend":
                weekly_values.append(_fb_sum("PT Recovery", "spend", ws, we))
            elif metric_id == "pt_link_clicks":
                weekly_values.append(_fb_clicks("PT Recovery", ws, we))
            elif metric_id == "pt_cpc":
                spend = _fb_sum("PT Recovery", "spend", ws, we)
                clicks = _fb_clicks("PT Recovery", ws, we)
                weekly_values.append(spend / clicks if clicks else 0.0)
            elif metric_id == "pt_lead_magnet_optins":
                weekly_values.append(_fb_leads("PT Recovery", ws, we))
            elif metric_id == "pt_new_leads":
                weekly_values.append(_contacts_in_group_with_submit("PT Recovery", ws, we))
            elif metric_id == "theraray_ad_spend":
                weekly_values.append(_fb_sum("TheraRay", "spend", ws, we))
            elif metric_id == "theraray_leads":
                weekly_values.append(_fb_leads("TheraRay", ws, we))
            elif metric_id == "theraray_15min_scheduled":
                weekly_values.append(_meetings_count_group("15 min", "TheraRay", ws, we))
            elif metric_id == "emx_ad_spend":
                weekly_values.append(_fb_sum("EMX", "spend", ws, we))
            elif metric_id == "emx_leads":
                weekly_values.append(_contacts_in_group_with_submit("EMX", ws, we))
            elif metric_id == "webinar_registrations":
                weekly_values.append(_contacts_property_in_window("_webinar_reg", ws, we))
            elif metric_id == "webinar_completions":
                weekly_values.append(_contacts_property_in_window("_webinar_done", ws, we))
            elif metric_id == "pt_webinar_registrations":
                weekly_values.append(_contacts_property_in_window("_pt_webinar_reg", ws, we))
            elif metric_id == "pt_webinar_completions":
                weekly_values.append(_contacts_property_in_window("_pt_webinar_done", ws, we))
            elif metric_id == "bofu_submissions_total":
                weekly_values.append(_bofu_in_week(ws, we))
            elif metric_id == "fifteen_min_scheduled":
                weekly_values.append(_meetings_count("15 min", ws, we))
            elif metric_id == "fifteen_min_completed":
                weekly_values.append(_meetings_count("15 min", ws, we, completed_only=True))
            elif metric_id == "pt_fifteen_min_scheduled":
                weekly_values.append(_meetings_count("pt 15 min", ws, we))
            elif metric_id == "pt_fifteen_min_completed":
                weekly_values.append(_meetings_count("pt 15 min", ws, we, completed_only=True))
            elif metric_id == "strategy_calls_total":
                weekly_values.append(_meetings_count("strategy", ws, we))
            elif metric_id == "strategy_calls_completed":
                weekly_values.append(_meetings_count("strategy", ws, we, completed_only=True))
            elif metric_id == "new_total_customers":
                stages = new_customer_stages if new_customer_stages else stages_closed_won
                weekly_values.append(_deals_won_in_week(ws, we, stages_override=stages))
            else:
                weekly_values.append(0)

        row = {
            "metric_id": metric_id,
            "metric_label": _METRIC_LABELS[metric_id],
            "goal": goals.get(metric_id, 0),
            "sum": sum(weekly_values),
        }
        for i, v in enumerate(weekly_values):
            row[week_cols[i]] = v
        rows.append(row)

    return pd.DataFrame(rows, columns=["metric_id", "metric_label", "goal", "sum"] + week_cols)


# ---------------------------------------------------------------------------
# Closed-deal detail table helpers
# ---------------------------------------------------------------------------

def build_closed_deals_table(
    deals: pd.DataFrame,
    contact_deals: pd.DataFrame,
    contacts: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    group_default_amount: dict[str, float],
    source_overrides: dict | None = None,
    stage_source_fallback: dict | None = None,
) -> pd.DataFrame:
    """Build a row-per-deal detail table for closed-won deals.

    Each row: hs_id (for link), contact_name, email, group, asset, source,
    is_marketing, closedate, deal_amount (Option C fallback),
    sales_cycle_days (typeform_submission to closedate), sdr_owner, bds, sme.
    """
    cols = ["hs_id", "contact_name", "email", "typeform", "group", "asset", "source",
            "tier", "send_contract", "is_marketing", "closedate", "deal_amount",
            "sales_cycle_days", "sdr_owner", "bds", "sme"]
    if deals.empty or contact_deals.empty or contacts.empty:
        return pd.DataFrame(columns=cols)

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)
    contacts_by_id = {str(r["hs_id"]): r for _, r in contacts.iterrows()}

    rows = []
    for _, deal in deals.iterrows():
        deal_id = deal["deal_id"]
        amt = float(deal.get("amount") or 0)
        cd_rows = contact_deals[contact_deals["deal_id"] == deal_id]
        contact_ids = [str(c) for c in cd_rows["contact_id"].tolist()]
        primary_contact = None
        for cid in contact_ids:
            if cid in contacts_by_id:
                primary_contact = contacts_by_id[cid]
                break

        if primary_contact is None:
            continue  # deal has no matched contact; skip

        # Determine source attribution
        email = (primary_contact.get("email") or "").strip().lower()
        asset = primary_contact.get("typeform_asset_download") or ""
        override = source_overrides.get(email) if source_overrides else None

        if asset and asset_to_group.get(asset):
            # Typeform-attributed: marketing
            source = asset
            group = asset_to_group.get(asset)
            is_marketing = True
        elif override:
            # Email-based override
            source, group, is_marketing = override
        elif stage_source_fallback and str(deal.get("dealstage")) in stage_source_fallback:
            # Stage-based fallback (e.g., DIY, 90-Day)
            source, group, is_marketing = stage_source_fallback[str(deal.get("dealstage"))]
        else:
            # Unknown source
            source = "(unattributed)"
            group = primary_contact.get("group")
            is_marketing = False

        # Option C: deal.amount if > 0, else group default
        effective_amt = amt if amt > 0 else float(group_default_amount.get(group, 0.0))

        # Sales cycle: prefer typeform_submission_date as lead-start; fall back
        # to HubSpot createdate when submission is missing OR appears to be
        # after the close (data anomaly — typeform_submission_date was bulk-
        # updated in some cases, corrupting older closes). Returns None when no
        # valid lead-start is available; None values are excluded from the
        # median rather than being clamped to 0.
        cycle_days = None
        try:
            submit_ts = pd.to_datetime(primary_contact.get("typeform_submission_date"),
                                        utc=True, errors="coerce")
            created_ts = pd.to_datetime(primary_contact.get("created"),
                                         utc=True, errors="coerce")
            close_ts = pd.to_datetime(deal.get("closedate"),
                                       utc=True, errors="coerce")
            # Fallback: use stage-entry date when deal has no closedate
            # (DIY / 90-Day stages). Final fallback = createdate.
            if pd.isna(close_ts):
                close_ts = pd.to_datetime(deal.get("stage_entry_date"),
                                           utc=True, errors="coerce")
            if pd.isna(close_ts):
                close_ts = pd.to_datetime(deal.get("createdate"),
                                           utc=True, errors="coerce")
            if pd.notna(close_ts):
                lead_start_ts = None
                # Prefer submission_date when it's a valid (pre-close) timestamp
                if pd.notna(submit_ts) and submit_ts <= close_ts:
                    lead_start_ts = submit_ts
                # Else fall back to createdate when it's valid
                elif pd.notna(created_ts) and created_ts <= close_ts:
                    lead_start_ts = created_ts
                if lead_start_ts is not None:
                    cycle_days = int((close_ts - lead_start_ts).days)
        except Exception:
            pass

        # TheraRay detection: contacts whose inbound source is theraray.org
        # are TheraRay leads regardless of their contract tier suffix. Without
        # this, a TheraRay lead who buys a "90-DAY - C" contract would tag as
        # Chiro via tier-suffix derivation.
        analytics_src = (primary_contact.get("analytics_source_data_1") or "").lower()
        is_theraray_signal = "theraray" in analytics_src
        if is_theraray_signal and not (asset and asset_to_group.get(asset)):
            # No explicit typeform attribution + TheraRay analytics signal
            # → mark as TheraRay marketing close.
            source = "TheraRay (direct traffic)"
            group = "TheraRay"
            is_marketing = True

        # Group derivation priority:
        #  1. Explicit asset/override group (set above)
        #  2. TheraRay analytics signal (now folded into group above)
        #  3. Tier-suffix → derived group (fallback for non-marketing closes)
        #  4. "(unmapped)"
        tier_val = primary_contact.get("contract_tier") or ""
        group_from_tier = _group_from_tier(tier_val)
        if group:  # asset map, override, or TheraRay signal above
            final_group = group
        elif group_from_tier:
            final_group = group_from_tier
        else:
            final_group = "(unmapped)"

        rows.append({
            "hs_id": str(primary_contact.get("hs_id")),
            "contact_name": primary_contact.get("name") or "",
            "email": primary_contact.get("email") or "",
            "typeform": primary_contact.get("typeform_asset_download") or "",
            "group": final_group,
            "asset": asset or source,  # show source label when no typeform
            "source": source,
            "tier": tier_val,
            "send_contract": primary_contact.get("send_contract_options") or "",
            "is_marketing": bool(is_marketing),
            "closedate": (deal.get("closedate")
                          or deal.get("stage_entry_date")
                          or deal.get("createdate")),
            "deal_amount": effective_amt,
            "sales_cycle_days": cycle_days,
            "sdr_owner": primary_contact.get("sdr_owner") or "",
            "bds": primary_contact.get("bds") or "",
            "sme": primary_contact.get("sme") or "",
        })

    df = pd.DataFrame(rows, columns=cols)
    # Sort newest close first
    df["_sort_ts"] = pd.to_datetime(df["closedate"], utc=True, errors="coerce")
    df = df.sort_values("_sort_ts", ascending=False, na_position="last")
    df = df.drop(columns=["_sort_ts"])
    return df


def compute_ytd_money(
    deals: pd.DataFrame,
    contact_deals: pd.DataFrame,
    contacts: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    group_default_amount: dict[str, float],
    source_overrides: dict | None = None,
    stage_source_fallback: dict | None = None,
) -> dict:
    """Compute YTD money KPIs in TWO views: Total (all closed) + Marketing-only.

    Returns a dict with prefix keys: total_* and mkt_*.
    """
    table = build_closed_deals_table(
        deals, contact_deals, contacts,
        asset_to_group=asset_to_group,
        group_default_amount=group_default_amount,
        source_overrides=source_overrides,
        stage_source_fallback=stage_source_fallback,
    )

    def _kpis(df: pd.DataFrame) -> dict:
        n = int(len(df))
        revenue = float(df["deal_amount"].sum()) if not df.empty else 0.0
        avg = (revenue / n) if n else None
        cycle_vals = df["sales_cycle_days"].dropna().tolist()
        cycle_median = float(pd.Series(cycle_vals).median()) if cycle_vals else None
        return {
            "new_revenue": revenue,
            "avg_deal_size": avg,
            "new_customers": n,
            "sales_cycle_median": cycle_median,
        }

    total = _kpis(table)
    marketing = _kpis(table[table["is_marketing"] == True]) if not table.empty else _kpis(table)

    return {
        "total_new_revenue": total["new_revenue"],
        "total_avg_deal_size": total["avg_deal_size"],
        "total_new_customers": total["new_customers"],
        "total_sales_cycle_median": total["sales_cycle_median"],
        "mkt_new_revenue": marketing["new_revenue"],
        "mkt_avg_deal_size": marketing["avg_deal_size"],
        "mkt_new_customers": marketing["new_customers"],
        "mkt_sales_cycle_median": marketing["sales_cycle_median"],
    }


def group_funnel_costs(
    *,
    fb_ytd: pd.DataFrame,
    contacts_ytd: pd.DataFrame,
    meetings_ytd: pd.DataFrame,
    deals_ytd: pd.DataFrame,
    contact_deals_ytd: pd.DataFrame,
    asset_to_group: dict,
    stages_closed_won,
    closed_deals_table: pd.DataFrame | None = None,
    groups: tuple[str, ...] = ("Chiro", "EMX", "PT Recovery", "TheraRay"),
) -> pd.DataFrame:
    """Per-source YTD funnel + cost-per-stage breakdown.

    Returns a DataFrame with one row per group plus a 'Total' row:
      group, ad_spend, leads, cpl,
      fifteen_booked, cost_per_fifteen_booked,
      strategy_booked, cost_per_strategy_booked,
      closed_won, cost_per_close.

    Inputs:
      fb_ytd            FB insights frame for Jan 1 -> today (group, spend, ...)
      contacts_ytd      contacts whose typeform_submission_date falls in YTD
                        (plus TheraRay list members for that group).
      meetings_ytd      meetings whose hs_meeting_start_time falls in YTD
                        (cols: meeting_id, contact_id, activity_type, outcome,
                         start_time).
      deals_ytd         closed-won deals YTD.
      contact_deals_ytd associations for those deals.

    Funnel counts are unique-contact counts per group (a contact with 2
    Strategy meetings counts once for Strategy Booked).
    """
    cols = ["group", "ad_spend", "leads", "cpl",
            "fifteen_booked", "cost_per_fifteen_booked",
            "strategy_booked", "cost_per_strategy_booked",
            "closed_won", "cost_per_close"]
    if contacts_ytd is None:
        contacts_ytd = pd.DataFrame()
    if meetings_ytd is None:
        meetings_ytd = pd.DataFrame()
    if deals_ytd is None:
        deals_ytd = pd.DataFrame()
    if contact_deals_ytd is None:
        contact_deals_ytd = pd.DataFrame(columns=["contact_id", "deal_id"])

    # 1) Spend per group
    if not fb_ytd.empty and "group" in fb_ytd.columns:
        spend_by_group = fb_ytd.groupby("group", dropna=True)["spend"].sum().to_dict()
    else:
        spend_by_group = {}

    # 2) Tag contacts with group. Typeform → ASSET_TO_GROUP wins; closed-deals
    # table is the secondary signal (covers long-cycle closes whose typeform
    # submission predates the window + CONTACT_SOURCE_OVERRIDES marketing
    # attributions that don't appear in contacts_ytd).
    contacts_ytd = contacts_ytd.copy()
    if not contacts_ytd.empty:
        contacts_ytd["group"] = contacts_ytd["typeform_asset_download"].map(asset_to_group)
    cid_to_group: dict[str, str | None] = {}
    if not contacts_ytd.empty:
        for _, c in contacts_ytd.iterrows():
            cid_to_group[str(c["hs_id"])] = c.get("group")
    if closed_deals_table is not None and not closed_deals_table.empty:
        for _, r in closed_deals_table.iterrows():
            if not r.get("is_marketing"):
                continue
            cid = str(r.get("hs_id"))
            grp = r.get("group")
            if cid_to_group.get(cid) in (None, "") and grp:
                cid_to_group[cid] = grp

    # 3) Lead counts per group
    leads_by_group: dict[str, int] = {}
    if not contacts_ytd.empty:
        for g, n in contacts_ytd.groupby("group", dropna=True).size().items():
            leads_by_group[g] = int(n)

    # 4) Meeting funnel — unique contacts per stage
    f15_booked_cids: set = set()
    strat_booked_cids: set = set()
    if not meetings_ytd.empty:
        types = meetings_ytd["activity_type"].fillna("").astype(str).str.lower()
        f15_booked_cids = set(
            meetings_ytd.loc[types.str.contains("15 min", na=False),
                              "contact_id"].astype(str).unique()
        )
        strat_booked_cids = set(
            meetings_ytd.loc[types.str.contains("strategy", na=False),
                              "contact_id"].astype(str).unique()
        )

    # 5) Closed-won per group. Prefer closed_deals_table when supplied —
    # its is_marketing + group columns are the same signals that drive the
    # Marketing Customers KPI, so totals line up exactly. Fall back to the
    # legacy deal-stage intersection only when no closed_deals_table provided.
    won_by_group: dict[str, int] = {}
    won_total = 0
    if closed_deals_table is not None and not closed_deals_table.empty:
        mkt = closed_deals_table[closed_deals_table["is_marketing"] == True]
        won_total = int(len(mkt))
        for g, n in mkt.groupby("group", dropna=False).size().items():
            won_by_group[g if g else "(unmapped)"] = int(n)
    else:
        if not deals_ytd.empty and not contact_deals_ytd.empty:
            won_set = set(stages_closed_won)
            won_deal_ids = set(deals_ytd.loc[deals_ytd["dealstage"].isin(won_set), "deal_id"])
            won_cids = set(
                contact_deals_ytd.loc[contact_deals_ytd["deal_id"].isin(won_deal_ids),
                                       "contact_id"].astype(str)
            )
            for cid in won_cids:
                g = cid_to_group.get(cid)
                if g:
                    won_by_group[g] = won_by_group.get(g, 0) + 1
            won_total = sum(won_by_group.values())

    def _per_g(s: set, g: str) -> int:
        return sum(1 for cid in s if cid_to_group.get(cid) == g)

    def _div(num, den):
        return (num / den) if den else None

    rows = []
    listed = set(groups)
    for g in groups:
        spend = float(spend_by_group.get(g, 0.0))
        leads = int(leads_by_group.get(g, 0))
        f15b = _per_g(f15_booked_cids, g)
        sb = _per_g(strat_booked_cids, g)
        cw = int(won_by_group.get(g, 0))
        rows.append({
            "group": g,
            "ad_spend": spend,
            "leads": leads,
            "cpl": _div(spend, leads),
            "fifteen_booked": f15b,
            "cost_per_fifteen_booked": _div(spend, f15b),
            "strategy_booked": sb,
            "cost_per_strategy_booked": _div(spend, sb),
            "closed_won": cw,
            "cost_per_close": _div(spend, cw),
        })

    # "Other" bucket: any closed-marketing deal whose group is outside the
    # listed groups (e.g., "(unmapped)" tier, niche category). Surfaces the
    # gap so totals reconcile to Marketing Customers.
    other_cw = sum(n for g, n in won_by_group.items() if g not in listed)
    if other_cw > 0:
        rows.append({
            "group": "Other",
            "ad_spend": 0.0,           # no FB spend tag for these groups
            "leads": 0,
            "cpl": None,
            "fifteen_booked": 0,
            "cost_per_fifteen_booked": None,
            "strategy_booked": 0,
            "cost_per_strategy_booked": None,
            "closed_won": int(other_cw),
            "cost_per_close": None,
        })

    # Totals row — closed-won uses the marketing-customer total so it
    # reconciles to the Marketing Customers KPI above.
    total_spend = sum(r["ad_spend"] for r in rows if r["group"] != "Other")
    total_leads = sum(r["leads"] for r in rows if r["group"] != "Other")
    total_f15 = sum(r["fifteen_booked"] for r in rows if r["group"] != "Other")
    total_sb = sum(r["strategy_booked"] for r in rows if r["group"] != "Other")
    total_cw = won_total if closed_deals_table is not None else sum(
        r["closed_won"] for r in rows if r["group"] != "Other"
    )
    rows.append({
        "group": "Total",
        "ad_spend": total_spend,
        "leads": total_leads,
        "cpl": _div(total_spend, total_leads),
        "fifteen_booked": total_f15,
        "cost_per_fifteen_booked": _div(total_spend, total_f15),
        "strategy_booked": total_sb,
        "cost_per_strategy_booked": _div(total_spend, total_sb),
        "closed_won": total_cw,
        "cost_per_close": _div(total_spend, total_cw),
    })
    return pd.DataFrame(rows, columns=cols)


def compute_close_commissions(
    deals_table: pd.DataFrame,
    *,
    sdr_close: dict,
    bds_close: float,
    sme_close: dict,
    flat_close: float,
) -> dict:
    """Sum per-closed-deal sales commissions across a closed-deals table.

    Expects the output of build_closed_deals_table (columns: typeform, group,
    sdr_owner, ...). Per-close commission rules (Dr. Gumm, 2026-05-22):

    - SDR: warm $200 / cold $400. Warm = 'typeform' column non-empty (contact
      had a marketing opt-in). Only billed when an SDR is assigned.
    - BDS: flat bds_close on every closed deal.
    - SME: sme_close[group], default sme_close['_default']. Chiro=$2000;
      PT/EMX/MUDA=$1000.
    - Flat (Gerri): flat_close on every closed deal.

    Returns dict: total, sdr_total, bds_total, sme_total, flat_total, n_deals.
    """
    keys = ["total", "sdr_total", "bds_total", "sme_total", "flat_total", "n_deals"]
    if deals_table is None or deals_table.empty:
        return {k: 0.0 for k in keys[:-1]} | {"n_deals": 0}

    df = deals_table
    n = int(len(df))

    typeform_col = df["typeform"] if "typeform" in df.columns else pd.Series([""] * n, index=df.index)
    warm = typeform_col.fillna("").astype(str).str.strip() != ""
    sdr_col = df["sdr_owner"] if "sdr_owner" in df.columns else pd.Series([""] * n, index=df.index)
    has_sdr = sdr_col.fillna("").astype(str).str.strip() != ""

    sdr_amt = warm.map(lambda w: sdr_close["warm"] if w else sdr_close["cold"])
    sdr_amt = sdr_amt.where(has_sdr, 0.0)

    bds_total = float(bds_close) * n

    group_col = df["group"] if "group" in df.columns else pd.Series([None] * n, index=df.index)
    default_sme = float(sme_close.get("_default", 0.0))
    sme_amt = group_col.map(lambda g: float(sme_close.get(g, default_sme)))
    # MUDA override: 'send_contract' containing "MUDA" (multi-unit discount
    # agreement) bills at the MUDA SME rate regardless of group (group is
    # usually Chiro for these). See send_contract_options HubSpot property.
    if "send_contract" in df.columns:
        muda_rate = float(sme_close.get("MUDA", default_sme))
        is_muda = df["send_contract"].fillna("").astype(str).str.contains("MUDA", case=False)
        sme_amt = sme_amt.where(~is_muda, muda_rate)

    flat_total = float(flat_close) * n

    sdr_total = float(sdr_amt.sum())
    sme_total = float(sme_amt.sum())
    return {
        "sdr_total": sdr_total,
        "bds_total": bds_total,
        "sme_total": sme_total,
        "flat_total": flat_total,
        "total": sdr_total + bds_total + sme_total + flat_total,
        "n_deals": n,
    }
