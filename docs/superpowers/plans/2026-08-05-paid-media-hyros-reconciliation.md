# Paid Media FB x Hyros Reconciliation Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a chat-delivered paid media report that cross-references Facebook Ads Manager against Hyros and HubSpot at campaign, ad set, and ad level across 14/7/3-day windows, yielding a tiered cut list keyed on cost per booked call plus a diagnosis of the FB lead over-report.

**Architecture:** Three read-only probe scripts pull raw data (FB Marketing API, Hyros API, HubSpot CRM) and dump JSON to the session scratchpad. One new pure-Python module, `dashboard/data/paid_media.py`, holds all reconciliation, join, and tiering logic with no I/O so it is unit-testable. The report itself is assembled by the agent in chat from the probe JSON plus a live browser audit of the funnel pages. No Streamlit UI is built.

**Tech Stack:** Python 3.13, pandas, requests, pytest, Streamlit only as a secrets reader (`st.secrets`), Claude Browser tools for the funnel audit.

## Global Constraints

- Repo root: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`. Working branch: `feature/cmo-dashboard`. Push here, never `main`.
- **All probes are strictly read-only.** No POST, PATCH, PUT, or DELETE against FB, Hyros, or HubSpot. GET only.
- Raw probe output goes to the scratchpad, never committed to the repo: `C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad`
- Probes run from repo root via the **Bash tool**: `python dashboard/probes/<name>.py`. Do not run probes through the context-mode sandbox: its `python` is a Windows stub.
- Existing loaders are wrapped in `@st.cache_data`. Unwrap them in probes with `def W(fn): return getattr(fn, "__wrapped__", fn)`, matching `dashboard/probes/quarterly_funnel_probe.py`.
- Target pandas is **< 2.1** (Streamlit Cloud floor). No pandas 2.1+ only APIs.
- New pure logic goes in `dashboard/data/paid_media.py`. Do **not** add to `dashboard/data/reconcile.py` (already 3,240 lines).
- Pure functions in `paid_media.py` take config values as **parameters, not imports**, matching the existing `reconcile.py` convention.
- Tests: `python -m pytest dashboard/tests -q`. Full suite must stay green (was 97 passing).
- All report prose and code comments use **standard hyphens. No em dashes.**
- Secrets already present in `.streamlit/secrets.toml`: `FB_ADS_TOKEN`, `FB_AD_ACCOUNT_ID`, `HYROS_API_KEY`, `HUBSPOT_TOKEN`.

### Fixed date windows (all tasks use these exact values)

| Name | Start | End |
|---|---|---|
| `w14` | 2026-07-22 | 2026-08-04 |
| `w7` | 2026-07-29 | 2026-08-04 |
| `w3` | 2026-08-02 | 2026-08-04 |
| `checksum` | 2026-07-21 | 2026-08-03 |

### Accuracy gate (from Kurt's Ads Manager screenshots)

| Check | Expected |
|---|---|
| `checksum` window total spend | $14,846.77 |
| `checksum` Hyros calls / leads / cost per lead | 63 / 73 / $203.38 |
| `w7` total spend | $6,890.57 |
| `w7` Hyros calls / leads | 31 / 29 |

## File Structure

| File | Responsibility |
|---|---|
| `dashboard/probes/paid_media_fb_probe.py` (create) | All FB Marketing API I/O: 9 insights pulls (3 windows x 3 levels) plus one entity pull for delivery status and creative destination URLs. Writes `fb_<window>_<level>.json` and `fb_entities.json`. |
| `dashboard/probes/paid_media_hyros_probe.py` (create) | All Hyros API I/O: `/leads` per window retaining full source objects, plus endpoint discovery for calls and revenue. Writes `hyros_<window>.json` and `hyros_endpoints.json`. |
| `dashboard/probes/paid_media_hubspot_probe.py` (create) | All HubSpot I/O for this report: email-to-contact lookup for Hyros lead emails, booked calls per window, marketing contacts per window. Writes `hubspot_<window>.json`. |
| `dashboard/data/paid_media.py` (create) | Pure logic, zero I/O: derived FB metrics, three-source lead reconciliation, Hyros-to-HubSpot booked call join, baseline computation, cut-list tiering. |
| `dashboard/tests/test_paid_media.py` (create) | Unit tests for every pure function in `paid_media.py`. |

Probes own I/O and are verified by running them. `paid_media.py` owns judgment and is verified by unit tests. That boundary is why the tiering thresholds can be tested without ever calling an API.

---

### Task 1: FB insights probe, three windows, three levels

**Files:**
- Create: `dashboard/probes/paid_media_fb_probe.py`
- Reference (do not modify): `dashboard/data/fb_loader.py`, `dashboard/probes/quarterly_funnel_probe.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: JSON files in the scratchpad named `fb_w14_campaign.json`, `fb_w14_adset.json`, `fb_w14_ad.json`, and the same for `w7`, `w3`, `checksum`, plus `fb_entities.json`. Each insights file is a JSON list of raw FB row dicts. `fb_entities.json` is a JSON list of dicts with keys `ad_id`, `ad_name`, `adset_id`, `campaign_id`, `effective_status`, `adset_effective_status`, `campaign_effective_status`, `link_url`, `body`, `title`, `thumbnail_url`.

- [ ] **Step 1: Create the probe with window/level constants and the insights field list**

`effective_status` is deliberately absent from the insights fields below. It is an object field on the ad/adset/campaign node, not an insights metric, and including it in an insights request returns an error. It is fetched separately in Step 3.

```python
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
    "video_play_actions", "video_3_sec_watched_actions",
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
```

- [ ] **Step 2: Add the paginated GET helper**

FB paginates insights. Without following `paging.next` the ad-level pull silently truncates, which would quietly drop ads from the cut list.

```python
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
```

The `filtering` clause drops the hundreds of zero-spend campaigns in the account (511 campaigns total, only a handful spent in these windows). This keeps the payload small without losing anything that could be judged.

- [ ] **Step 3: Add the entity pull for delivery status and creative destination URLs**

```python
def pull_entities() -> list[dict]:
    """Ad objects with delivery status and creative destination URL.

    The destination link lives in one of two places depending on how the ad
    was built: object_story_spec.link_data.link for a single creative, or
    asset_feed_spec.link_urls[].website_url for a Flexible/dynamic creative.
    Both are checked.
    """
    params = {
        "fields": (
            "id,name,effective_status,"
            "adset{id,name,effective_status},"
            "campaign{id,name,effective_status},"
            "creative{id,body,title,thumbnail_url,link_url,"
            "object_story_spec,asset_feed_spec}"
        ),
        "access_token": TOKEN,
        "limit": 100,
    }
    raw = _get_all(f"{FB_API}/act_{ACCT}/ads", params)

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
```

- [ ] **Step 4: Add the main block that writes all ten JSON files and prints the checksum**

```python
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for wname, (start, end) in WINDOWS.items():
        for level in LEVELS:
            rows = pull_insights(level, start, end)
            path = OUT / f"fb_{wname}_{level}.json"
            path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
            spend = sum(float(r.get("spend", 0)) for r in rows)
            print(f"{wname:9s} {level:8s} rows={len(rows):4d} spend=${spend:,.2f}")

    ents = pull_entities()
    (OUT / "fb_entities.json").write_text(json.dumps(ents, indent=1), encoding="utf-8")
    active = [e for e in ents if e["effective_status"] == "ACTIVE"]
    print(f"entities: {len(ents)} ads, {len(active)} ACTIVE, "
          f"{sum(1 for e in ents if not e['link_url'])} missing link_url")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the probe and check the accuracy gate**

Run: `python dashboard/probes/paid_media_fb_probe.py`

Expected: ten JSON files written. The printed spend for `checksum` at campaign level must read **$14,846.77** and `w7` at campaign level must read **$6,890.57**. Campaign, adset, and ad level spend must agree with each other to within a cent for the same window, because they are three groupings of identical underlying spend.

If v19.0 returns an API version error, bump `FB_API` to the current supported version and rerun. Do not proceed to Task 2 until the two checksum figures match. If they do not match, the query is wrong: check whether the account timezone shifts the window, and whether the `filtering` clause is excluding a campaign that spent.

- [ ] **Step 6: Commit**

```bash
git add dashboard/probes/paid_media_fb_probe.py
git commit -m "feat(probe): FB insights probe for paid media report (3 windows x 3 levels + entities)"
```

---

### Task 2: Hyros probe, leads with full source objects

**Files:**
- Create: `dashboard/probes/paid_media_hyros_probe.py`
- Reference (do not modify): `dashboard/data/hyros_loader.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `hyros_w14.json`, `hyros_w7.json`, `hyros_w3.json`, `hyros_checksum.json` in the scratchpad. Each is a JSON list of dicts with keys `lead_id`, `email`, `created`, `first_source_name`, `first_source_category`, `last_source_name`, `last_source_category`, `raw_first`, `raw_last`. Also produces `hyros_endpoints.json`, a dict mapping probed endpoint path to HTTP status and a response sample.

The existing `hyros_loader.load_hyros_leads` collapses each source to a single label string, which throws away the ad-level name. This probe keeps the full nested object so attribution can reach ad level.

- [ ] **Step 1: Create the probe with paginated lead fetching**

```python
"""Hyros probe for the paid media reconciliation report.

Unlike dashboard/data/hyros_loader.py, this keeps the FULL firstSource /
lastSource objects rather than collapsing them to one label, so attribution
can be resolved at ad level and not just campaign level.

Read-only. GET requests only.
Run from repo root: python dashboard/probes/paid_media_hyros_probe.py
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

HYROS_API = "https://api.hyros.com/v1/api/v1.0"

OUT = Path(r"C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad")

WINDOWS = {
    "w14": (date(2026, 7, 22), date(2026, 8, 4)),
    "w7": (date(2026, 7, 29), date(2026, 8, 4)),
    "w3": (date(2026, 8, 2), date(2026, 8, 4)),
    "checksum": (date(2026, 7, 21), date(2026, 8, 3)),
}

KEY = st.secrets["HYROS_API_KEY"]


def _get(path: str, params: dict) -> tuple[int, dict]:
    r = requests.get(f"{HYROS_API}{path}", headers={"API-Key": KEY},
                     params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_text": r.text[:600]}


def pull_leads(start: date, end: date) -> list[dict]:
    """Fetch every lead in the window, following Hyros page tokens."""
    rows: list[dict] = []
    params = {
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": 250,
    }
    page = 0
    while True:
        status, payload = _get("/leads", params)
        if status >= 400:
            raise RuntimeError(f"Hyros /leads {status}: {payload}")
        batch = payload.get("result") or payload.get("data") or []
        if not isinstance(batch, list):
            batch = []
        rows.extend(batch)
        token = payload.get("nextPageId") or payload.get("nextPageToken")
        page += 1
        if not token or not batch or page > 80:
            break
        params = dict(params, pageId=token)
        time.sleep(0.3)
    return rows
```

- [ ] **Step 2: Add source flattening that preserves both levels**

```python
def flatten(lead: dict) -> dict:
    """Keep ad-level name AND campaign-level category for both sources."""
    def parts(src):
        if not isinstance(src, dict):
            return (src or None), None
        cat = src.get("category")
        cat_name = cat.get("name") if isinstance(cat, dict) else cat
        return src.get("name"), cat_name

    f_name, f_cat = parts(lead.get("firstSource"))
    l_name, l_cat = parts(lead.get("lastSource"))
    return {
        "lead_id": lead.get("id"),
        "email": (lead.get("email") or "").strip().lower() or None,
        "created": lead.get("createdDate") or lead.get("created"),
        "first_source_name": f_name,
        "first_source_category": f_cat,
        "last_source_name": l_name,
        "last_source_category": l_cat,
        "raw_first": lead.get("firstSource"),
        "raw_last": lead.get("lastSource"),
    }
```

Email is lowercased and stripped here because Task 5 joins Hyros leads to HubSpot contacts on email, and a case mismatch would silently drop the join.

- [ ] **Step 3: Add endpoint discovery for calls and revenue**

The design has an open question: whether the public API exposes the CALLS and COST PER CALL figures the Chrome extension injects into Ads Manager, and why TOTAL REVENUE reads $0.00. This probes for it rather than assuming.

```python
CANDIDATES = ["/calls", "/call", "/orders", "/order", "/sales",
              "/attribution", "/ads", "/campaigns"]


def discover() -> dict:
    """Probe candidate endpoints so we know what Hyros actually exposes."""
    start, end = WINDOWS["w14"]
    found = {}
    for path in CANDIDATES:
        status, payload = _get(path, {
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
            "pageSize": 5,
        })
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        sample = payload.get("result") or payload.get("data") or []
        found[path] = {
            "status": status,
            "top_level_keys": keys,
            "sample": sample[:2] if isinstance(sample, list) else str(sample)[:400],
        }
        print(f"{path:14s} -> {status}")
        time.sleep(0.3)
    return found
```

- [ ] **Step 4: Add the main block**

```python
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for wname, (start, end) in WINDOWS.items():
        raw = pull_leads(start, end)
        rows = [flatten(x) for x in raw]
        (OUT / f"hyros_{wname}.json").write_text(
            json.dumps(rows, indent=1), encoding="utf-8")
        no_email = sum(1 for r in rows if not r["email"])
        unattr = sum(1 for r in rows if not r["first_source_name"])
        print(f"{wname:9s} leads={len(rows):4d} no_email={no_email} "
              f"unattributed={unattr}")

    (OUT / "hyros_endpoints.json").write_text(
        json.dumps(discover(), indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the probe and check the accuracy gate**

Run: `python dashboard/probes/paid_media_hyros_probe.py`

Expected: `checksum` prints **leads=73** and `w7` prints **leads=29**, matching the Hyros extension columns in Kurt's screenshots. Note in the run output which of the candidate endpoints returned HTTP 200, because that decides Task 5: if a calls endpoint exists, booked calls can come from Hyros directly; if every candidate 404s, booked calls are derived from HubSpot meetings.

If lead counts are close but not exact, check timezone handling before changing anything. If they are far off, the window or pagination is wrong.

- [ ] **Step 6: Commit**

```bash
git add dashboard/probes/paid_media_hyros_probe.py
git commit -m "feat(probe): Hyros leads probe retaining full source objects + endpoint discovery"
```

---

### Task 3: HubSpot probe, third lead count and booked calls

**Files:**
- Create: `dashboard/probes/paid_media_hubspot_probe.py`
- Reference (do not modify): `dashboard/data/hubspot_loader.py`, `dashboard/data/reconcile.py` (for `discovery_mask`)

**Interfaces:**
- Consumes: `hyros_w14.json`, `hyros_w7.json`, `hyros_w3.json`, `hyros_checksum.json` from Task 2 (reads the `email` field to build the lookup set).
- Produces: `hubspot_<window>.json` for each of the four windows. Each is a dict with keys `contacts` (list of dicts: `hs_id`, `email`, `created`, `recent_conversion_event`, `utm_source`, `analytics_source`), `meetings` (list of dicts: `meeting_id`, `contact_id`, `activity_type`, `outcome`, `start_time`, `booked_at`), and `email_to_id` (dict mapping lowercased email to HubSpot contact id).

`load_marketing_contacts(start, end)` only returns contacts whose recent conversion falls in the window, so it cannot resolve an arbitrary Hyros lead email. That is why Step 2 adds a dedicated email lookup.

- [ ] **Step 1: Create the probe reusing existing loaders**

```python
"""HubSpot probe for the paid media reconciliation report.

Supplies the third independent lead count (marketing contacts) and the
authoritative booked-call count (meetings), plus an email-to-contact-id map
so Hyros leads can be joined to HubSpot records.

Read-only. GET and CRM search POST only (search is read-only despite POST).
Run from repo root: python dashboard/probes/paid_media_hubspot_probe.py
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

from dashboard.data import hubspot_loader as hl

OUT = Path(r"C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\b68f6f0d-e602-4cb3-ad0b-df9a70eb0f7c\scratchpad")

WINDOWS = {
    "w14": (date(2026, 7, 22), date(2026, 8, 4)),
    "w7": (date(2026, 7, 29), date(2026, 8, 4)),
    "w3": (date(2026, 8, 2), date(2026, 8, 4)),
    "checksum": (date(2026, 7, 21), date(2026, 8, 3)),
}

TOKEN = st.secrets["HUBSPOT_TOKEN"]


def W(fn):
    """Unwrap a @st.cache_data-decorated loader so it runs outside Streamlit."""
    return getattr(fn, "__wrapped__", fn)
```

- [ ] **Step 2: Add batched email-to-contact-id lookup**

HubSpot's search `IN` filter caps at 100 values per request, so emails are chunked.

```python
def lookup_contact_ids(emails: list[str]) -> dict[str, str]:
    """Map lowercased email -> HubSpot contact id. Batches of 100."""
    out: dict[str, str] = {}
    uniq = sorted({e for e in emails if e})
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {"Authorization": f"Bearer {TOKEN}",
               "Content-Type": "application/json"}

    for i in range(0, len(uniq), 100):
        chunk = uniq[i:i + 100]
        body = {
            "filterGroups": [{"filters": [
                {"propertyName": "email", "operator": "IN", "values": chunk}
            ]}],
            "properties": ["email"],
            "limit": 100,
        }
        r = requests.post(url, headers=headers, json=body, timeout=60)
        if r.status_code >= 400:
            print(f"  lookup batch {i} failed {r.status_code}: {r.text[:300]}")
            continue
        for res in r.json().get("results", []):
            em = (res.get("properties", {}).get("email") or "").strip().lower()
            if em:
                out[em] = str(res.get("id"))
        time.sleep(0.2)
    return out
```

- [ ] **Step 3: Add the main block pulling contacts, meetings, and the email map**

```python
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for wname, (start, end) in WINDOWS.items():
        contacts = W(hl.load_marketing_contacts)(start, end)
        meetings = W(hl.load_meetings_in_window)(start, end)

        hyros_path = OUT / f"hyros_{wname}.json"
        hyros_emails = []
        if hyros_path.exists():
            hyros_emails = [r["email"] for r in
                            json.loads(hyros_path.read_text(encoding="utf-8"))]
        else:
            print(f"  WARNING: {hyros_path.name} missing, run Task 2 first")

        email_to_id = lookup_contact_ids(hyros_emails)

        keep_c = ["hs_id", "email", "created", "recent_conversion_event",
                  "utm_source", "analytics_source"]
        keep_m = ["meeting_id", "contact_id", "activity_type", "outcome",
                  "start_time", "booked_at"]

        payload = {
            "contacts": contacts[keep_c].to_dict(orient="records"),
            "meetings": meetings[keep_m].to_dict(orient="records"),
            "email_to_id": email_to_id,
        }
        (OUT / f"hubspot_{wname}.json").write_text(
            json.dumps(payload, indent=1, default=str), encoding="utf-8")
        print(f"{wname:9s} contacts={len(contacts):4d} "
              f"meetings={len(meetings):4d} "
              f"hyros_emails_matched={len(email_to_id)}/{len(set(hyros_emails))}")


if __name__ == "__main__":
    main()
```

If `load_marketing_contacts` or `load_meetings_in_window` returns a frame missing any column in `keep_c` / `keep_m`, that is a loader change since this plan was written. Print `list(contacts.columns)` and reconcile against `dashboard/data/hubspot_loader.py` rather than dropping the column silently.

- [ ] **Step 4: Run the probe and sanity check**

Run: `python dashboard/probes/paid_media_hubspot_probe.py`

Expected: four JSON files written. The `hyros_emails_matched` ratio should be high (most Hyros leads should exist in HubSpot). A low ratio is itself a finding for the report: it means Hyros is recording leads that never reached the CRM. Record the actual ratio, do not treat a low number as a bug to fix here.

- [ ] **Step 5: Commit**

```bash
git add dashboard/probes/paid_media_hubspot_probe.py
git commit -m "feat(probe): HubSpot probe for third lead count, booked calls, email->id map"
```

---

### Task 4: Pure derived FB metrics

**Files:**
- Create: `dashboard/data/paid_media.py`
- Create: `dashboard/tests/test_paid_media.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on plain dicts shaped like FB insights rows).
- Produces: `action_value(actions, action_type) -> float`, `derive_metrics(row) -> dict`, and the module constant `LEAD_ACTION_TYPES: tuple[str, ...]`. Tasks 5, 6, and 7 import from this module.

- [ ] **Step 1: Write the failing tests**

```python
from dashboard.data.paid_media import (
    action_value, derive_metrics, LEAD_ACTION_TYPES,
)


def test_action_value_finds_matching_type():
    actions = [{"action_type": "lead", "value": "7"},
               {"action_type": "landing_page_view", "value": "42"}]
    assert action_value(actions, "lead") == 7.0
    assert action_value(actions, "landing_page_view") == 42.0


def test_action_value_missing_type_is_zero():
    assert action_value([{"action_type": "lead", "value": "3"}], "purchase") == 0.0
    assert action_value(None, "lead") == 0.0
    assert action_value([], "lead") == 0.0


def test_derive_metrics_computes_link_cpc_and_ctr():
    row = {"spend": "100", "impressions": "10000",
           "clicks": "200", "inline_link_clicks": "50", "actions": []}
    m = derive_metrics(row)
    assert m["link_cpc"] == 2.0            # 100 / 50
    assert m["link_ctr"] == 0.005          # 50 / 10000
    assert m["cpm_calc"] == 10.0           # 100 / 10000 * 1000


def test_derive_metrics_cpl_uses_first_available_lead_action():
    row = {"spend": "200", "impressions": "1000", "inline_link_clicks": "10",
           "actions": [{"action_type": "offsite_conversion.fb_pixel_lead",
                        "value": "4"}]}
    m = derive_metrics(row)
    assert m["fb_leads"] == 4.0
    assert m["cpl"] == 50.0


def test_derive_metrics_hook_and_hold_rate():
    row = {"spend": "10", "impressions": "1000", "inline_link_clicks": "1",
           "actions": [],
           "video_3_sec_watched_actions": [{"action_type": "video_view",
                                           "value": "300"}],
           "video_thruplay_watched_actions": [{"action_type": "video_view",
                                              "value": "90"}]}
    m = derive_metrics(row)
    assert m["hook_rate"] == 0.3           # 300 / 1000
    assert m["hold_rate"] == 0.3           # 90 / 300


def test_derive_metrics_zero_denominators_are_none_not_crash():
    row = {"spend": "0", "impressions": "0", "inline_link_clicks": "0",
           "actions": []}
    m = derive_metrics(row)
    assert m["link_cpc"] is None
    assert m["link_ctr"] is None
    assert m["cpl"] is None
    assert m["hook_rate"] is None
    assert m["hold_rate"] is None


def test_lead_action_types_prefers_pixel_lead_first():
    assert LEAD_ACTION_TYPES[0] == "offsite_conversion.fb_pixel_lead"
    assert "lead" in LEAD_ACTION_TYPES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_media.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.data.paid_media'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_media.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/paid_media.py dashboard/tests/test_paid_media.py
git commit -m "feat(paid-media): pure derived FB metrics (link CPC/CTR, CPL, hook/hold rate)"
```

---

### Task 5: Pure three-source lead reconciliation

**Files:**
- Modify: `dashboard/data/paid_media.py` (append)
- Modify: `dashboard/tests/test_paid_media.py` (append)

**Interfaces:**
- Consumes: `_div` from Task 4.
- Produces: `reconcile_lead_counts(fb_leads, hyros_leads, hubspot_leads, over_report_pct=0.20) -> dict` returning keys `fb_leads`, `hyros_leads`, `hubspot_leads`, `fb_vs_hyros_pct`, `hyros_vs_hubspot_pct`, `flags` (list of str), `trusted_count` (float). Task 6 consumes `trusted_count`.

- [ ] **Step 1: Write the failing tests**

```python
from dashboard.data.paid_media import reconcile_lead_counts


def test_reconcile_flags_fb_over_report_above_threshold():
    r = reconcile_lead_counts(fb_leads=20, hyros_leads=11, hubspot_leads=11)
    assert r["fb_vs_hyros_pct"] > 0.80
    assert "FB_OVER_REPORT" in r["flags"]


def test_reconcile_no_flag_when_sources_agree():
    r = reconcile_lead_counts(fb_leads=11, hyros_leads=11, hubspot_leads=11)
    assert r["flags"] == []
    assert r["fb_vs_hyros_pct"] == 0.0


def test_reconcile_small_variance_under_threshold_is_not_flagged():
    r = reconcile_lead_counts(fb_leads=11, hyros_leads=10, hubspot_leads=10)
    assert r["fb_vs_hyros_pct"] == 0.10
    assert "FB_OVER_REPORT" not in r["flags"]


def test_reconcile_flags_hyros_without_crm_record():
    r = reconcile_lead_counts(fb_leads=10, hyros_leads=10, hubspot_leads=4)
    assert "HYROS_WITHOUT_CRM" in r["flags"]


def test_reconcile_flags_untracked_traffic_when_hubspot_leads():
    r = reconcile_lead_counts(fb_leads=10, hyros_leads=4, hubspot_leads=10)
    assert "HYROS_UNDERTRACKING" in r["flags"]


def test_reconcile_trusted_count_prefers_two_source_agreement():
    # Hyros and HubSpot agree at 11, FB says 20 -> trust 11
    r = reconcile_lead_counts(fb_leads=20, hyros_leads=11, hubspot_leads=11)
    assert r["trusted_count"] == 11


def test_reconcile_trusted_count_falls_back_to_hyros_when_all_disagree():
    r = reconcile_lead_counts(fb_leads=20, hyros_leads=11, hubspot_leads=6)
    assert r["trusted_count"] == 11


def test_reconcile_zero_hyros_does_not_divide_by_zero():
    r = reconcile_lead_counts(fb_leads=5, hyros_leads=0, hubspot_leads=0)
    assert r["fb_vs_hyros_pct"] is None
    assert "HYROS_ZERO_WITH_FB_LEADS" in r["flags"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_media.py -k reconcile -v`
Expected: FAIL with `ImportError: cannot import name 'reconcile_lead_counts'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_media.py -v`
Expected: 15 passed (7 from Task 4 plus 8 new)

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/paid_media.py dashboard/tests/test_paid_media.py
git commit -m "feat(paid-media): three-source lead reconciliation with variance flags"
```

---

### Task 6: Pure booked-call attribution join

**Files:**
- Modify: `dashboard/data/paid_media.py` (append)
- Modify: `dashboard/tests/test_paid_media.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `is_booked_call(activity_type) -> bool` and `booked_calls_by_source(hyros_rows, email_to_id, meetings, source_key="first_source_name") -> dict[str, int]` mapping a Hyros source label to a count of distinct contacts who booked a discovery or strategy call. Task 7 consumes this.

Booked calls are counted **per distinct contact**, not per meeting, matching the contact-level counting convention the dashboard already uses everywhere else. A prospect who books three calls is one booked call for cost purposes.

- [ ] **Step 1: Write the failing tests**

```python
from dashboard.data.paid_media import is_booked_call, booked_calls_by_source


def test_is_booked_call_matches_15_min_and_strategy():
    assert is_booked_call("15 min call") is True
    assert is_booked_call("15-Min Discovery") is True
    assert is_booked_call("Strategy Call") is True
    assert is_booked_call("Protocol Mapping") is True


def test_is_booked_call_rejects_device_intro_calls():
    # Per Kurt's standing decision these are NOT discovery calls
    assert is_booked_call("DTI Intro Call") is False
    assert is_booked_call("TheraRay Intro Call") is False
    assert is_booked_call("HydroWave Intro Call") is False
    assert is_booked_call(None) is False
    assert is_booked_call("") is False


def test_booked_calls_by_source_counts_distinct_contacts():
    hyros = [
        {"email": "a@x.com", "first_source_name": "AD_A"},
        {"email": "b@x.com", "first_source_name": "AD_A"},
        {"email": "c@x.com", "first_source_name": "AD_B"},
    ]
    email_to_id = {"a@x.com": "1", "b@x.com": "2", "c@x.com": "3"}
    meetings = [
        {"contact_id": "1", "activity_type": "15 min call"},
        {"contact_id": "1", "activity_type": "Strategy Call"},  # same contact
        {"contact_id": "3", "activity_type": "15 min call"},
    ]
    got = booked_calls_by_source(hyros, email_to_id, meetings)
    assert got == {"AD_A": 1, "AD_B": 1}   # contact 1 counted once, not twice


def test_booked_calls_by_source_ignores_non_discovery_meetings():
    hyros = [{"email": "a@x.com", "first_source_name": "AD_A"}]
    meetings = [{"contact_id": "1", "activity_type": "DTI Intro Call"}]
    got = booked_calls_by_source(hyros, {"a@x.com": "1"}, meetings)
    assert got == {}


def test_booked_calls_by_source_skips_unmatched_emails():
    hyros = [{"email": "ghost@x.com", "first_source_name": "AD_A"}]
    meetings = [{"contact_id": "1", "activity_type": "15 min call"}]
    got = booked_calls_by_source(hyros, {}, meetings)
    assert got == {}


def test_booked_calls_by_source_honours_last_source_key():
    hyros = [{"email": "a@x.com", "first_source_name": "AD_A",
              "last_source_name": "AD_Z"}]
    meetings = [{"contact_id": "1", "activity_type": "15 min call"}]
    got = booked_calls_by_source(hyros, {"a@x.com": "1"}, meetings,
                                 source_key="last_source_name")
    assert got == {"AD_Z": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_media.py -k booked -v`
Expected: FAIL with `ImportError: cannot import name 'is_booked_call'`

- [ ] **Step 3: Write the implementation**

```python
DISCOVERY_SUBSTRINGS = ("15 min", "15-min", "strategy", "protocol mapping")

# Device/product intro calls are excluded per Kurt's standing decision: they
# are not discovery calls and must not inflate the booked-call denominator.
EXCLUDED_SUBSTRINGS = ("intro call",)


def is_booked_call(activity_type) -> bool:
    """True when a meeting activity_type counts as a booked discovery call."""
    t = (activity_type or "").lower()
    if not t:
        return False
    if any(x in t for x in EXCLUDED_SUBSTRINGS):
        return False
    return any(x in t for x in DISCOVERY_SUBSTRINGS)


def booked_calls_by_source(hyros_rows: list[dict],
                           email_to_id: dict[str, str],
                           meetings: list[dict],
                           source_key: str = "first_source_name",
                           ) -> dict[str, int]:
    """Count distinct contacts per Hyros source label who booked a call.

    Contact-level counting, matching the dashboard convention: one prospect
    with three meetings is one booked call.
    """
    booked_ids = {
        str(m.get("contact_id")) for m in meetings
        if is_booked_call(m.get("activity_type")) and m.get("contact_id")
    }

    per_source: dict[str, set[str]] = {}
    for row in hyros_rows:
        label = row.get(source_key)
        email = (row.get("email") or "").strip().lower()
        if not label or not email:
            continue
        cid = email_to_id.get(email)
        if not cid or str(cid) not in booked_ids:
            continue
        per_source.setdefault(label, set()).add(str(cid))

    return {k: len(v) for k, v in per_source.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_media.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/paid_media.py dashboard/tests/test_paid_media.py
git commit -m "feat(paid-media): contact-level booked-call attribution join"
```

---

### Task 7: Pure baseline computation and cut-list tiering

**Files:**
- Modify: `dashboard/data/paid_media.py` (append)
- Modify: `dashboard/tests/test_paid_media.py` (append)

**Interfaces:**
- Consumes: `_div` from Task 4.
- Produces: `compute_baselines(rows) -> dict` with keys `blended_cost_per_call`, `blended_cpl`, `total_spend`, `total_calls`, `total_leads`; and `tier_ads(rows, baselines, min_impressions=1000, min_spend=100.0) -> list[dict]` where each output dict adds `tier`, `cost_per_call`, and `reason`.

Thresholds are derived from `baselines` at call time, never hardcoded, so they stay correct as account performance moves. The spec's stated figures ($235.66 blended cost per call, $203.38 blended CPL, $353.49 cut threshold, $406.76 CPL threshold) are what these formulas must reproduce from Kurt's 14-day data, and the tests assert exactly that.

- [ ] **Step 1: Write the failing tests**

```python
from dashboard.data.paid_media import compute_baselines, tier_ads


def test_compute_baselines_reproduces_kurts_14_day_figures():
    rows = [{"spend": 14846.77, "booked_calls": 63, "trusted_leads": 73}]
    b = compute_baselines(rows)
    assert round(b["blended_cost_per_call"], 2) == 235.66
    assert round(b["blended_cpl"], 2) == 203.38


def test_compute_baselines_sums_across_rows_including_paused():
    rows = [{"spend": 100.0, "booked_calls": 1, "trusted_leads": 2},
            {"spend": 300.0, "booked_calls": 1, "trusted_leads": 2}]
    b = compute_baselines(rows)
    assert b["total_spend"] == 400.0
    assert b["blended_cost_per_call"] == 200.0
    assert b["blended_cpl"] == 100.0


def test_compute_baselines_zero_calls_gives_none_not_crash():
    b = compute_baselines([{"spend": 500.0, "booked_calls": 0,
                            "trusted_leads": 0}])
    assert b["blended_cost_per_call"] is None
    assert b["blended_cpl"] is None


BASE = {"blended_cost_per_call": 235.66, "blended_cpl": 203.38}


def test_tier_below_judgeability_floor_is_insufficient_data():
    rows = [{"ad_id": "1", "spend": 50.0, "impressions": 400,
             "booked_calls": 0, "trusted_leads": 0}]
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "INSUFFICIENT_DATA"


def test_tier_low_impressions_alone_blocks_judgement():
    rows = [{"ad_id": "1", "spend": 900.0, "impressions": 300,
             "booked_calls": 0, "trusted_leads": 0}]
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "INSUFFICIENT_DATA"


def test_tier_cut_now_zero_calls_and_no_leads():
    rows = [{"ad_id": "1", "spend": 300.0, "impressions": 20000,
             "booked_calls": 0, "trusted_leads": 0}]
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "CUT_NOW"


def test_tier_cut_now_zero_calls_and_cpl_above_2x():
    # CPL 500 > 2 x 203.38 = 406.76
    rows = [{"ad_id": "1", "spend": 500.0, "impressions": 20000,
             "booked_calls": 0, "trusted_leads": 1}]
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "CUT_NOW"


def test_tier_zero_calls_but_cheap_leads_is_watch_not_cut():
    # 4 leads at $75 CPL, no calls yet -> too early to kill
    rows = [{"ad_id": "1", "spend": 300.0, "impressions": 20000,
             "booked_calls": 0, "trusted_leads": 4}]
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "WATCH"


def test_tier_cut_reallocate_needs_two_calls_of_history():
    # cost per call 400 > 353.49 but only 1 call -> not enough history
    one = tier_ads([{"ad_id": "1", "spend": 400.0, "impressions": 20000,
                     "booked_calls": 1, "trusted_leads": 3}], BASE)
    assert one[0]["tier"] == "WATCH"
    # same cost per call with 2 calls -> cut
    two = tier_ads([{"ad_id": "2", "spend": 800.0, "impressions": 20000,
                     "booked_calls": 2, "trusted_leads": 6}], BASE)
    assert two[0]["tier"] == "CUT_REALLOCATE"


def test_tier_scale_at_or_below_blended():
    rows = [{"ad_id": "1", "spend": 400.0, "impressions": 20000,
             "booked_calls": 2, "trusted_leads": 5}]      # 200 per call
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "SCALE"


def test_tier_watch_between_1x_and_15x():
    rows = [{"ad_id": "1", "spend": 600.0, "impressions": 20000,
             "booked_calls": 2, "trusted_leads": 5}]      # 300 per call
    out = tier_ads(rows, BASE)
    assert out[0]["tier"] == "WATCH"


def test_tier_every_row_gets_a_human_readable_reason():
    rows = [{"ad_id": "1", "spend": 300.0, "impressions": 20000,
             "booked_calls": 0, "trusted_leads": 0}]
    out = tier_ads(rows, BASE)
    assert out[0]["reason"]
    assert "\u2014" not in out[0]["reason"]   # no em dashes in report prose
    assert "$300.00" in out[0]["reason"]      # cites the actual spend
    assert "zero booked calls" in out[0]["reason"]


def test_tier_missing_baseline_degrades_to_insufficient_data():
    rows = [{"ad_id": "1", "spend": 300.0, "impressions": 20000,
             "booked_calls": 2, "trusted_leads": 5}]
    out = tier_ads(rows, {"blended_cost_per_call": None, "blended_cpl": None})
    assert out[0]["tier"] == "INSUFFICIENT_DATA"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_media.py -k "baseline or tier" -v`
Expected: FAIL with `ImportError: cannot import name 'compute_baselines'`

- [ ] **Step 3: Write the implementation**

```python
def compute_baselines(rows: list[dict]) -> dict:
    """Blended benchmarks across every row passed in.

    Callers pass ALL in-window spend including paused campaigns, per Kurt's
    decision: excluding roughly 46% of spend would skew what "good" means.
    """
    total_spend = sum(float(r.get("spend") or 0) for r in rows)
    total_calls = sum(float(r.get("booked_calls") or 0) for r in rows)
    total_leads = sum(float(r.get("trusted_leads") or 0) for r in rows)
    return {
        "total_spend": total_spend,
        "total_calls": total_calls,
        "total_leads": total_leads,
        "blended_cost_per_call": _div(total_spend, total_calls),
        "blended_cpl": _div(total_spend, total_leads),
    }


def tier_ads(rows: list[dict], baselines: dict,
             min_impressions: float = 1000.0,
             min_spend: float = 100.0,
             cut_multiple: float = 1.5,
             cpl_cut_multiple: float = 2.0,
             cut_now_spend: float = 250.0,
             min_calls_for_cut: int = 2) -> list[dict]:
    """Assign a tier to each row. Returns new dicts; does not mutate input."""
    bcpc = baselines.get("blended_cost_per_call")
    bcpl = baselines.get("blended_cpl")

    out = []
    for r in rows:
        spend = float(r.get("spend") or 0)
        impressions = float(r.get("impressions") or 0)
        calls = float(r.get("booked_calls") or 0)
        leads = float(r.get("trusted_leads") or 0)
        cpc_call = _div(spend, calls)
        cpl = _div(spend, leads)

        row = dict(r)
        row["cost_per_call"] = cpc_call

        if impressions < min_impressions or spend < min_spend:
            row["tier"] = "INSUFFICIENT_DATA"
            row["reason"] = (
                f"Only {impressions:,.0f} impressions and ${spend:,.2f} spend. "
                f"Needs {min_impressions:,.0f} impressions and "
                f"${min_spend:,.2f} to judge. Let it run."
            )
        elif bcpc is None or bcpl is None:
            row["tier"] = "INSUFFICIENT_DATA"
            row["reason"] = ("No account baseline available, so no threshold "
                             "to judge against.")
        elif calls == 0 and spend >= cut_now_spend and (
                leads == 0 or (cpl is not None and cpl >= bcpl * cpl_cut_multiple)):
            row["tier"] = "CUT_NOW"
            lead_txt = ("zero leads" if leads == 0
                        else f"CPL ${cpl:,.2f} vs ${bcpl * cpl_cut_multiple:,.2f} ceiling")
            row["reason"] = (f"${spend:,.2f} spent, zero booked calls, "
                             f"{lead_txt}.")
        elif (cpc_call is not None and calls >= min_calls_for_cut
              and cpc_call >= bcpc * cut_multiple):
            row["tier"] = "CUT_REALLOCATE"
            row["reason"] = (
                f"${cpc_call:,.2f} per booked call vs "
                f"${bcpc * cut_multiple:,.2f} threshold, on {calls:.0f} calls "
                f"of history."
            )
        elif cpc_call is not None and cpc_call <= bcpc:
            row["tier"] = "SCALE"
            row["reason"] = (f"${cpc_call:,.2f} per booked call, at or below "
                             f"the ${bcpc:,.2f} blended baseline.")
        else:
            row["tier"] = "WATCH"
            if cpc_call is None:
                row["reason"] = (
                    f"${spend:,.2f} spent, {leads:.0f} leads, no booked calls "
                    f"yet. Leads are not over the ${bcpl * cpl_cut_multiple:,.2f} "
                    f"ceiling, so give it more time."
                )
            else:
                row["reason"] = (
                    f"${cpc_call:,.2f} per booked call, between the "
                    f"${bcpc:,.2f} baseline and the "
                    f"${bcpc * cut_multiple:,.2f} cut threshold."
                )
        out.append(row)
    return out
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `python -m pytest dashboard/tests/test_paid_media.py -v`
Expected: 34 passed

Run: `python -m pytest dashboard/tests -q`
Expected: full suite green, 97 prior tests plus 34 new. No regressions.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/paid_media.py dashboard/tests/test_paid_media.py
git commit -m "feat(paid-media): baseline computation + four-tier cut list engine"
```

---

### Task 8: Funnel tracking audit

**Files:**
- Read: `fb_entities.json` from Task 1 (scratchpad)
- No repo files created or modified. Findings are recorded in the chat report.

**Interfaces:**
- Consumes: `fb_entities.json` (`link_url` and `effective_status` per ad) from Task 1; the `flags` output of `reconcile_lead_counts` from Task 5 to know which funnels to prioritize.
- Produces: a per-funnel findings list used by section 7 of the report.

- [ ] **Step 1: Build the audit list**

From `fb_entities.json`, take the distinct `link_url` values belonging to ads whose `effective_status` is `ACTIVE`. Sort by the 14-day spend of the campaigns pointing at them so the biggest money gets audited first. Cross-reference against the `FB_OVER_REPORT` flags from Task 5: a funnel carrying that flag is a confirmed suspect, not just a candidate.

- [ ] **Step 2: Open each funnel and capture the tracking state**

For each URL, using the Claude Browser tools:

1. `preview_start` with `{url}` to open the funnel.
2. `read_network_requests` with `urlPattern` `facebook.com/tr` to count pixel fires **on page load alone**. More than one fire per pixel id, or any `ev=Lead` present before a form submit, is the double-report cause.
3. `javascript_tool` to enumerate what is installed:

```javascript
JSON.stringify({
  fbq_present: typeof fbq !== "undefined",
  fbq_queue_len: (typeof fbq !== "undefined" && fbq.queue) ? fbq.queue.length : null,
  pixel_ids: Array.from(new Set(
    Array.from(document.querySelectorAll("script"))
      .flatMap(s => Array.from((s.textContent || "").matchAll(/fbq\('init',\s*'(\d+)'/g)))
      .map(m => m[1])
  )),
  pixel_script_tags: Array.from(document.querySelectorAll("script"))
    .filter(s => (s.src || "").includes("connect.facebook.net")).length,
  pixel_noscript_imgs: document.querySelectorAll('noscript img[src*="facebook.com/tr"]').length,
  gtm_present: typeof google_tag_manager !== "undefined",
  gtm_containers: typeof google_tag_manager !== "undefined"
    ? Object.keys(google_tag_manager).filter(k => k.startsWith("GTM-")) : [],
  hyros_scripts: Array.from(document.querySelectorAll("script"))
    .filter(s => /hyros|t\.hyros\.com/i.test(s.src || s.textContent || "")).length,
  hubspot_forms: document.querySelectorAll("form.hs-form, .hbspt-form").length,
  all_forms: document.querySelectorAll("form").length
})
```

Record, per funnel: pixel id count, duplicate `connect.facebook.net` script tags, `noscript` fallback images that fire a second time, GTM containers that may also be firing a Lead tag, Hyros script presence, and duplicate form embeds.

4. `read_console_messages` with `onlyErrors: true` to catch a tracking script that is throwing and retrying.

- [ ] **Step 3: Check the thank-you page separately**

The most common cause of a stable percentage over-report is a `Lead` event on the thank-you page that re-fires on every page view and refresh, rather than once per submission. Where a thank-you or confirmation URL is discoverable from the funnel, load it directly and repeat Step 2's network check. A `Lead` event firing on a bare page load with no form submission behind it confirms it.

Do not submit any funnel form to test this. Submitting creates a real lead in HubSpot and pollutes the data being analyzed.

- [ ] **Step 4: Diagnose the Hyros $0.00 revenue column**

Separate defect from the lead over-report. Check, in order:

1. Did `hyros_endpoints.json` (Task 2) show an orders or sales endpoint returning 200 with an empty result set? Empty means Hyros is reachable but has no revenue data, pointing at missing event delivery rather than an API problem.
2. Is the Hyros script present on the funnel pages at all (Step 2's `hyros_scripts` count)? Absent on the money pages means no purchase event can ever fire.
3. Is revenue expected to arrive from HubSpot deals rather than a checkout? BPA closes on sales calls, not self-serve checkout, so Hyros would need deal values pushed in from HubSpot. If no integration is doing that, $0.00 is the expected consequence of an absent integration, not a broken pixel, and the fix is an integration decision rather than a tracking repair.

Report which of these three it is. Do not change any configuration.

- [ ] **Step 5: No commit**

This task produces findings, not code. Nothing to commit.

---

### Task 9: Assemble and deliver the report

**Files:**
- Read: every JSON file in the scratchpad from Tasks 1 to 3
- Import: `dashboard/data/paid_media.py` from Tasks 4 to 7
- No repo files created or modified.

**Interfaces:**
- Consumes: `derive_metrics`, `reconcile_lead_counts`, `booked_calls_by_source`, `compute_baselines`, `tier_ads` from `paid_media.py`; all probe JSON; Task 8's funnel findings.
- Produces: the report in chat. Nothing persisted.

- [ ] **Step 1: Re-verify the accuracy gate before analyzing**

Recompute from the probe JSON and confirm against the table in Global Constraints: `checksum` spend $14,846.77, Hyros 73 leads, `w7` spend $6,890.57, Hyros 29 leads. State the actual computed figures in the report. If any figure is off, say so plainly and explain the cause rather than presenting the analysis as clean.

- [ ] **Step 2: Compute the three-window analysis**

For each of `w14`, `w7`, `w3`: apply `derive_metrics` to every insights row at all three levels; compute `booked_calls_by_source` per window; join booked calls onto ad rows by Hyros source label; call `compute_baselines` over **all** rows in the window including paused campaigns; call `tier_ads` over **active-only** rows.

The label join is the fragile step. Hyros source names come from its own ad naming and may not match FB `ad_name` exactly. Report the match rate. Where labels cannot be matched at ad level, fall back to ad set, then campaign, and say which level each number came from rather than presenting an unmatched ad as having zero calls.

- [ ] **Step 3: Write the seven report sections**

Follow the spec's structure: headline (cut today, scale today, waste identified), which numbers to trust and why, campaign table across three windows, ad set table per active campaign, ad-level tiered cut list, copy and creative recommendations, tracking findings and fixes.

Creative recommendations follow the winning-creative-evolution convention: variations and modular swaps off what is already winning, not net-new angles. Use the `body`, `title`, and `thumbnail_url` captured in `fb_entities.json` to ground the recommendations in the actual copy running.

Include the timezone caveat: FB reports in the ad account timezone, Hyros and HubSpot may not, so single-day edge drift is expected and small variances are not evidence of a defect.

- [ ] **Step 4: State the limits honestly**

Name anything that could not be determined: Hyros endpoints that 404'd, ads whose source label would not join, funnels that could not be loaded, ads below the judgeability floor. A cut list that silently omits unjudgeable ads reads as complete coverage when it is not.

- [ ] **Step 5: No commit**

The report is a chat deliverable.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: windows and FB pulls to Task 1; Hyros with full source objects and the calls/revenue open question to Task 2; HubSpot third count and booked calls to Task 3; derived metrics including hook and hold rate to Task 4; reconciliation and variance rules to Task 5; the booked-call join fallback to Task 6; judgeability floor, baselines, and the four tiers to Task 7; the funnel audit and the $0.00 revenue diagnosis to Task 8; report structure, accuracy gate, and objective normalization to Task 9.

One spec item is deliberately handled in Task 9 rather than in code: **objective normalization** (bucketing ads by optimization event so Landing Page View campaigns are not ranked against Website Lead campaigns on CPL). `tier_ads` keys on cost per booked call, which is objective-independent, so no code branch is needed. Task 9 Step 2 groups by optimization event when presenting CPL comparisons.

**Type consistency.** `_div` returns `float | None` and every consumer handles `None` explicitly. `trusted_count` from `reconcile_lead_counts` is the `trusted_leads` key that `compute_baselines` and `tier_ads` read. `booked_calls_by_source` returns `dict[str, int]` keyed on the Hyros source label, joined to the `booked_calls` key those two functions read. Function names are identical across the tasks that define and consume them.

**Threshold arithmetic verified against the tests.** With `blended_cost_per_call` $235.66 and `blended_cpl` $203.38, the cut threshold is $353.49 (1.5x) and the zero-call CPL ceiling is $406.76 (2x), matching the spec. The tier branch order was traced against all 13 tiering tests: floor check, then missing-baseline, then CUT_NOW, then CUT_REALLOCATE, then SCALE, then WATCH as the catch-all. An ad with zero booked calls and cheap leads lands in WATCH rather than CUT because `cost_per_call` is `None` and both cut branches require a non-`None` value.

**Test counts are cumulative:** Task 4 adds 7, Task 5 adds 8 (15 total), Task 6 adds 6 (21 total), Task 7 adds 13 (34 total). The expected counts in each task's run step assume the prior tasks landed.

## Open Risks

1. **Hyros ad-level attribution may not exist.** If `firstSource.name` is a campaign name rather than an ad name, ad-level booked-call attribution collapses to campaign level and the ad-level cut list must be driven by FB leads with a stated caveat. Task 2 Step 5 reveals this. Do not fabricate ad-level precision that the data cannot support.
2. **Hyros lead counts may not match the extension exactly.** The extension may apply an attribution model the API does not. If Task 2's gate misses by a small margin, report the delta rather than forcing a match.
3. **FB API v19.0 may be retired.** Task 1 Step 5 covers bumping the version.
4. **Thresholds are provisional.** Kurt approved them as revisable after the first run. Every threshold is a named parameter with a default, so tuning is a call-site change and not a rewrite.
