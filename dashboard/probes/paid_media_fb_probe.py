"""FB Marketing API probe for the paid media reconciliation report.

Pulls insights at campaign, adset, and ad level for four date windows, plus a
separate entity pull for delivery status and creative destination URLs
(effective_status and creative are object fields, NOT insights fields).

Read-only. GET requests only.
Run from repo root: python dashboard/probes/paid_media_fb_probe.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")

import requests
import streamlit as st

FB_API = "https://graph.facebook.com/v19.0"

OUT = Path(r"C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad")

WINDOWS = {
    "w14": (date(2026, 7, 22), date(2026, 8, 4)),
    "w7": (date(2026, 7, 29), date(2026, 8, 4)),
    "w3": (date(2026, 8, 2), date(2026, 8, 4)),
    "checksum": (date(2026, 7, 21), date(2026, 8, 3)),
}

LEVELS = ("campaign", "adset", "ad")

BASE_FIELDS = [
    "spend", "impressions", "reach", "frequency",
    "clicks", "inline_link_clicks", "unique_clicks",
    "ctr", "inline_link_click_ctr", "cpc",
    "cost_per_inline_link_click", "cpm",
    "actions", "action_values", "cost_per_action_type",
    "video_play_actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "video_thruplay_watched_actions",
    "quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking",
    "date_start", "date_stop",
]

ID_FIELDS = {
    "campaign": ["campaign_id", "campaign_name"],
    "adset": ["campaign_id", "campaign_name", "adset_id", "adset_name"],
    "ad": ["campaign_id", "campaign_name", "adset_id", "adset_name",
           "ad_id", "ad_name"],
}

TOKEN = st.secrets["FB_ADS_TOKEN"]
ACCT = st.secrets["FB_AD_ACCOUNT_ID"]

# Skip any output file that already exists, so a retry under a throttle
# doesn't re-burn quota re-fetching data already on disk. Pass --force to
# ignore existing files and re-pull everything.
FORCE = "--force" in sys.argv[1:]


def _get_all(url: str, params: dict) -> list[dict]:
    """GET with cursor pagination. Returns every row across all pages."""
    rows: list[dict] = []
    page = 0
    while True:
        r = requests.get(url, params=params, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"FB API {r.status_code}: {r.text[:600]}")
        payload = r.json()
        rows.extend(payload.get("data", []))
        nxt = (payload.get("paging") or {}).get("next")
        page += 1
        if not nxt or page > 60:
            break
        url, params = nxt, {}   # `next` is a fully-formed URL
        time.sleep(0.3)
    return rows


def pull_insights(level: str, start: date, end: date) -> list[dict]:
    fields = ID_FIELDS[level] + BASE_FIELDS
    params = {
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "level": level,
        "fields": ",".join(fields),
        "access_token": TOKEN,
        "limit": 200,
        "filtering": '[{"field":"spend","operator":"GREATER_THAN","value":0}]',
    }
    return _get_all(f"{FB_API}/act_{ACCT}/insights", params)


def pull_daily(level: str, start: date, end: date) -> list[dict]:
    """Same as pull_insights but broken out one row per day (time_increment=1).

    Used for the w14 window only, to check whether spend for the most recent
    day(s) is still settling relative to a reference pull taken earlier.
    """
    fields = ID_FIELDS[level] + BASE_FIELDS
    params = {
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "level": level,
        "fields": ",".join(fields),
        "access_token": TOKEN,
        "limit": 200,
        "time_increment": 1,
        "filtering": '[{"field":"spend","operator":"GREATER_THAN","value":0}]',
    }
    return _get_all(f"{FB_API}/act_{ACCT}/insights", params)


def collect_ad_ids() -> list[str]:
    """Distinct ad_id values across the four already-written ad-level files.

    Reads from disk rather than re-pulling insights, since main() writes
    these files before calling pull_entities.
    """
    ids = set()
    for wname in WINDOWS:
        path = OUT / f"fb_{wname}_ad.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        for r in rows:
            aid = r.get("ad_id")
            if aid:
                ids.add(aid)
    return sorted(ids)


def pull_entities(ad_ids: list[str]) -> list[dict]:
    """Ad objects with delivery status and creative destination URL.

    Only the ads that actually spent in one of our four windows (ad_ids),
    fetched by id in chunks via the Graph API's batch-by-ids form. This
    avoids walking every ad the account has ever run, which is what
    triggered account-level rate limiting when this pulled the whole account.

    The destination link lives in one of two places depending on how the ad
    was built: object_story_spec.link_data.link for a single creative, or
    asset_feed_spec.link_urls[].website_url for a Flexible/dynamic creative.
    Both are checked.
    """
    fields = (
        "id,name,effective_status,"
        "adset{id,name,effective_status},"
        "campaign{id,name,effective_status},"
        "creative{id,body,title,thumbnail_url,link_url,"
        "object_story_spec,asset_feed_spec}"
    )

    raw = []
    for i in range(0, len(ad_ids), 50):
        chunk = ad_ids[i:i + 50]
        r = requests.get(
            f"{FB_API}/",
            params={
                "ids": ",".join(chunk),
                "fields": fields,
                "access_token": TOKEN,
            },
            timeout=90,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"FB API {r.status_code}: {r.text[:600]}")
        by_id = r.json()   # dict keyed by ad id, not a `data` list
        raw.extend(by_id.values())
        time.sleep(1)

    out = []
    for ad in raw:
        cr = ad.get("creative") or {}
        link = cr.get("link_url")
        if not link:
            spec = (cr.get("object_story_spec") or {}).get("link_data") or {}
            link = spec.get("link")
        if not link:
            feed = (cr.get("asset_feed_spec") or {}).get("link_urls") or []
            link = feed[0].get("website_url") if feed else None
        out.append({
            "ad_id": ad.get("id"),
            "ad_name": ad.get("name"),
            "adset_id": (ad.get("adset") or {}).get("id"),
            "campaign_id": (ad.get("campaign") or {}).get("id"),
            "effective_status": ad.get("effective_status"),
            "adset_effective_status": (ad.get("adset") or {}).get("effective_status"),
            "campaign_effective_status": (ad.get("campaign") or {}).get("effective_status"),
            "link_url": link,
            "body": cr.get("body"),
            "title": cr.get("title"),
            "thumbnail_url": cr.get("thumbnail_url"),
        })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for wname, (start, end) in WINDOWS.items():
        for level in LEVELS:
            path = OUT / f"fb_{wname}_{level}.json"
            if path.exists() and not FORCE:
                print(f"{path.name} exists, skipping")
                continue
            rows = pull_insights(level, start, end)
            path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
            spend = sum(float(r.get("spend", 0)) for r in rows)
            print(f"{wname:9s} {level:8s} rows={len(rows):4d} spend=${spend:,.2f}")

    daily_path = OUT / "fb_w14_daily.json"
    if daily_path.exists() and not FORCE:
        print(f"{daily_path.name} exists, skipping")
    else:
        daily = pull_daily("campaign", *WINDOWS["w14"])
        daily_path.write_text(json.dumps(daily, indent=1), encoding="utf-8")
        by_day: dict[str, float] = {}
        for r in daily:
            by_day[r.get("date_start")] = by_day.get(r.get("date_start"), 0.0) + float(r.get("spend", 0))
        for d in sorted(by_day):
            print(f"w14 daily  {d}  spend=${by_day[d]:,.2f}")

    entities_path = OUT / "fb_entities.json"
    if entities_path.exists() and not FORCE:
        print(f"{entities_path.name} exists, skipping")
    else:
        ad_ids = collect_ad_ids()
        ents = pull_entities(ad_ids)
        entities_path.write_text(json.dumps(ents, indent=1), encoding="utf-8")
        active = [e for e in ents if e["effective_status"] == "ACTIVE"]
        print(f"entities: {len(ad_ids)} distinct ad_ids, {len(ents)} ads fetched, "
              f"{len(active)} ACTIVE, "
              f"{sum(1 for e in ents if not e['link_url'])} missing link_url")


if __name__ == "__main__":
    main()
