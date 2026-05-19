"""Pull AirCall calls for a date range, return normalized DataFrame."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import requests
import streamlit as st


AIRCALL_API = "https://api.aircall.io/v1"
PAGE_SIZE = 50


def _normalize_phone(s) -> str:
    """Last-10-digits normalization for US phone matching."""
    if s is None:
        return ""
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


@st.cache_data(ttl=900, show_spinner="Pulling AirCall calls...")
def load_aircall_calls(start: date, end: date) -> pd.DataFrame:
    """Return all calls in window.

    Columns: call_id, started_at_utc, answered_at_utc, duration, direction,
             status, user_id, user_name, raw_digits, phone_normalized.

    Pagination: 50/page, follows the Aircall `meta.next_page_link` until exhausted.
    """
    cols = ["call_id", "started_at_utc", "answered_at_utc", "duration",
            "direction", "status", "user_id", "user_name",
            "raw_digits", "phone_normalized"]

    api_id = st.secrets.get("AIRCALL_API_ID") or st.secrets.get("API_ID")
    api_token = st.secrets.get("AIRCALL_API_token") or st.secrets.get("API_token")
    if not api_id or not api_token:
        return pd.DataFrame(columns=cols)

    auth = (api_id, api_token)
    start_ts = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.combine(end, datetime.max.time(),
                                   tzinfo=timezone.utc).timestamp())

    rows = []
    page = 1
    while True:
        r = requests.get(
            f"{AIRCALL_API}/calls",
            auth=auth,
            params={
                "from": start_ts, "to": end_ts,
                "per_page": PAGE_SIZE, "page": page,
                "order": "asc",
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        calls = data.get("calls", [])
        for c in calls:
            user = c.get("user") or {}
            raw = c.get("raw_digits") or ""
            rows.append({
                "call_id": str(c.get("id")),
                "started_at_utc": c.get("started_at"),
                "answered_at_utc": c.get("answered_at"),
                "duration": int(c.get("duration") or 0),
                "direction": c.get("direction"),
                "status": c.get("status"),
                "user_id": str(user.get("id")) if user.get("id") is not None else "",
                "user_name": user.get("name") or "",
                "raw_digits": raw,
                "phone_normalized": _normalize_phone(raw),
            })
        # Aircall pagination: meta.next_page_link is null at the end
        meta = data.get("meta", {})
        if not meta.get("next_page_link"):
            break
        page += 1
        # Safety cap so a bug can't infinite-loop us
        if page > 200:
            break

    return pd.DataFrame(rows, columns=cols)
