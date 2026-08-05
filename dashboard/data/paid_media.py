"""Pure paid-media reconciliation and cut-list logic. No I/O.

Every function here takes plain data and config values as parameters so it can
be unit tested without touching FB, Hyros, or HubSpot. Follows the
dependency-injected style of dashboard/data/reconcile.py.
"""
from __future__ import annotations

LEAD_ACTION_TYPES = (
    "offsite_conversion.fb_pixel_lead",
    "lead",
    "onsite_conversion.lead_grouped",
)

LP_VIEW_ACTION = "landing_page_view"


def _f(value) -> float:
    """Coerce an FB string number to float. FB returns numerics as strings."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _div(num: float, den: float) -> float | None:
    """Divide, returning None on a zero denominator rather than 0 or inf.

    None means "not computable", which is different from a real zero. The
    tiering logic in tier_ads depends on that distinction.
    """
    if not den:
        return None
    return num / den


def action_value(actions, action_type: str) -> float:
    """Pull one action_type's value out of an FB actions list."""
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            return _f(a.get("value"))
    return 0.0


def first_lead_value(actions) -> float:
    """FB reports leads under different action types depending on the funnel.

    Returns the first non-zero match in LEAD_ACTION_TYPES priority order.
    """
    for atype in LEAD_ACTION_TYPES:
        v = action_value(actions, atype)
        if v:
            return v
    return 0.0


def derive_metrics(row: dict) -> dict:
    """Add computed metrics to one FB insights row. Does not mutate `row`."""
    spend = _f(row.get("spend"))
    impressions = _f(row.get("impressions"))
    link_clicks = _f(row.get("inline_link_clicks"))
    actions = row.get("actions")

    fb_leads = first_lead_value(actions)
    lp_views = action_value(actions, LP_VIEW_ACTION)
    three_sec = action_value(row.get("video_3_sec_watched_actions"),
                             "video_view")
    if not three_sec:
        three_sec = action_value(row.get("video_play_actions"), "video_view")
    thruplay = action_value(row.get("video_thruplay_watched_actions"),
                            "video_view")

    return {
        "spend": spend,
        "impressions": impressions,
        "link_clicks": link_clicks,
        "fb_leads": fb_leads,
        "lp_views": lp_views,
        "link_cpc": _div(spend, link_clicks),
        "link_ctr": _div(link_clicks, impressions),
        "cpm_calc": _div(spend * 1000.0, impressions),
        "cpl": _div(spend, fb_leads),
        "cost_per_lp_view": _div(spend, lp_views),
        "lp_view_to_lead": _div(fb_leads, lp_views),
        "hook_rate": _div(three_sec, impressions),
        "hold_rate": _div(thruplay, three_sec),
    }


def reconcile_lead_counts(fb_leads: float, hyros_leads: float,
                          hubspot_leads: float,
                          over_report_pct: float = 0.20,
                          agreement_pct: float = 0.10) -> dict:
    """Compare the three lead counts for one campaign/adset/ad.

    Hyros is the variance baseline because it is the attribution system of
    record. `trusted_count` is whichever value two sources agree on within
    `agreement_pct`, falling back to Hyros when all three disagree.
    """
    fb = float(fb_leads or 0)
    hy = float(hyros_leads or 0)
    hs = float(hubspot_leads or 0)

    fb_vs_hy = _div(fb - hy, hy)
    hy_vs_hs = _div(hy - hs, hs)

    flags: list[str] = []
    if fb_vs_hy is not None and fb_vs_hy > over_report_pct:
        flags.append("FB_OVER_REPORT")
    if hy_vs_hs is not None and hy_vs_hs > over_report_pct:
        flags.append("HYROS_WITHOUT_CRM")
    if hy_vs_hs is not None and hy_vs_hs < -over_report_pct:
        flags.append("HYROS_UNDERTRACKING")
    if hy == 0 and fb > 0:
        flags.append("HYROS_ZERO_WITH_FB_LEADS")

    def agree(a: float, b: float) -> bool:
        if a == b:
            return True
        rel = _div(abs(a - b), max(a, b))
        return rel is not None and rel <= agreement_pct

    if agree(hy, hs):
        trusted = min(hy, hs)
    elif agree(fb, hy):
        trusted = hy
    elif agree(fb, hs):
        trusted = hs
    else:
        trusted = hy

    return {
        "fb_leads": fb,
        "hyros_leads": hy,
        "hubspot_leads": hs,
        "fb_vs_hyros_pct": fb_vs_hy,
        "hyros_vs_hubspot_pct": hy_vs_hs,
        "flags": flags,
        "trusted_count": trusted,
    }
