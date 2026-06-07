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
    whose most-recent conversion event fell in the window.

    Filters on `recent_conversion_date` rather than `typeform_submission_date`
    because the latter was bulk-overwritten for 1,602 contacts on 2026-04-07
    14:19 UTC. recent_conversion_date tracks REAL form/meeting submission
    events and survived the bulk edit.

    Columns: hs_id, name, email, created, typeform_asset_download,
    typeform_submission_date, recent_conversion_date,
    recent_conversion_event, sdr_owner, bds, sme, utm_source, ...
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
                {"propertyName": cfg.HS_PROP_RECENT_CONVERSION_DATE,
                 "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "createdate",
            cfg.HS_PROP_TYPEFORM_ASSET, cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE,
            cfg.HS_PROP_RECENT_CONVERSION_DATE, cfg.HS_PROP_RECENT_CONVERSION_EVENT,
            cfg.HS_PROP_SDR_OWNER, cfg.HS_PROP_BDS, cfg.HS_PROP_SME,
            cfg.HS_PROP_UTM_SOURCE,
            cfg.HS_PROP_15MIN_CALL_DATE, cfg.HS_PROP_LIFECYCLE_STAGE,
            "phone", "mobilephone",
            cfg.HS_PROP_WEBINAR_REG_DATE, cfg.HS_PROP_WEBINAR_COMPLETED_DATE,
            cfg.HS_PROP_PT_WEBINAR_REG_DATE, cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE,
            cfg.HS_PROP_CONTRACT_TIER, cfg.HS_PROP_SEND_CONTRACT_OPTIONS,
            cfg.HS_PROP_RECENT_CONVERSION_DATE, cfg.HS_PROP_RECENT_CONVERSION_EVENT,
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
        _em = (p.get("email") or "").strip().lower()
        if _em in cfg.MARKETING_EXCLUDED_EMAILS:
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
            "phone": p.get("phone"),
            "mobilephone": p.get("mobilephone"),
            "webinar_registration_date": p.get(cfg.HS_PROP_WEBINAR_REG_DATE),
            "webinar_completed_date": p.get(cfg.HS_PROP_WEBINAR_COMPLETED_DATE),
            "pt_webinar_registration_date": p.get(cfg.HS_PROP_PT_WEBINAR_REG_DATE),
            "pt_webinar_completed_date": p.get(cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE),
            "contract_tier": p.get(cfg.HS_PROP_CONTRACT_TIER),
            "send_contract_options": p.get(cfg.HS_PROP_SEND_CONTRACT_OPTIONS),
            "recent_conversion_date": p.get(cfg.HS_PROP_RECENT_CONVERSION_DATE),
            "recent_conversion_event": p.get(cfg.HS_PROP_RECENT_CONVERSION_EVENT),
        })
    return pd.DataFrame(rows, columns=[
        "hs_id", "name", "email", "created",
        "typeform_asset_download", "typeform_submission_date",
        "sdr_owner", "bds", "sme", "utm_source",
        "fifteen_min_call_date", "lifecycle_stage",
        "phone", "mobilephone",
        "webinar_registration_date", "webinar_completed_date",
        "pt_webinar_registration_date", "pt_webinar_completed_date",
        "contract_tier", "send_contract_options",
        "recent_conversion_date", "recent_conversion_event",
    ])


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot deals...")
def load_deals_in_window(
    start: date,
    end: date,
    data_floor_days_back: int = 90,
) -> pd.DataFrame:
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
                       "createdate", "closedate",
                       *cfg.STAGE_ENTRY_DATE_PROPERTIES.values()],
        "limit": 100,
    }
    results = _hs_search(token, "deals", body)
    from dashboard.config import data_floor_date
    floor_ts = datetime.combine(
        data_floor_date(data_floor_days_back),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    rows = []
    for r in results:
        p = r.get("properties", {})
        deal_id = r.get("id")
        closedate_str = p.get("closedate") or ""
        # Filter out deals closed before the data floor.
        if closedate_str:
            try:
                close_dt = datetime.fromisoformat(closedate_str.replace("Z", "+00:00"))
                if close_dt < floor_ts:
                    continue
            except (ValueError, TypeError):
                pass
        # Effective close date for STAGES_CLOSED_WON_NO_CLOSEDATE: stage-entry
        # timestamp. Falls back to createdate when stage-entry is missing.
        stage_id = p.get("dealstage") or ""
        stage_entry = None
        prop = cfg.STAGE_ENTRY_DATE_PROPERTIES.get(stage_id)
        if prop:
            stage_entry = p.get(prop)
        rows.append({
            "deal_id": str(deal_id) if deal_id is not None else None,
            "dealname": p.get("dealname"),
            "amount": float(p.get("amount") or 0),
            "dealstage": stage_id,
            "pipeline": p.get("pipeline"),
            "createdate": p.get("createdate"),
            "closedate": p.get("closedate"),
            "stage_entry_date": stage_entry,
        })
    return pd.DataFrame(rows, columns=[
        "deal_id", "dealname", "amount", "dealstage",
        "pipeline", "createdate", "closedate", "stage_entry_date",
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


@st.cache_data(ttl=900, show_spinner="Pulling deal -> contact associations...")
def load_deal_contacts(deal_ids: list[str]) -> pd.DataFrame:
    """For each deal id, return its associated contact ids (reverse direction
    of load_contact_deals). Lets the SALES tab pull every contact tied to a
    deal in the window — including contacts who submitted their typeform
    weeks/months ago and whose 15-min/Strategy/Close is happening now.

    Columns: deal_id, contact_id.
    """
    if not deal_ids:
        return pd.DataFrame(columns=["deal_id", "contact_id"])

    token = st.secrets["HUBSPOT_TOKEN"]
    rows = []
    for i in range(0, len(deal_ids), 100):
        batch = deal_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v4/associations/deals/contacts/batch/read",
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": [{"id": did} for did in batch]},
            timeout=60,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            did = item.get("from", {}).get("id")
            for t in item.get("to", []):
                cid = t.get("toObjectId")
                rows.append({
                    "deal_id": str(did) if did is not None else None,
                    "contact_id": str(cid) if cid is not None else None,
                })
    return pd.DataFrame(rows, columns=["deal_id", "contact_id"])


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot meetings...")
def load_meetings_for_contacts(
    contact_ids: list[str],
    data_floor_days_back: int = 90,
) -> pd.DataFrame:
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
    from dashboard.config import data_floor_date
    floor_ts = datetime.combine(
        data_floor_date(data_floor_days_back),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    rows = []
    for cid, mids in contact_to_meetings.items():
        for mid in mids:
            m = meetings_props.get(mid, {})
            start_str = m.get("start_time") or ""
            # Filter out meetings before the data floor.
            if start_str:
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    if start_dt < floor_ts:
                        continue
                except (ValueError, TypeError):
                    pass  # Unparseable timestamp — keep the row (rare)
            rows.append({
                "meeting_id": mid,
                "contact_id": cid,
                "activity_type": m.get("activity_type", ""),
                "outcome": m.get("outcome", ""),
                "start_time": start_str,
            })
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=900, show_spinner="Pulling meetings in window...")
def load_meetings_in_window(start: date, end: date) -> pd.DataFrame:
    """Return every meeting whose hs_meeting_start_time falls in [start, end].

    Uses meetings/search directly (no per-contact filter) so we can pull a
    full window's worth of meetings without first enumerating contacts.
    Then fetches the associated contact_id for each meeting in batch.

    Columns: meeting_id, contact_id, activity_type, outcome, start_time.
    Multiple contacts on one meeting → multiple rows (first contact wins
    when None — defensive only).
    """
    cols = ["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]
    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    start_ms = int(datetime.combine(start, datetime.min.time(),
                                      tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end, datetime.max.time(),
                                    tzinfo=timezone.utc).timestamp() * 1000)
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "hs_meeting_start_time", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": ["hs_activity_type", "hs_meeting_outcome",
                       "hs_meeting_start_time", "hs_meeting_title"],
        "limit": 100,
    }
    meetings = []
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(f"{HS_API}/crm/v3/objects/meetings/search",
                          headers=headers, json=b, timeout=60)
        r.raise_for_status()
        data = r.json()
        for o in data.get("results", []):
            p = o.get("properties") or {}
            meetings.append({
                "meeting_id": o["id"],
                "activity_type": p.get("hs_activity_type") or "",
                "outcome": p.get("hs_meeting_outcome") or "",
                "start_time": p.get("hs_meeting_start_time"),
                "title": p.get("hs_meeting_title") or "",
            })
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after or len(meetings) >= 20000:
            break

    if not meetings:
        return pd.DataFrame(columns=cols)

    # Associations: meeting -> contact
    mid_to_cid: dict[str, str] = {}
    mids = [m["meeting_id"] for m in meetings]
    for i in range(0, len(mids), 100):
        batch = mids[i:i + 100]
        r = requests.post(
            f"{HS_API}/crm/v4/associations/meetings/contacts/batch/read",
            headers=headers,
            json={"inputs": [{"id": mid} for mid in batch]},
            timeout=60,
        )
        if r.status_code >= 400:
            continue
        for item in r.json().get("results", []):
            mid = str(item.get("from", {}).get("id"))
            cids = [t.get("toObjectId") for t in item.get("to", [])]
            if cids:
                mid_to_cid[mid] = str(cids[0])

    # Final rows — title falls back to activity_type matching when needed
    rows = []
    for m in meetings:
        cid = mid_to_cid.get(m["meeting_id"])
        if not cid:
            continue  # drop meetings without a contact association
        t = (m["activity_type"] or "").lower()
        title = (m["title"] or "").lower()
        # Promote title-only matches into activity_type so downstream "15 min"
        # / "strategy" substring checks work.
        if "15 min" not in t and ("15 min" in title or "15-min" in title):
            m["activity_type"] = "15 min call"
        elif "strategy" not in t and "strategy" in title:
            m["activity_type"] = "Strategy Call"
        rows.append({
            "meeting_id": m["meeting_id"],
            "contact_id": cid,
            "activity_type": m["activity_type"],
            "outcome": m["outcome"],
            "start_time": m["start_time"],
        })
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=900, show_spinner="Pulling contact asset details...")
def load_contacts_by_ids(contact_ids: list[str]) -> pd.DataFrame:
    """Batch-fetch contact properties by HubSpot contact ID.

    Used for closed-deal attribution: when a deal closes but the contact
    submitted their typeform outside the current dashboard window, we still
    need the contact's typeform_asset_download to attribute revenue to the
    right group.

    Returns DataFrame with the same shape as load_marketing_contacts.
    """
    cols = [
        "hs_id", "name", "email", "created",
        "typeform_asset_download", "typeform_submission_date",
        "sdr_owner", "bds", "sme", "utm_source",
        "fifteen_min_call_date", "lifecycle_stage",
        "phone", "mobilephone",
        "webinar_registration_date", "webinar_completed_date",
        "pt_webinar_registration_date", "pt_webinar_completed_date",
        "contract_tier", "send_contract_options",
        "recent_conversion_date", "recent_conversion_event",
    ]
    if not contact_ids:
        return pd.DataFrame(columns=cols)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    rows = []
    for i in range(0, len(contact_ids), 100):
        batch = contact_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v3/objects/contacts/batch/read",
            headers=headers,
            json={
                "properties": [
                    "firstname", "lastname", "email", "createdate",
                    cfg.HS_PROP_TYPEFORM_ASSET, cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE,
                    cfg.HS_PROP_SDR_OWNER, cfg.HS_PROP_BDS, cfg.HS_PROP_SME,
                    cfg.HS_PROP_UTM_SOURCE,
                    cfg.HS_PROP_15MIN_CALL_DATE, cfg.HS_PROP_LIFECYCLE_STAGE,
                    "phone", "mobilephone",
                    cfg.HS_PROP_WEBINAR_REG_DATE, cfg.HS_PROP_WEBINAR_COMPLETED_DATE,
                    cfg.HS_PROP_PT_WEBINAR_REG_DATE, cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE,
                    cfg.HS_PROP_CONTRACT_TIER, cfg.HS_PROP_SEND_CONTRACT_OPTIONS,
                    cfg.HS_PROP_RECENT_CONVERSION_DATE, cfg.HS_PROP_RECENT_CONVERSION_EVENT,
                ],
                "inputs": [{"id": cid} for cid in batch],
            },
            timeout=60,
        )
        if r.status_code >= 400:
            continue  # Batch failure: skip rather than crash
        for c in r.json().get("results", []):
            p = c.get("properties") or {}
            fn = (p.get("firstname") or "").strip().lower()
            ln = (p.get("lastname") or "").strip().lower()
            if fn == "test" or ln == "test":
                continue  # Same TEST-contact filter as load_marketing_contacts
            em = (p.get("email") or "").strip().lower()
            if em in cfg.MARKETING_EXCLUDED_EMAILS:
                continue
            hs_id = c.get("id")
            rows.append({
                "hs_id": str(hs_id) if hs_id is not None else None,
                "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "email": p.get("email"),
                "created": p.get("createdate"),
                "typeform_asset_download": p.get(cfg.HS_PROP_TYPEFORM_ASSET),
                "typeform_submission_date": p.get(cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE),
                "sdr_owner": p.get(cfg.HS_PROP_SDR_OWNER),
                "bds": p.get(cfg.HS_PROP_BDS),
                "sme": p.get(cfg.HS_PROP_SME),
                "utm_source": p.get(cfg.HS_PROP_UTM_SOURCE),
                "fifteen_min_call_date": p.get(cfg.HS_PROP_15MIN_CALL_DATE),
                "lifecycle_stage": p.get(cfg.HS_PROP_LIFECYCLE_STAGE),
                "phone": p.get("phone"),
                "mobilephone": p.get("mobilephone"),
                "webinar_registration_date": p.get(cfg.HS_PROP_WEBINAR_REG_DATE),
                "webinar_completed_date": p.get(cfg.HS_PROP_WEBINAR_COMPLETED_DATE),
                "pt_webinar_registration_date": p.get(cfg.HS_PROP_PT_WEBINAR_REG_DATE),
                "pt_webinar_completed_date": p.get(cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE),
                "contract_tier": p.get(cfg.HS_PROP_CONTRACT_TIER),
            "send_contract_options": p.get(cfg.HS_PROP_SEND_CONTRACT_OPTIONS),
            "recent_conversion_date": p.get(cfg.HS_PROP_RECENT_CONVERSION_DATE),
            "recent_conversion_event": p.get(cfg.HS_PROP_RECENT_CONVERSION_EVENT),
            })

    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=900, show_spinner="Pulling YTD closed deals...")
def load_closed_deals_ytd(
    closed_won_stages: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pull all deals closed-won YTD (Jan 1 of current year -> today), plus their
    associated contacts. Always uses a 200-day floor to cover the full YTD
    range regardless of the user's data-lookback selector.

    Returns: (deals_df, contact_deals_df, contacts_df) -- same shapes as the
    other loaders.

    The deals_df is filtered to only closed-won stages in `closed_won_stages`
    AND closedate >= Jan 1 of current year.
    """
    from datetime import date as _date

    deal_cols = ["deal_id", "dealname", "amount", "dealstage",
                 "pipeline", "createdate", "closedate", "stage_entry_date"]
    assoc_cols = ["contact_id", "deal_id"]
    contact_cols = [
        "hs_id", "name", "email", "created",
        "typeform_asset_download", "typeform_submission_date",
        "sdr_owner", "bds", "sme", "utm_source",
        "fifteen_min_call_date", "lifecycle_stage",
        "phone", "mobilephone",
        "webinar_registration_date", "webinar_completed_date",
        "pt_webinar_registration_date", "pt_webinar_completed_date",
    ]

    from datetime import date as _date, datetime as _datetime
    from datetime import timezone as _timezone
    year_start = _date(_date.today().year, 1, 1)
    today = _date.today()
    start_ms = int(_datetime.combine(year_start, _datetime.min.time(),
                                       tzinfo=_timezone.utc).timestamp() * 1000)
    end_ms = int(_datetime.combine(today, _datetime.max.time(),
                                     tzinfo=_timezone.utc).timestamp() * 1000)

    closed_set = list(closed_won_stages)
    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    # Import the stages-without-closedate set + stage-entry props
    try:
        from dashboard.config import (
            STAGES_CLOSED_WON_NO_CLOSEDATE,
            STAGE_ENTRY_DATE_PROPERTIES,
        )
        no_closedate_stages = list(STAGES_CLOSED_WON_NO_CLOSEDATE)
        stage_entry_props = dict(STAGE_ENTRY_DATE_PROPERTIES)
    except ImportError:
        no_closedate_stages = []
        stage_entry_props = {}

    # closedate_stages = those WITH a closedate (filter by closedate)
    closedate_stages = [s for s in closed_set if s not in set(no_closedate_stages)]

    filter_groups = []
    if closedate_stages:
        filter_groups.append({
            "filters": [
                {"propertyName": "dealstage", "operator": "IN",
                 "values": closedate_stages},
                {"propertyName": "closedate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        })
    # For each no-closedate stage, filter by its stage-entry date — that's
    # when the deal actually became a customer in that stage.
    for stage_id in no_closedate_stages:
        prop = stage_entry_props.get(stage_id)
        if not prop:
            continue
        filter_groups.append({
            "filters": [
                {"propertyName": "dealstage", "operator": "EQ", "value": stage_id},
                {"propertyName": prop, "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        })

    body = {
        "filterGroups": filter_groups,
        "properties": ["dealname", "amount", "dealstage", "pipeline",
                       "createdate", "closedate",
                       *stage_entry_props.values()],
        "limit": 100,
    }
    deal_rows = []
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(
            f"{HS_API}/crm/v3/objects/deals/search",
            headers=headers, json=b, timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for d in data.get("results", []):
            p = d.get("properties") or {}
            did = d.get("id")
            stage_id = p.get("dealstage") or ""
            stage_entry = None
            prop = stage_entry_props.get(stage_id)
            if prop:
                stage_entry = p.get(prop)
            deal_rows.append({
                "deal_id": str(did) if did is not None else None,
                "dealname": p.get("dealname"),
                "amount": float(p.get("amount") or 0),
                "dealstage": stage_id,
                "pipeline": p.get("pipeline"),
                "createdate": p.get("createdate"),
                "closedate": p.get("closedate"),
                "stage_entry_date": stage_entry,
            })
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after or len(deal_rows) >= 10000:
            break

    deals_ytd = pd.DataFrame(deal_rows, columns=deal_cols)

    if deals_ytd.empty:
        return (deals_ytd,
                pd.DataFrame(columns=assoc_cols),
                pd.DataFrame(columns=contact_cols))

    # 3. Get associated contact IDs for these deals
    # -- here we have deal_ids, so we use a deal->contact lookup directly.
    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    deal_ids = deals_ytd["deal_id"].tolist()

    assoc_rows = []
    for i in range(0, len(deal_ids), 100):
        batch = deal_ids[i:i+100]
        r = requests.post(
            f"{HS_API}/crm/v4/associations/deals/contacts/batch/read",
            headers=headers,
            json={"inputs": [{"id": did} for did in batch]},
            timeout=60,
        )
        if r.status_code >= 400:
            continue
        for item in r.json().get("results", []):
            deal_id = str(item.get("from", {}).get("id"))
            for t in item.get("to", []):
                cid = t.get("toObjectId")
                if cid is not None:
                    assoc_rows.append({"contact_id": str(cid), "deal_id": deal_id})

    contact_deals_df = pd.DataFrame(assoc_rows, columns=assoc_cols)

    # 4. Pull contact details for those contact_ids
    contact_ids = list({r["contact_id"] for r in assoc_rows})
    contacts_df = load_contacts_by_ids(contact_ids) if contact_ids \
        else pd.DataFrame(columns=contact_cols)

    return deals_ytd, contact_deals_df, contacts_df


@st.cache_data(ttl=900, show_spinner="Pulling TheraRay contacts...")
def load_contacts_by_utm_campaigns(campaign_ids: tuple[str, ...],
                                    start: date,
                                    end: date) -> pd.DataFrame:
    """Pull HubSpot contacts whose utm_campaign matches any of the given FB
    campaign IDs AND createdate is in window.

    Used for TheraRay-style leads that don't fill a typeform but ARE
    identifiable via the FB campaign ID their utm_campaign carries.

    Returns the same DataFrame shape as load_marketing_contacts.
    """
    cols = [
        "hs_id", "name", "email", "created",
        "typeform_asset_download", "typeform_submission_date",
        "sdr_owner", "bds", "sme", "utm_source",
        "fifteen_min_call_date", "lifecycle_stage",
        "phone", "mobilephone",
        "webinar_registration_date", "webinar_completed_date",
        "pt_webinar_registration_date", "pt_webinar_completed_date",
        "contract_tier", "send_contract_options",
        "recent_conversion_date", "recent_conversion_event",
    ]
    if not campaign_ids:
        return pd.DataFrame(columns=cols)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                     tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end, datetime.max.time(),
                                   tzinfo=timezone.utc).timestamp() * 1000)

    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "utm_campaign", "operator": "IN",
                 "values": list(campaign_ids)},
                {"propertyName": "createdate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "createdate",
            cfg.HS_PROP_TYPEFORM_ASSET, cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE,
            cfg.HS_PROP_SDR_OWNER, cfg.HS_PROP_BDS, cfg.HS_PROP_SME,
            cfg.HS_PROP_UTM_SOURCE,
            cfg.HS_PROP_15MIN_CALL_DATE, cfg.HS_PROP_LIFECYCLE_STAGE,
            "phone", "mobilephone",
            cfg.HS_PROP_WEBINAR_REG_DATE, cfg.HS_PROP_WEBINAR_COMPLETED_DATE,
            cfg.HS_PROP_PT_WEBINAR_REG_DATE, cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE,
            cfg.HS_PROP_CONTRACT_TIER, cfg.HS_PROP_SEND_CONTRACT_OPTIONS,
            cfg.HS_PROP_RECENT_CONVERSION_DATE, cfg.HS_PROP_RECENT_CONVERSION_EVENT,
        ],
        "limit": 100,
    }
    results = _hs_search(token, "contacts", body)
    rows = []
    for r in results:
        p = r.get("properties", {})
        fn = (p.get("firstname") or "").strip().lower()
        ln = (p.get("lastname") or "").strip().lower()
        if fn == "test" or ln == "test":
            continue
        em = (p.get("email") or "").strip().lower()
        if em in cfg.MARKETING_EXCLUDED_EMAILS:
            continue
        hs_id = r.get("id")
        rows.append({
            "hs_id": str(hs_id) if hs_id is not None else None,
            "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "email": p.get("email"),
            "created": p.get("createdate"),
            "typeform_asset_download": p.get(cfg.HS_PROP_TYPEFORM_ASSET),
            "typeform_submission_date": p.get(cfg.HS_PROP_TYPEFORM_SUBMISSION_DATE),
            "sdr_owner": p.get(cfg.HS_PROP_SDR_OWNER),
            "bds": p.get(cfg.HS_PROP_BDS),
            "sme": p.get(cfg.HS_PROP_SME),
            "utm_source": p.get(cfg.HS_PROP_UTM_SOURCE),
            "fifteen_min_call_date": p.get(cfg.HS_PROP_15MIN_CALL_DATE),
            "lifecycle_stage": p.get(cfg.HS_PROP_LIFECYCLE_STAGE),
            "phone": p.get("phone"),
            "mobilephone": p.get("mobilephone"),
            "webinar_registration_date": p.get(cfg.HS_PROP_WEBINAR_REG_DATE),
            "webinar_completed_date": p.get(cfg.HS_PROP_WEBINAR_COMPLETED_DATE),
            "pt_webinar_registration_date": p.get(cfg.HS_PROP_PT_WEBINAR_REG_DATE),
            "pt_webinar_completed_date": p.get(cfg.HS_PROP_PT_WEBINAR_COMPLETED_DATE),
            "contract_tier": p.get(cfg.HS_PROP_CONTRACT_TIER),
            "send_contract_options": p.get(cfg.HS_PROP_SEND_CONTRACT_OPTIONS),
            "recent_conversion_date": p.get(cfg.HS_PROP_RECENT_CONVERSION_DATE),
            "recent_conversion_event": p.get(cfg.HS_PROP_RECENT_CONVERSION_EVENT),
        })
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=900, show_spinner="Pulling list members...")
def load_list_memberships(list_id: str) -> pd.DataFrame:
    """Return DataFrame of (contact_id, membership_timestamp) for the given
    HubSpot list. `membership_timestamp` is when the contact joined the list
    (NOT the contact's createdate)."""
    cols = ["contact_id", "membership_timestamp"]
    if not list_id:
        return pd.DataFrame(columns=cols)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    rows: list[dict] = []
    after = None
    while True:
        params = {"limit": 250}
        if after:
            params["after"] = after
        r = requests.get(
            f"{HS_API}/crm/v3/lists/{list_id}/memberships",
            headers=headers, params=params, timeout=60,
        )
        if r.status_code >= 400:
            break
        data = r.json()
        for m in data.get("results", []):
            rid = m.get("recordId")
            ts = m.get("membershipTimestamp")
            if rid is not None:
                rows.append({"contact_id": str(rid),
                              "membership_timestamp": ts})
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break

    return pd.DataFrame(rows, columns=cols)


# Backward-compatible alias for any callers that only need IDs
@st.cache_data(ttl=900, show_spinner="Pulling list members...")
def load_list_membership_contact_ids(list_id: str) -> list[str]:
    df = load_list_memberships(list_id)
    return df["contact_id"].tolist() if not df.empty else []


@st.cache_data(ttl=900, show_spinner="Pulling closed deals in window...")
def load_closed_deals_in_window(
    start: date,
    end: date,
    closed_won_stages: tuple[str, ...],
    no_closedate_stages: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Pull deals closed-won where:
      - dealstage in closed_won_stages AND closedate BETWEEN start..end, OR
      - dealstage in no_closedate_stages AND createdate BETWEEN start..end

    Used by the METRICS tab to count closed deals per week accurately --
    bypasses the hs_lastmodifieddate filter that misses deals closed
    earlier but not touched since.
    """
    from datetime import date as _date, datetime as _datetime
    from datetime import timezone as _timezone

    deal_cols = ["deal_id", "dealname", "amount", "dealstage", "pipeline",
                 "createdate", "closedate", "stage_entry_date"]
    start_ms = int(_datetime.combine(start, _datetime.min.time(),
                                       tzinfo=_timezone.utc).timestamp() * 1000)
    end_ms = int(_datetime.combine(end, _datetime.max.time(),
                                     tzinfo=_timezone.utc).timestamp() * 1000)

    token = st.secrets["HUBSPOT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    closed_set = list(closed_won_stages)
    no_close_list = [s for s in no_closedate_stages if s in set(closed_set)]
    closedate_only = [s for s in closed_set if s not in set(no_close_list)]

    stage_entry_props = dict(cfg.STAGE_ENTRY_DATE_PROPERTIES)

    filter_groups = []
    if closedate_only:
        filter_groups.append({
            "filters": [
                {"propertyName": "dealstage", "operator": "IN",
                 "values": closedate_only},
                {"propertyName": "closedate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        })
    # Per-stage filter using its stage-entry date (when the deal entered the
    # no-closedate stage = effective close date for DIY/90-Day).
    for stage_id in no_close_list:
        prop = stage_entry_props.get(stage_id)
        if not prop:
            continue
        filter_groups.append({
            "filters": [
                {"propertyName": "dealstage", "operator": "EQ", "value": stage_id},
                {"propertyName": prop, "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        })

    if not filter_groups:
        return pd.DataFrame(columns=deal_cols)

    body = {
        "filterGroups": filter_groups,
        "properties": ["dealname", "amount", "dealstage", "pipeline",
                       "createdate", "closedate",
                       *stage_entry_props.values()],
        "limit": 100,
    }
    deal_rows = []
    after = None
    while True:
        b = dict(body)
        if after:
            b["after"] = after
        r = requests.post(
            f"{HS_API}/crm/v3/objects/deals/search",
            headers=headers, json=b, timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for d in data.get("results", []):
            p = d.get("properties") or {}
            did = d.get("id")
            stage_id = p.get("dealstage") or ""
            stage_entry = None
            prop = stage_entry_props.get(stage_id)
            if prop:
                stage_entry = p.get(prop)
            deal_rows.append({
                "deal_id": str(did) if did is not None else None,
                "dealname": p.get("dealname"),
                "amount": float(p.get("amount") or 0),
                "dealstage": stage_id,
                "pipeline": p.get("pipeline"),
                "createdate": p.get("createdate"),
                "closedate": p.get("closedate"),
                "stage_entry_date": stage_entry,
            })
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after or len(deal_rows) >= 10000:
            break

    return pd.DataFrame(deal_rows, columns=deal_cols)
