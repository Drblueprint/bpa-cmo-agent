"""Pull Facebook Ads insights for a date range, return per-campaign dataframe."""
from __future__ import annotations

from datetime import date

import pandas as pd
import requests
import streamlit as st

from dashboard.data.groups import match_group


FB_API = "https://graph.facebook.com/v19.0"


def _action_value(actions: list | None, atype: str) -> float:
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == atype:
            return float(a.get("value", 0))
    return 0.0


@st.cache_data(ttl=900, show_spinner="Pulling Facebook Ads...")
def load_fb_insights(start: date, end: date,
                     time_increment_days: int | None = None) -> pd.DataFrame:
    """Return a dataframe with columns: campaign_name, group, spend, impressions,
    clicks, fb_leads, date_start, date_stop.

    One row per campaign. Caches for 15 minutes per date range.

    If time_increment_days is set, FB returns one row per campaign per period
    of that many days. E.g., time_increment_days=7 -> weekly breakdown.
    """
    token = st.secrets["FB_ADS_TOKEN"]
    acct = st.secrets["FB_AD_ACCOUNT_ID"]

    params = {
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "level": "campaign",
        "fields": "campaign_id,campaign_name,spend,impressions,clicks,inline_link_clicks,actions,date_start,date_stop",
        "access_token": token,
        "limit": 500,
    }
    if time_increment_days:
        params["time_increment"] = time_increment_days
    r = requests.get(f"{FB_API}/act_{acct}/insights", params=params, timeout=60)
    r.raise_for_status()
    rows = r.json().get("data", [])

    records = []
    for row in rows:
        name = row.get("campaign_name", "")
        records.append({
            "campaign_id": row.get("campaign_id"),  # NEW
            "campaign_name": name,
            "group": match_group(name),
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "inline_link_clicks": int(row.get("inline_link_clicks", 0)),
            "fb_leads": _action_value(row.get("actions"),
                                      "offsite_conversion.fb_pixel_lead")
                        or _action_value(row.get("actions"), "lead"),
            "date_start": row.get("date_start"),
            "date_stop": row.get("date_stop"),
        })
    return pd.DataFrame(records)
