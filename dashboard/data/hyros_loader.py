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
    rows_in = (data.get("result") or {}).get("leads") or data.get("data") or []
    rows = []
    for x in rows_in:
        fs = x.get("firstSource")
        ls = x.get("lastSource")
        rows.append({
            "lead_id": x.get("id"),
            "email": x.get("email"),
            "first_source": (fs.get("name") if isinstance(fs, dict) else fs) or "unattributed",
            "last_source": (ls.get("name") if isinstance(ls, dict) else ls) or "unattributed",
            "created": x.get("createdDate") or x.get("created"),
        })
    return pd.DataFrame(rows)
