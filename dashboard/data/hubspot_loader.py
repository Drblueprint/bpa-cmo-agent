"""Pull HubSpot marketing leads (contacts) and their associated deals."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import pandas as pd
import requests
import streamlit as st

from dashboard import config as cfg


HS_API = "https://api.hubapi.com"


def _hs_search(token: str, object_type: str, body: dict) -> list[dict]:
    """Paginate through HubSpot search API."""
    out: list[dict] = []
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(
            f"{HS_API}/crm/v3/objects/{object_type}/search",
            headers={"Authorization": f"Bearer {token}"},
            json=b,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after or len(out) >= 10000:
            break
    return out


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot contacts...")
def load_marketing_contacts(start: date, end: date) -> pd.DataFrame:
    """Return marketing leads (contacts with typeform_asset_download populated)
    created in the window.

    Columns: hs_id, name, email, created, typeform_asset_download, sdr_owner,
    bds, sme, utm_source.
    """
    token = st.secrets["HUBSPOT_TOKEN"]
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int((datetime.combine(end, datetime.max.time(),
                                    tzinfo=timezone.utc)).timestamp() * 1000)
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": cfg.HS_PROP_TYPEFORM_ASSET,
                 "operator": "HAS_PROPERTY"},
                {"propertyName": cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE,
                 "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "createdate",
            cfg.HS_PROP_TYPEFORM_ASSET, cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE,
            cfg.HS_PROP_SDR_OWNER, cfg.HS_PROP_BDS, cfg.HS_PROP_SME,
            cfg.HS_PROP_UTM_SOURCE,
            cfg.HS_PROP_15MIN_CALL_DATE, cfg.HS_PROP_LIFECYCLE_STAGE,
        ],
        "limit": 100,
    }
    results = _hs_search(token, "contacts", body)

    rows = []
    for r in results:
        p = r.get("properties", {})
        # Skip test contacts (firstname or lastname == "TEST", case-insensitive)
        _fn = (p.get("firstname") or "").strip().lower()
        _ln = (p.get("lastname") or "").strip().lower()
        if _fn == "test" or _ln == "test":
            continue
        hs_id = r.get("id")
        rows.append({
            "hs_id": str(hs_id) if hs_id is not None else None,
            "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "email": p.get("email"),
            "created": p.get("createdate"),
            "typeform_asset_download": p.get(cfg.HS_PROP_TYPEFORM_ASSET),
            "typeform_submission_date": p.get(cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE),  # NEW
            "sdr_owner": p.get(cfg.HS_PROP_SDR_OWNER),
            "bds": p.get(cfg.HS_PROP_BDS),
            "sme": p.get(cfg.HS_PROP_SME),
            "utm_source": p.get(cfg.HS_PROP_UTM_SOURCE),
            "fifteen_min_call_date": p.get(cfg.HS_PROP_15MIN_CALL_DATE),
            "lifecycle_stage": p.get(cfg.HS_PROP_LIFECYCLE_STAGE),
        })
    return pd.DataFrame(rows, columns=[
        "hs_id", "name", "email", "created",
        "typeform_asset_download", "typeform_submission_date",
        "sdr_owner", "bds", "sme", "utm_source",
        "fifteen_min_call_date", "lifecycle_stage",
    ])


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot deals...")
def load_deals_in_window(start: date, end: date) -> pd.DataFrame:
    """Return deals modified or created in the window.

    Columns: deal_id, dealname, amount, dealstage, pipeline, createdate,
    closedate.
    """
    token = st.secrets["HUBSPOT_TOKEN"]
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int((datetime.combine(end, datetime.max.time(),
                                    tzinfo=timezone.utc)).timestamp() * 1000)
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "hs_lastmodifieddate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": ["dealname", "amount", "dealstage", "pipeline",
                       "createdate", "closedate"],
        "limit": 100,
    }
    results = _hs_search(token, "deals", body)
    rows = []
    for r in results:
        p = r.get("properties", {})
        deal_id = r.get("id")
        rows.append({
            "deal_id": str(deal_id) if deal_id is not None else None,
            "dealname": p.get("dealname"),
            "amount": float(p.get("amount") or 0),
            "dealstage": p.get("dealstage"),
            "pipeline": p.get("pipeline"),
            "createdate": p.get("createdate"),
            "closedate": p.get("closedate"),
        })
    return pd.DataFrame(rows, columns=[
        "deal_id", "dealname", "amount", "dealstage",
        "pipeline", "createdate", "closedate",
    ])


@st.cache_data(ttl=900, show_spinner="Pulling contact-deal associations...")
def load_contact_deals(contact_ids: list[str]) -> pd.DataFrame:
    """For each contact id, return its associated deal ids.

    Columns: contact_id, deal_id.
    """
    if not contact_ids:
        return pd.DataFrame(columns=["contact_id", "deal_id"])

    token = st.secrets["HUBSPOT_TOKEN"]
    rows = []
    # Batch API: 100 at a time
    for i in range(0, len(contact_ids), 100):
        batch = contact_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v4/associations/contacts/deals/batch/read",
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": [{"id": cid} for cid in batch]},
            timeout=60,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            cid = item.get("from", {}).get("id")
            for t in item.get("to", []):
                deal_id = t.get("toObjectId")
                rows.append({
                    "contact_id": str(cid) if cid is not None else None,
                    "deal_id": str(deal_id) if deal_id is not None else None,
                })
    return pd.DataFrame(rows, columns=["contact_id", "deal_id"])


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot meetings...")
def load_meetings_for_contacts(contact_ids: list[str]) -> pd.DataFrame:
    """Return meetings associated with the given contact IDs.

    Columns: meeting_id, contact_id, activity_type, outcome, start_time.

    activity_type values seen: "15 min call", "Strategy Call", ...
    outcome values seen: "SCHEDULED", "RESCHEDULED", "COMPLETE - QUALIFIED",
        "COMPLETE - FUTURE", "COMPLETE - DISQUALIFIED", "COMPLETE - BAMFAM", "NO_SHOW", ...
    """
    cols = ["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]
    if not contact_ids:
        return pd.DataFrame(columns=cols)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Get meeting IDs per contact via association API
    contact_to_meetings: dict[str, list[str]] = {}
    for i in range(0, len(contact_ids), 100):
        batch = contact_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v4/associations/contacts/meetings/batch/read",
            headers=headers,
            json={"inputs": [{"id": cid} for cid in batch]},
            timeout=60,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            cid = str(item.get("from", {}).get("id"))
            for t in item.get("to", []):
                mid = str(t.get("toObjectId"))
                contact_to_meetings.setdefault(cid, []).append(mid)

    if not contact_to_meetings:
        return pd.DataFrame(columns=cols)

    # 2. Batch-fetch meeting properties
    all_meeting_ids = list({mid for mids in contact_to_meetings.values() for mid in mids})
    meetings_props: dict[str, dict] = {}
    for i in range(0, len(all_meeting_ids), 100):
        batch = all_meeting_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v3/objects/meetings/batch/read",
            headers=headers,
            json={
                "properties": [
                    "hs_meeting_title", "hs_meeting_outcome",
                    "hs_activity_type", "hs_meeting_start_time",
                ],
                "inputs": [{"id": mid} for mid in batch],
            },
            timeout=60,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            mid = str(item.get("id"))
            p = item.get("properties", {}) or {}
            meetings_props[mid] = {
                "activity_type": p.get("hs_activity_type") or "",
                "outcome": (p.get("hs_meeting_outcome") or "").upper(),
                "start_time": p.get("hs_meeting_start_time") or "",
            }

    # 3. Flatten
    rows = []
    for cid, mids in contact_to_meetings.items():
        for mid in mids:
            m = meetings_props.get(mid, {})
            rows.append({
                "meeting_id": mid,
                "contact_id": cid,
                "activity_type": m.get("activity_type", ""),
                "outcome": m.get("outcome", ""),
                "start_time": m.get("start_time", ""),
            })
    return pd.DataFrame(rows, columns=cols)
