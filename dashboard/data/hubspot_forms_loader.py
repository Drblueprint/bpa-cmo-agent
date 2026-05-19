"""Pull HubSpot form submissions per form, per date range."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import requests
import streamlit as st

HS_API = "https://api.hubapi.com"


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot form submissions...")
def load_form_submissions(form_ids: list[str], start: date, end: date) -> pd.DataFrame:
    """Return submissions for the given form IDs in window.

    Columns: form_id, submission_id, submitted_at, email.
    """
    cols = ["form_id", "submission_id", "submitted_at", "email"]
    if not form_ids:
        return pd.DataFrame(columns=cols)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end, datetime.max.time(),
                                   tzinfo=timezone.utc).timestamp() * 1000)

    rows = []
    for form_id in form_ids:
        after = None
        while True:
            params = {"limit": 50}
            if after:
                params["after"] = after
            r = requests.get(
                f"{HS_API}/form-integrations/v1/submissions/forms/{form_id}",
                headers=headers,
                params=params,
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            for s in data.get("results", []):
                submitted_ms = s.get("submittedAt")
                if submitted_ms is None:
                    continue
                if not (start_ms <= submitted_ms <= end_ms):
                    continue
                submitted = datetime.fromtimestamp(
                    submitted_ms / 1000, tz=timezone.utc
                ).isoformat()
                # Find the email value if present
                email = ""
                for v in s.get("values", []):
                    if v.get("name") == "email":
                        email = v.get("value", "")
                        break
                rows.append({
                    "form_id": form_id,
                    "submission_id": s.get("id") or s.get("submissionId") or "",
                    "submitted_at": submitted,
                    "email": email,
                })
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break

    return pd.DataFrame(rows, columns=cols)
