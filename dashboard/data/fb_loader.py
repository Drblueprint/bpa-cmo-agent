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


@st.cache_data(ttl=900, show_spinner="Loading ad-level performance...")
def load_fb_ad_insights(start: date, end: date) -> pd.DataFrame:
    """Ad-level insights for the Creative Tracker.

    video_plays is how Format is derived. The creative object reports
    object_type SHARE and a null video_id on every ad in this account,
    because the ads share existing posts rather than embedding creative, so
    the creative object cannot distinguish video from static. Video play
    actions can.

    Columns: ad_id, ad_name, campaign_name, spend, impressions, clicks,
             video_plays
    """
    token = st.secrets["FB_ADS_TOKEN"]
    acct = st.secrets["FB_AD_ACCOUNT_ID"]
    params = {
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "level": "ad",
        "fields": ("ad_id,ad_name,campaign_name,spend,impressions,clicks,"
                   "video_play_actions"),
        "access_token": token,
        "limit": 500,
    }
    r = requests.get(f"{FB_API}/act_{acct}/insights", params=params, timeout=90)
    r.raise_for_status()
    rows = []
    for row in r.json().get("data", []):
        plays = 0.0
        for a in (row.get("video_play_actions") or []):
            try:
                plays += float(a.get("value", 0))
            except (TypeError, ValueError):
                pass
        rows.append({
            "ad_id": str(row.get("ad_id")),
            "ad_name": row.get("ad_name", ""),
            "campaign_name": row.get("campaign_name", ""),
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0) or 0),
            "clicks": int(row.get("clicks", 0) or 0),
            "video_plays": plays,
        })
    return pd.DataFrame(rows, columns=[
        "ad_id", "ad_name", "campaign_name", "spend", "impressions",
        "clicks", "video_plays",
    ])


@st.cache_data(ttl=900, show_spinner="Loading ad creative details...")
def load_fb_ad_entities(ad_ids: tuple[str, ...]) -> pd.DataFrame:
    """Launch date, delivery status and post permalink id, per ad.

    These are object fields, NOT insights fields; requesting them in an
    insights call errors. Fetched in batches of 25 because creative
    expansion at larger page sizes returns HTTP 500 from FB.

    Columns: ad_id, created_time, effective_status, story_id
    """
    token = st.secrets["FB_ADS_TOKEN"]
    rows = []
    failed_chunks = []
    first_error_code = None

    for i in range(0, len(ad_ids), 25):
        chunk = ad_ids[i:i + 25]
        r = requests.get(
            f"{FB_API}/",
            params={
                "ids": ",".join(chunk),
                "fields": ("id,created_time,effective_status,"
                           "creative{effective_object_story_id}"),
                "access_token": token,
            },
            timeout=90)
        if not r.ok:
            failed_chunks.append(len(chunk))
            if first_error_code is None:
                first_error_code = r.status_code
            continue
        for _aid, node in (r.json() or {}).items():
            rows.append({
                "ad_id": str(node.get("id")),
                "created_time": node.get("created_time"),
                "effective_status": node.get("effective_status"),
                "story_id": (node.get("creative") or {}).get(
                    "effective_object_story_id"),
            })

    if failed_chunks:
        failed_count = sum(failed_chunks)
        st.warning(f"Creative data missing for {failed_count} of {len(ad_ids)} ads (first error: HTTP {first_error_code})")

    return pd.DataFrame(rows, columns=[
        "ad_id", "created_time", "effective_status", "story_id"])
