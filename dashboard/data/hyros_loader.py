"""Pull Hyros lead and call attribution for a date range."""
from __future__ import annotations

from datetime import date

import pandas as pd
import requests
import streamlit as st


HYROS_API = "https://api.hyros.com/v1/api/v1.0"


def _call(path: str, key: str, start: date, end: date) -> dict:
    headers = {"API-Key": key}
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": 250,
    }
    r = requests.get(f"{HYROS_API}{path}", headers=headers,
                     params=params, timeout=60)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=900, show_spinner="Pulling Hyros attribution...")
def load_hyros_leads(start: date, end: date) -> pd.DataFrame:
    """Return Hyros leads with their attributed ad source.

    Columns: lead_id, email, first_source, last_source, created.
    """
    key = st.secrets["HYROS_API_KEY"]
    data = _call("/leads", key, start, end)
    rows_in = data.get("result") or data.get("data") or []
    if not isinstance(rows_in, list):
        rows_in = []
    def _source_label(src) -> str:
        """Pick the campaign-level name when available; fall back to ad set name."""
        if not isinstance(src, dict):
            return src or "unattributed"
        category = src.get("category")
        if isinstance(category, dict) and category.get("name"):
            return category["name"]
        return src.get("name") or "unattributed"

    rows = []
    for x in rows_in:
        rows.append({
            "lead_id": x.get("id"),
            "email": x.get("email"),
            "first_source": _source_label(x.get("firstSource")),
            "last_source": _source_label(x.get("lastSource")),
            "created": x.get("createdDate") or x.get("created"),
        })
    return pd.DataFrame(rows, columns=[
        "lead_id", "email", "first_source", "last_source", "created",
    ])


def _next_page_params(payload: dict, params: dict) -> dict | None:
    """Hyros paging: the response's nextPageId goes back as pageId.

    Verified per-endpoint in dashboard/probes/paid_media_hyros_probe.py.
    nextPageToken/pageToken is kept as a documented fallback.
    """
    if payload.get("nextPageId"):
        return dict(params, pageId=payload["nextPageId"])
    if payload.get("nextPageToken"):
        return dict(params, pageToken=payload["nextPageToken"])
    return None


@st.cache_data(ttl=900, show_spinner="Pulling Hyros ad attribution...")
def load_hyros_leads_with_ads(start: date, end: date) -> pd.DataFrame:
    """Hyros leads retaining the FB ad id, for the Creative Tracker.

    Separate from load_hyros_leads because that one flattens sources to a
    display label and discards the ad id, and does not paginate.

    The ad id lives at firstSource.sourceLinkAd.adSourceId, falling back to
    lastSource. Note this routes through the LEAD record deliberately: Hyros
    sale records arrive from the HubSpot integration with no firstSource or
    lastSource block at all, so a direct sale-to-ad join is impossible.

    Columns: email, ad_id, created
    """
    key = st.secrets["HYROS_API_KEY"]
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": 250,
    }
    rows_in: list[dict] = []
    seen_pages = 0
    prev_page_id = None  # Track for stuck cursor detection
    while True:
        r = requests.get(f"{HYROS_API}/leads", headers={"API-Key": key},
                         params=params, timeout=90)
        r.raise_for_status()
        payload = r.json()
        # Distinguish unexpected response shape from genuinely empty results.
        if "result" not in payload and "data" not in payload:
            st.warning(
                "Hyros /leads returned an unexpected response shape with no "
                "'result' or 'data' key. Ad-level attribution may be incomplete.")
            break
        batch = payload.get("result") or payload.get("data") or []
        if not isinstance(batch, list) or not batch:
            break
        rows_in.extend(batch)
        seen_pages += 1
        nxt = _next_page_params(payload, params)
        if nxt is None:
            # A full page with no paging token is suspicious: it usually
            # means truncation rather than a genuine end of results.
            if len(batch) == params["pageSize"]:
                st.warning(
                    f"Hyros /leads returned a full page ({len(batch)} rows) "
                    "with no paging token. Ad-level lead counts may be "
                    "truncated.")
            break
        # Detect stuck cursor (repeated pageId) to avoid burning requests.
        current_page_id = nxt.get("pageId")
        if current_page_id == prev_page_id and current_page_id is not None:
            st.warning(
                f"Hyros /leads pagination token did not change after page {seen_pages}. "
                "Results may be duplicated or incomplete.")
            break
        prev_page_id = current_page_id
        params = nxt
        if seen_pages > 200:  # runaway guard
            st.warning(
                f"Hyros /leads exceeded 200 pages ({seen_pages}). "
                "Results may be incomplete or duplicated.")
            break

    rows = []
    for x in rows_in:
        email = (x.get("email") or "").strip().lower()
        if not email:
            continue
        ad_id = None
        for key_name in ("firstSource", "lastSource"):
            sla = ((x.get(key_name) or {}).get("sourceLinkAd") or {})
            if sla.get("adSourceId"):
                ad_id = str(sla["adSourceId"])
                break
        rows.append({
            "email": email,
            "ad_id": ad_id,
            "created": x.get("createdDate") or x.get("created"),
        })
    return pd.DataFrame(rows, columns=["email", "ad_id", "created"])
