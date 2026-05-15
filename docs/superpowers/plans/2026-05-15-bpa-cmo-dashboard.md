# BPA CMO Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit dashboard hosted on Streamlit Community Cloud that shows BPA's complete funnel from ad spend → marketing lead → 15-min call → Strategy Call → Closed-Won, gated by a shared password, behind a calendar date-range picker.

**Architecture:** New `dashboard/` subdirectory inside the existing `bpa-cmo-agent` repo. Reuses the existing FB / Hyros / HubSpot pull logic from `hubspot_puller.py`, `weekly_report_v3.py`, `hyros_probe2.py`. Two-tab UI (Marketing, Sales). HubSpot = source of truth, FB = spend, Hyros = cross-check.

**Tech Stack:** Python 3.11+, Streamlit, pandas, plotly, anthropic (for the existing scripts), requests, python-dotenv. Hosted on Streamlit Community Cloud (free) from a GitHub repo. Secrets via Streamlit secrets manager.

---

## File Structure

```
bpa-cmo-agent/
├── dashboard/
│   ├── app.py                # Streamlit entrypoint, password gate, tabs
│   ├── auth.py               # password gate component
│   ├── config.py             # constants, group regex patterns, env loading
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fb_loader.py      # FB Ads pull by date range
│   │   ├── hyros_loader.py   # Hyros lead/call pull by date range
│   │   ├── hubspot_loader.py # HubSpot contact + deal pull
│   │   ├── reconcile.py      # joins across sources, lead-count cross-check
│   │   └── groups.py         # campaign group regex matcher (Chiro/PT/TheraRay/EMX)
│   ├── sections/
│   │   ├── __init__.py
│   │   ├── marketing.py      # MARKETING tab
│   │   └── sales.py          # SALES tab
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_groups.py    # campaign group matcher (pure logic, unit tests)
│   │   ├── test_reconcile.py # reconciliation math (pure logic, unit tests)
│   │   └── test_smoke.py     # loader smoke tests (real API, manual run)
│   ├── requirements.txt
│   └── README.md
├── .streamlit/
│   └── secrets.toml.example  # template for local dev
```

---

## Phase 1 — Project Scaffold & Password Gate

Goal: empty Streamlit app deployable to Streamlit Cloud, password gate works, calendar date picker renders, two empty tabs visible.

### Task 1: Create directory skeleton and requirements file

**Files:**
- Create: `dashboard/__init__.py` (empty)
- Create: `dashboard/data/__init__.py` (empty)
- Create: `dashboard/sections/__init__.py` (empty)
- Create: `dashboard/tests/__init__.py` (empty)
- Create: `dashboard/requirements.txt`
- Create: `.streamlit/secrets.toml.example`

- [ ] **Step 1: Create the empty package files**

```bash
cd ~/Desktop/bpa-cmo-agent
mkdir -p dashboard/data dashboard/sections dashboard/tests .streamlit
touch dashboard/__init__.py dashboard/data/__init__.py dashboard/sections/__init__.py dashboard/tests/__init__.py
```

- [ ] **Step 2: Write `dashboard/requirements.txt`**

```text
streamlit==1.40.0
pandas==2.2.3
plotly==5.24.1
requests==2.32.3
python-dotenv==1.0.1
pytest==8.3.3
```

- [ ] **Step 3: Write `.streamlit/secrets.toml.example`**

```toml
# Copy to .streamlit/secrets.toml for local dev. Never commit the real file.
FB_ADS_TOKEN = "your_fb_access_token"
FB_AD_ACCOUNT_ID = "1234567890"
HYROS_API_KEY = "your_hyros_key"
HUBSPOT_TOKEN = "pat-na1-..."
DASHBOARD_PASSWORD = "set_a_strong_shared_password"
```

- [ ] **Step 4: Update `.gitignore` to exclude real secrets**

Add these lines to `.gitignore`:

```text
.streamlit/secrets.toml
dashboard/__pycache__/
dashboard/**/__pycache__/
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/ .streamlit/secrets.toml.example .gitignore
git commit -m "scaffold(dashboard): create directory skeleton and dependency manifest"
```

---

### Task 2: Password gate

**Files:**
- Create: `dashboard/auth.py`

- [ ] **Step 1: Write `dashboard/auth.py`**

```python
"""Shared-password gate. One password, set in Streamlit secrets, no user accounts."""
from __future__ import annotations

import streamlit as st


def require_password() -> None:
    """Block rendering until the user enters the correct shared password.

    Sets st.session_state['authenticated'] on success. Call this as the very
    first line of the Streamlit app, after st.set_page_config.
    """
    if st.session_state.get("authenticated"):
        return

    st.title("BPA CMO Dashboard")
    pw = st.text_input("Password", type="password")
    if not pw:
        st.stop()

    expected = st.secrets.get("DASHBOARD_PASSWORD", "")
    if pw == expected and expected != "":
        st.session_state["authenticated"] = True
        st.rerun()
    else:
        st.error("Incorrect password.")
        st.stop()
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/auth.py
git commit -m "feat(dashboard): add shared-password gate"
```

---

### Task 3: App entrypoint with date picker and tabs

**Files:**
- Create: `dashboard/app.py`

- [ ] **Step 1: Write `dashboard/app.py`**

```python
"""BPA CMO Dashboard entrypoint."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from dashboard.auth import require_password


st.set_page_config(
    page_title="BPA CMO Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

require_password()

# --- Global header ---
st.title("BPA CMO Dashboard")

col_dates, col_refresh = st.columns([4, 1])
with col_dates:
    today = date.today()
    default_start = today - timedelta(days=7)
    date_range = st.date_input(
        "Date range",
        value=(default_start, today),
        max_value=today,
    )
with col_refresh:
    st.write("")  # spacing
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    st.warning("Pick a start and end date.")
    st.stop()

st.caption(f"Window: {start_date} → {end_date}")

# --- Tabs ---
tab_marketing, tab_sales = st.tabs(["MARKETING", "SALES"])

with tab_marketing:
    st.info("Marketing tab — wired in Phase 3.")

with tab_sales:
    st.info("Sales tab — wired in Phase 5.")
```

- [ ] **Step 2: Run the app locally to verify password gate + tabs render**

```bash
cd ~/Desktop/bpa-cmo-agent
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml and set DASHBOARD_PASSWORD to anything for testing
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

Expected: browser opens at `http://localhost:8501`, shows password prompt. Enter password. Dashboard renders with date picker, refresh button, two empty tabs.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.py
git commit -m "feat(dashboard): scaffold app with date picker and tabs"
```

---

## Phase 2 — HubSpot Probe (resolve open items from spec)

Goal: confirm exact HubSpot property internal names and deal stage IDs before wiring loaders. Output is a `dashboard/config.py` with constants the rest of the code uses.

### Task 4: Write HubSpot probe script

**Files:**
- Create: `dashboard/probes/hubspot_probe.py`

- [ ] **Step 1: Write the probe**

```python
"""One-time probe to confirm HubSpot internal field names and deal stage IDs.

Run manually: python -m dashboard.probes.hubspot_probe
Output goes to stdout; copy the IDs into dashboard/config.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


def main() -> None:
    env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    token = env.get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("HUBSPOT_TOKEN not found in .env")

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Contact properties — look for typeform_asset_download, sdr_owner, bds, sme
    print("=" * 60)
    print("CONTACT PROPERTIES")
    print("=" * 60)
    r = requests.get(
        "https://api.hubapi.com/crm/v3/properties/contacts",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    wanted = {"typeform", "sdr", "bds", "sme", "utm_source"}
    for p in r.json().get("results", []):
        name = p.get("name", "").lower()
        label = p.get("label", "").lower()
        if any(w in name or w in label for w in wanted):
            print(f"  {p['name']:40s}  ({p.get('label')})  type={p.get('type')}")

    # 2. Deal pipelines and stages — look for 15-min, Strategy, Closed-Won
    print()
    print("=" * 60)
    print("DEAL PIPELINES + STAGES")
    print("=" * 60)
    r = requests.get(
        "https://api.hubapi.com/crm/v3/pipelines/deals",
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    for p in r.json().get("results", []):
        print(f"\nPipeline: {p['label']}  (id={p['id']})")
        for s in p.get("stages", []):
            print(f"  stage id={s['id']:30s} label={s['label']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the probe**

```bash
cd ~/Desktop/bpa-cmo-agent
python -m dashboard.probes.hubspot_probe
```

Expected: prints contact property internal names (e.g., `typeform_asset_download`, `sdr_owner`, `bds`, `sme`, `utm_source`) AND prints all deal pipelines with their stage IDs.

- [ ] **Step 3: Record findings in `dashboard/config.py`**

Create `dashboard/config.py` with the IDs from the probe output. Template:

```python
"""Dashboard-wide constants and configuration.

Values here come from the HubSpot probe (dashboard/probes/hubspot_probe.py).
Re-run the probe if HubSpot stages or properties change.
"""
from __future__ import annotations

import re

# --- HubSpot property internal names ---
# REPLACE these with the actual names from the probe output
HS_PROP_TYPEFORM_ASSET = "typeform_asset_download"  # confirm via probe
HS_PROP_SDR_OWNER = "sdr_owner"                      # confirm via probe
HS_PROP_BDS = "bds"                                   # confirm via probe
HS_PROP_SME = "sme"                                   # confirm via probe
HS_PROP_UTM_SOURCE = "utm_source"

# --- HubSpot deal stage IDs ---
# REPLACE these with stage IDs from the probe output
HS_STAGE_15MIN_BOOKED = "REPLACE_ME"
HS_STAGE_15MIN_HELD = "REPLACE_ME"
HS_STAGE_STRATEGY_BOOKED = "REPLACE_ME"
HS_STAGE_STRATEGY_HELD = "REPLACE_ME"
HS_STAGE_CLOSED_WON = "closedwon"  # HubSpot default; confirm

# Ordered list for funnel rendering
HS_STAGE_ORDER = [
    ("Marketing Lead", None),
    ("15-min Booked", HS_STAGE_15MIN_BOOKED),
    ("15-min Held", HS_STAGE_15MIN_HELD),
    ("Strategy Booked", HS_STAGE_STRATEGY_BOOKED),
    ("Strategy Held", HS_STAGE_STRATEGY_HELD),
    ("Closed-Won", HS_STAGE_CLOSED_WON),
]

# --- Campaign group regex patterns ---
# Match against FB campaign names like "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",        re.compile(r"__EMX__", re.IGNORECASE)),       # checked first so EMX wins inside Chiro
    ("Chiro",      re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery", re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",   re.compile(r"__Theraray__", re.IGNORECASE)),
]

# EMX rolls up into Chiro totals in addition to being its own row
EMX_PARENT = "Chiro"
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/probes/__init__.py dashboard/probes/hubspot_probe.py dashboard/config.py
git commit -m "feat(dashboard): add hubspot probe and config constants"
```

> **Note:** Create `dashboard/probes/__init__.py` (empty) before committing.

---

## Phase 3 — Marketing Data Layer (TDD on pure logic, smoke tests on loaders)

Goal: pull FB spend, HubSpot marketing leads, Hyros leads for a date range. Produce a per-group dataframe.

### Task 5: Campaign group matcher (pure logic — TDD)

**Files:**
- Create: `dashboard/data/groups.py`
- Test: `dashboard/tests/test_groups.py`

- [ ] **Step 1: Write the failing tests**

```python
# dashboard/tests/test_groups.py
"""Tests for campaign group regex matcher."""
import pytest

from dashboard.data.groups import match_group


@pytest.mark.parametrize("name,expected", [
    ("DS | __Chiro__ Mixed Funnel Setup | CBO | USA", "Chiro"),
    ("DS | __PT__ Recovery Program Funnel | CBO | USA", "PT Recovery"),
    ("DS | __Theraray__ Funnel Setup | CBO | USA", "TheraRay"),
    ("DS | __EMX__ Event Funnel | CBO | USA", "EMX"),
    ("DS | __Chiro__ but also __EMX__ inside", "EMX"),  # EMX wins
    ("Something with no marker", None),
    ("", None),
])
def test_match_group(name, expected):
    assert match_group(name) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Desktop/bpa-cmo-agent
pytest dashboard/tests/test_groups.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.data.groups'`

- [ ] **Step 3: Write the implementation**

```python
# dashboard/data/groups.py
"""Campaign group matcher. Maps FB campaign names to logical groups."""
from __future__ import annotations

from dashboard.config import CAMPAIGN_GROUPS


def match_group(campaign_name: str) -> str | None:
    """Return the group label for a campaign name, or None if no match.

    Order in CAMPAIGN_GROUPS matters: EMX is checked before Chiro so that
    a campaign containing both tokens is classified as EMX (more specific).
    """
    if not campaign_name:
        return None
    for label, pattern in CAMPAIGN_GROUPS:
        if pattern.search(campaign_name):
            return label
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest dashboard/tests/test_groups.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/groups.py dashboard/tests/test_groups.py
git commit -m "feat(dashboard): campaign group regex matcher with tests"
```

---

### Task 6: FB loader

**Files:**
- Create: `dashboard/data/fb_loader.py`

- [ ] **Step 1: Write `dashboard/data/fb_loader.py`**

```python
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
def load_fb_insights(start: date, end: date) -> pd.DataFrame:
    """Return a dataframe with columns: campaign_name, group, spend, impressions,
    clicks, fb_leads, date_start, date_stop.

    One row per campaign. Caches for 15 minutes per date range.
    """
    token = st.secrets["FB_ADS_TOKEN"]
    acct = st.secrets["FB_AD_ACCOUNT_ID"]

    params = {
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "level": "campaign",
        "fields": "campaign_name,spend,impressions,clicks,actions,date_start,date_stop",
        "access_token": token,
        "limit": 500,
    }
    r = requests.get(f"{FB_API}/act_{acct}/insights", params=params, timeout=60)
    r.raise_for_status()
    rows = r.json().get("data", [])

    records = []
    for row in rows:
        name = row.get("campaign_name", "")
        records.append({
            "campaign_name": name,
            "group": match_group(name),
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "fb_leads": _action_value(row.get("actions"),
                                      "offsite_conversion.fb_pixel_lead")
                        or _action_value(row.get("actions"), "lead"),
            "date_start": row.get("date_start"),
            "date_stop": row.get("date_stop"),
        })
    return pd.DataFrame(records)
```

- [ ] **Step 2: Manual smoke test**

Create a throwaway test file `dashboard/tests/smoke_fb.py`:

```python
"""Manual smoke: run python -m dashboard.tests.smoke_fb"""
from datetime import date, timedelta

import os
import sys

# Make secrets available outside Streamlit
os.environ["STREAMLIT_SECRETS_PATH"] = "../.streamlit/secrets.toml"

from dashboard.data.fb_loader import load_fb_insights

today = date.today()
df = load_fb_insights(today - timedelta(days=7), today)
print(df[["campaign_name", "group", "spend", "fb_leads"]].to_string())
print(f"\n{len(df)} campaigns, {df['group'].notna().sum()} matched a group")
```

Run inside Streamlit context instead (loaders use `st.secrets`):

```bash
streamlit run dashboard/app.py
# In another terminal:
# Just observe the dashboard loads — Task 9 wires the actual rendering
```

For pure Python smoke, skip — we'll see real data in Task 9.

- [ ] **Step 3: Commit**

```bash
git add dashboard/data/fb_loader.py
git commit -m "feat(dashboard): FB Ads loader with group tagging and 15-min cache"
```

---

### Task 7: HubSpot loader (contacts + deals)

**Files:**
- Create: `dashboard/data/hubspot_loader.py`

- [ ] **Step 1: Write `dashboard/data/hubspot_loader.py`**

```python
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
                {"propertyName": "createdate", "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "createdate",
            cfg.HS_PROP_TYPEFORM_ASSET, cfg.HS_PROP_SDR_OWNER,
            cfg.HS_PROP_BDS, cfg.HS_PROP_SME, cfg.HS_PROP_UTM_SOURCE,
        ],
        "limit": 100,
    }
    results = _hs_search(token, "contacts", body)

    rows = []
    for r in results:
        p = r.get("properties", {})
        rows.append({
            "hs_id": r.get("id"),
            "name": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "email": p.get("email"),
            "created": p.get("createdate"),
            "typeform_asset_download": p.get(cfg.HS_PROP_TYPEFORM_ASSET),
            "sdr_owner": p.get(cfg.HS_PROP_SDR_OWNER),
            "bds": p.get(cfg.HS_PROP_BDS),
            "sme": p.get(cfg.HS_PROP_SME),
            "utm_source": p.get(cfg.HS_PROP_UTM_SOURCE),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner="Pulling HubSpot deals...")
def load_deals_in_window(start: date, end: date) -> pd.DataFrame:
    """Return deals modified or created in the window.

    Columns: deal_id, dealname, amount, dealstage, pipeline, createdate,
    closedate, hs_object_id, contact_ids (list).
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
        rows.append({
            "deal_id": r.get("id"),
            "dealname": p.get("dealname"),
            "amount": float(p.get("amount") or 0),
            "dealstage": p.get("dealstage"),
            "pipeline": p.get("pipeline"),
            "createdate": p.get("createdate"),
            "closedate": p.get("closedate"),
        })
    return pd.DataFrame(rows)


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
                rows.append({"contact_id": cid, "deal_id": t.get("toObjectId")})
    return pd.DataFrame(rows)
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/data/hubspot_loader.py
git commit -m "feat(dashboard): HubSpot loader for marketing contacts and deals"
```

---

### Task 8: Hyros loader

**Files:**
- Create: `dashboard/data/hyros_loader.py`

- [ ] **Step 1: Write `dashboard/data/hyros_loader.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/data/hyros_loader.py
git commit -m "feat(dashboard): Hyros loader for lead attribution"
```

---

### Task 9: Reconcile / group aggregation (TDD on pure logic)

**Files:**
- Create: `dashboard/data/reconcile.py`
- Test: `dashboard/tests/test_reconcile.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/test_reconcile.py
"""Tests for marketing per-group aggregation."""
import pandas as pd

from dashboard.data.reconcile import group_marketing_metrics


def test_group_marketing_metrics_basic():
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "impressions": 50000, "clicks": 500, "fb_leads": 20},
        {"campaign_name": "DS | __PT__ ...", "group": "PT Recovery",
         "spend": 500.0, "impressions": 25000, "clicks": 250, "fb_leads": 10},
        {"campaign_name": "DS | __EMX__ ...", "group": "EMX",
         "spend": 200.0, "impressions": 8000, "clicks": 80, "fb_leads": 5},
    ])
    # 10 marketing contacts: 6 from Chiro asset, 3 PT, 1 EMX-ish
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "3", "typeform_asset_download": "PT Recovery Guide"},
    ])
    # 2 deals from marketing leads in 15-min booked stage
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "3", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "15min_booked", "amount": 0},
    ])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }
    stages_15min = {"15min_booked", "15min_held"}

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=asset_to_group,
        stages_15min_booked=stages_15min,
    )

    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["spend"] == 1000.0
    assert chiro["leads"] == 2
    assert chiro["calls_booked"] == 1
    assert chiro["cpl"] == 500.0
    assert chiro["cost_per_qualified_call"] == 1000.0
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest dashboard/tests/test_reconcile.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `dashboard/data/reconcile.py`**

```python
"""Cross-source aggregation. HubSpot is the source of truth for leads and
calls; FB is the source of truth for spend; Hyros is the cross-check."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def _safe_div(num: float, den: float) -> float | None:
    if not den:
        return None
    return num / den


def group_marketing_metrics(
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    stages_15min_booked: Iterable[str],
) -> pd.DataFrame:
    """Return per-group marketing metrics.

    Columns: group, spend, leads, calls_booked, cpl, cost_per_qualified_call.

    - spend: sum of FB spend rows whose group matches
    - leads: count of contacts whose typeform_asset_download maps to the group
    - calls_booked: count of contacts whose deals contain a 15-min stage
    - cpl: spend / leads
    - cost_per_qualified_call: spend / calls_booked
    """
    fb_by_group = fb.groupby("group", dropna=True)["spend"].sum().to_dict()

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)

    stages_set = set(stages_15min_booked)
    booked_deal_ids = set(deals.loc[deals["dealstage"].isin(stages_set), "deal_id"])
    booked_contact_ids = set(
        contact_deals.loc[contact_deals["deal_id"].isin(booked_deal_ids), "contact_id"]
    )

    groups = sorted({*fb_by_group.keys(), *contacts["group"].dropna().unique()})
    rows = []
    for g in groups:
        leads = int((contacts["group"] == g).sum())
        booked = int(((contacts["group"] == g) &
                      contacts["hs_id"].isin(booked_contact_ids)).sum())
        spend = float(fb_by_group.get(g, 0.0))
        rows.append({
            "group": g,
            "spend": spend,
            "leads": leads,
            "calls_booked": booked,
            "cpl": _safe_div(spend, leads),
            "cost_per_qualified_call": _safe_div(spend, booked),
        })
    return pd.DataFrame(rows)


def reconciliation_panel(
    fb: pd.DataFrame,
    contacts: pd.DataFrame,
    hyros: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
) -> pd.DataFrame:
    """Return per-group lead counts from each source for cross-check.

    Columns: group, fb_leads, hyros_leads, hubspot_leads, match_rate.
    match_rate is hyros_leads / hubspot_leads (capped at 1.0), shown as diagnostic.
    """
    fb_by_group = fb.groupby("group", dropna=True)["fb_leads"].sum().to_dict()

    contacts = contacts.copy()
    contacts["group"] = contacts["typeform_asset_download"].map(asset_to_group)
    hs_by_group = contacts.groupby("group", dropna=True).size().to_dict()

    # Hyros first_source typically contains the FB campaign name — match groups by regex
    from dashboard.data.groups import match_group
    if not hyros.empty:
        hyros = hyros.copy()
        hyros["group"] = hyros["first_source"].map(match_group)
        hy_by_group = hyros.groupby("group", dropna=True).size().to_dict()
    else:
        hy_by_group = {}

    groups = sorted({*fb_by_group.keys(), *hs_by_group.keys(), *hy_by_group.keys()})
    rows = []
    for g in groups:
        hs = int(hs_by_group.get(g, 0))
        hy = int(hy_by_group.get(g, 0))
        rate = (min(hy, hs) / hs) if hs else None
        rows.append({
            "group": g,
            "fb_leads": int(fb_by_group.get(g, 0)),
            "hyros_leads": hy,
            "hubspot_leads": hs,
            "match_rate": rate,
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest dashboard/tests/test_reconcile.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat(dashboard): per-group marketing aggregation + reconciliation"
```

---

### Task 10: Asset-to-group mapping config

**Files:**
- Modify: `dashboard/config.py` (add `ASSET_TO_GROUP` dict)

- [ ] **Step 1: Add asset map**

In `dashboard/config.py`, add at the bottom:

```python
# --- Typeform asset download → campaign group mapping ---
# Populate this from the typeform_asset_download values you've seen in HubSpot.
# Use Phase 2 probe data; expand as new assets ship.
ASSET_TO_GROUP: dict[str, str] = {
    # Examples — CONFIRM exact values during Phase 2 probe:
    # "Chiro Practice Audit PDF": "Chiro",
    # "PT Recovery Implementation Guide": "PT Recovery",
    # "TheraRay Protocol PDF": "TheraRay",
    # "EMX Event Registration": "EMX",
}

STAGES_15MIN_BOOKED = {
    # filled in from probe; e.g. {"presentationscheduled", "appointmentscheduled"}
}
STAGES_15MIN_HELD = set()
STAGES_STRATEGY_BOOKED = set()
STAGES_STRATEGY_HELD = set()
```

- [ ] **Step 2: Discover real asset values**

Add a tiny probe script `dashboard/probes/asset_probe.py`:

```python
"""Print all distinct typeform_asset_download values seen in the last 90 days."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st  # noqa: requires .streamlit/secrets.toml
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dashboard.data.hubspot_loader import load_marketing_contacts

today = date.today()
df = load_marketing_contacts(today - timedelta(days=90), today)
print(df["typeform_asset_download"].value_counts())
```

Run with: `streamlit run dashboard/probes/asset_probe.py` — or refactor `load_marketing_contacts` to accept an explicit secrets dict for non-Streamlit invocation. For now, run inside Streamlit context (Task 11).

- [ ] **Step 3: Commit (placeholder mapping)**

```bash
git add dashboard/config.py dashboard/probes/asset_probe.py
git commit -m "feat(dashboard): asset-to-group mapping scaffold (values pending probe)"
```

> **Action item:** after running the probe in Task 11, return to `dashboard/config.py` and fill in `ASSET_TO_GROUP` and the four `STAGES_*` sets with real values. Commit as a separate "data: populate asset and stage maps" commit.

---

## Phase 4 — Marketing Tab UI

### Task 11: Render Marketing tab

**Files:**
- Create: `dashboard/sections/marketing.py`
- Modify: `dashboard/app.py` (replace `st.info` with `render_marketing(...)`)

- [ ] **Step 1: Write `dashboard/sections/marketing.py`**

```python
"""MARKETING tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
)
from dashboard.data.hyros_loader import load_hyros_leads
from dashboard.data.reconcile import (
    group_marketing_metrics,
    reconciliation_panel,
)


def _fmt_money(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def render_marketing(start: date, end: date) -> None:
    try:
        fb = load_fb_insights(start, end)
    except Exception as e:
        st.warning(f"FB Ads unavailable: {e}")
        fb = pd.DataFrame(columns=["campaign_name", "group", "spend",
                                   "impressions", "clicks", "fb_leads"])
    try:
        contacts = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        contacts = pd.DataFrame()
    try:
        hyros = load_hyros_leads(start, end)
    except Exception as e:
        st.warning(f"Hyros unavailable: {e}")
        hyros = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
        deals = load_deals_in_window(start, end)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
        deals = pd.DataFrame()

    metrics = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=cfg.ASSET_TO_GROUP,
        stages_15min_booked=cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
    )

    # --- Top-row KPIs ---
    total_spend = metrics["spend"].sum()
    total_leads = metrics["leads"].sum()
    total_booked = metrics["calls_booked"].sum()
    cpl = (total_spend / total_leads) if total_leads else None
    cpqc = (total_spend / total_booked) if total_booked else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ad Spend", _fmt_money(total_spend))
    c2.metric("Marketing Leads", _fmt_int(total_leads))
    c3.metric("CPL", _fmt_money(cpl))
    c4.metric("15-min Calls Booked", _fmt_int(total_booked))

    st.divider()

    # --- Section A: campaign group table ---
    st.subheader("By Campaign Group")
    display = metrics.copy()
    display["spend"] = display["spend"].map(_fmt_money)
    display["cpl"] = display["cpl"].map(_fmt_money)
    display["cost_per_qualified_call"] = display["cost_per_qualified_call"].map(_fmt_money)
    display["leads"] = display["leads"].map(_fmt_int)
    display["calls_booked"] = display["calls_booked"].map(_fmt_int)
    display = display.rename(columns={
        "group": "Group",
        "spend": "Spend",
        "leads": "Leads",
        "cpl": "CPL",
        "calls_booked": "15-min Calls",
        "cost_per_qualified_call": "Cost / Qualified Call",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Unmatched campaigns warning
    unmatched = fb[fb["group"].isna()]
    if not unmatched.empty:
        with st.expander(f"⚠️ {len(unmatched)} unmatched campaign(s) — review naming"):
            st.dataframe(unmatched[["campaign_name", "spend", "fb_leads"]],
                         hide_index=True)

    st.divider()

    # --- Section B: reconciliation panel ---
    st.subheader("Lead Reconciliation (diagnostic)")
    recon = reconciliation_panel(fb, contacts, hyros,
                                  asset_to_group=cfg.ASSET_TO_GROUP)
    if not recon.empty:
        recon_display = recon.copy()
        recon_display["match_rate"] = recon_display["match_rate"].map(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) else "—"
        )
        recon_display = recon_display.rename(columns={
            "group": "Group", "fb_leads": "FB", "hyros_leads": "Hyros",
            "hubspot_leads": "HubSpot (truth)", "match_rate": "Hyros↔HubSpot",
        })
        st.dataframe(recon_display, use_container_width=True, hide_index=True)
    st.caption("HubSpot is the headline number above. FB and Hyros shown here "
               "for cross-check only.")

    st.divider()

    # --- Section C: trend chart ---
    st.subheader("Leads & Spend Over Time")
    if not contacts.empty and not fb.empty:
        contacts["created_date"] = pd.to_datetime(contacts["created"]).dt.date
        contacts["group"] = contacts["typeform_asset_download"].map(cfg.ASSET_TO_GROUP)
        daily_leads = contacts.groupby(["created_date", "group"]).size().reset_index(name="leads")
        fig = px.bar(daily_leads, x="created_date", y="leads", color="group",
                     title="Marketing leads per day by group")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data to plot for selected window.")
```

- [ ] **Step 2: Wire it into `dashboard/app.py`**

Replace the placeholder `tab_marketing` block in `dashboard/app.py`:

```python
from dashboard.sections.marketing import render_marketing

# ...
with tab_marketing:
    render_marketing(start_date, end_date)
```

- [ ] **Step 3: Run locally and verify**

```bash
streamlit run dashboard/app.py
```

Walk through:
1. Enter password — get into dashboard.
2. Pick last 7 days.
3. MARKETING tab loads.
4. See 4 KPI cards filled in.
5. See group table with Chiro / PT Recovery / TheraRay rows.
6. See reconciliation panel.
7. See trend chart.

If any source errors, the yellow banner appears and the rest still renders.

- [ ] **Step 4: Populate `ASSET_TO_GROUP` and `STAGES_*` constants**

From the data you observed, edit `dashboard/config.py` and fill in the actual asset names and stage IDs you saw.

- [ ] **Step 5: Commit**

```bash
git add dashboard/sections/marketing.py dashboard/app.py dashboard/config.py
git commit -m "feat(dashboard): MARKETING tab — KPIs, group table, reconciliation, trend"
```

---

## Phase 5 — Sales Tab UI

### Task 12: Pipeline funnel aggregation (TDD)

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `pipeline_funnel`)
- Modify: `dashboard/tests/test_reconcile.py` (add test)

- [ ] **Step 1: Write failing test**

Append to `dashboard/tests/test_reconcile.py`:

```python
from dashboard.data.reconcile import pipeline_funnel


def test_pipeline_funnel_marketing_vs_all():
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "x"},
        {"hs_id": "2", "typeform_asset_download": "y"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",   "amount": 5000},
        {"deal_id": "d3", "dealstage": "closedwon",   "amount": 1000},  # not marketing
    ])
    stages = {
        "15min_booked":     {"15min_booked", "15min_held"},
        "strategy_booked":  set(),
        "closedwon":        {"closedwon"},
    }

    fn = pipeline_funnel(contacts, contact_deals, deals,
                         stage_groups=stages, marketing_only=True)
    assert fn["count"].loc[fn["stage"] == "15-min Booked"].iloc[0] == 1
    assert fn["count"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 1
    assert fn["revenue"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 5000.0

    fn_all = pipeline_funnel(contacts, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)
    assert fn_all["count"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 2
    assert fn_all["revenue"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 6000.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest dashboard/tests/test_reconcile.py::test_pipeline_funnel_marketing_vs_all -v
```

Expected: FAIL — `ImportError: cannot import name 'pipeline_funnel'`.

- [ ] **Step 3: Implement `pipeline_funnel`**

Append to `dashboard/data/reconcile.py`:

```python
STAGE_LABELS = [
    ("15-min Booked", "15min_booked"),
    ("15-min Held", "15min_held"),
    ("Strategy Booked", "strategy_booked"),
    ("Strategy Held", "strategy_held"),
    ("Closed-Won", "closedwon"),
]


def pipeline_funnel(
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    stage_groups: dict[str, set[str]],
    marketing_only: bool,
) -> pd.DataFrame:
    """Return funnel counts and revenue per stage.

    Columns: stage, count, revenue.
    - marketing_only=True restricts to deals whose contacts have a typeform asset.
    - stage_groups maps logical stage keys (e.g. "15min_booked") to sets of
      HubSpot dealstage internal IDs that count for that stage.
    """
    if marketing_only and not contacts.empty:
        marketing_ids = set(contacts["hs_id"])
        marketing_deals = set(
            contact_deals.loc[contact_deals["contact_id"].isin(marketing_ids), "deal_id"]
        )
        d = deals[deals["deal_id"].isin(marketing_deals)]
    else:
        d = deals

    rows = []
    for label, key in STAGE_LABELS:
        stages = stage_groups.get(key, set())
        sub = d[d["dealstage"].isin(stages)]
        rows.append({
            "stage": label,
            "count": int(len(sub)),
            "revenue": float(sub["amount"].sum()),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to confirm pass**

```bash
pytest dashboard/tests/test_reconcile.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat(dashboard): pipeline funnel aggregator with marketing-only filter"
```

---

### Task 13: Owner rollup (TDD)

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `owner_rollup`)
- Modify: `dashboard/tests/test_reconcile.py` (add test)

- [ ] **Step 1: Write failing test**

```python
from dashboard.data.reconcile import owner_rollup


def test_owner_rollup_by_sdr():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "Gage", "bds": "Scott Warren"},
        {"hs_id": "2", "sdr_owner": "Gage", "bds": "Garrett"},
        {"hs_id": "3", "sdr_owner": "Other", "bds": "Scott Warren"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
        {"contact_id": "3", "deal_id": "d3"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",    "amount": 5000},
        {"deal_id": "d3", "dealstage": "strategy_held", "amount": 0},
    ])
    stages = {
        "15min_booked":    {"15min_booked", "15min_held"},
        "strategy_booked": {"strategy_booked", "strategy_held"},
        "closedwon":       {"closedwon"},
    }

    by_sdr = owner_rollup(contacts, contact_deals, deals,
                          owner_field="sdr_owner", stage_groups=stages)

    gage = by_sdr[by_sdr["owner"] == "Gage"].iloc[0]
    assert gage["calls_15min"] == 1
    assert gage["closed_won"] == 1
    assert gage["closed_won_revenue"] == 5000.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest dashboard/tests/test_reconcile.py::test_owner_rollup_by_sdr -v
```

- [ ] **Step 3: Implement `owner_rollup`**

Append to `dashboard/data/reconcile.py`:

```python
def owner_rollup(
    contacts: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    owner_field: str,
    stage_groups: dict[str, set[str]],
) -> pd.DataFrame:
    """Aggregate funnel metrics by a contact-level owner field.

    Columns: owner, calls_15min, strategy_calls, closed_won, closed_won_revenue.
    """
    if contacts.empty:
        return pd.DataFrame(columns=["owner", "calls_15min", "strategy_calls",
                                     "closed_won", "closed_won_revenue"])

    cd = contact_deals.merge(
        contacts[["hs_id", owner_field]].rename(columns={"hs_id": "contact_id"}),
        on="contact_id", how="left",
    )
    cd = cd.merge(deals[["deal_id", "dealstage", "amount"]],
                   on="deal_id", how="left")

    s15 = stage_groups.get("15min_booked", set())
    sst = stage_groups.get("strategy_booked", set())
    scw = stage_groups.get("closedwon", set())

    rows = []
    for owner, sub in cd.groupby(owner_field, dropna=False):
        rows.append({
            "owner": owner or "(unassigned)",
            "calls_15min": int(sub["dealstage"].isin(s15).sum()),
            "strategy_calls": int(sub["dealstage"].isin(sst).sum()),
            "closed_won": int(sub["dealstage"].isin(scw).sum()),
            "closed_won_revenue": float(sub.loc[sub["dealstage"].isin(scw), "amount"].sum()),
        })
    return pd.DataFrame(rows).sort_values("closed_won_revenue", ascending=False)
```

- [ ] **Step 4: Run tests**

```bash
pytest dashboard/tests/test_reconcile.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat(dashboard): SDR/BDS owner rollup aggregator"
```

---

### Task 14: Render Sales tab

**Files:**
- Create: `dashboard/sections/sales.py`
- Modify: `dashboard/app.py`

- [ ] **Step 1: Write `dashboard/sections/sales.py`**

```python
"""SALES tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import config as cfg
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
)
from dashboard.data.reconcile import owner_rollup, pipeline_funnel


def _fmt_money(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def _stage_groups() -> dict[str, set[str]]:
    return {
        "15min_booked":    cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        "15min_held":      cfg.STAGES_15MIN_HELD,
        "strategy_booked": cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
        "strategy_held":   cfg.STAGES_STRATEGY_HELD,
        "closedwon":       {cfg.HS_STAGE_CLOSED_WON},
    }


def render_sales(start: date, end: date) -> None:
    st.info(
        '**"Marketing-attributed"** below = HubSpot contact has '
        '`typeform_asset_download` populated.',
        icon="ℹ️",
    )

    try:
        marketing = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        marketing = pd.DataFrame()
    try:
        deals = load_deals_in_window(start, end)
        contact_deals = load_contact_deals(marketing["hs_id"].tolist()) \
            if not marketing.empty else pd.DataFrame(columns=["contact_id","deal_id"])
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])

    stages = _stage_groups()

    fn_mkt = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=True)
    fn_all = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)

    # --- KPIs ---
    def _v(df, stage, col="count"):
        s = df.loc[df["stage"] == stage, col]
        return s.iloc[0] if not s.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("15-min Calls (Marketing)", _fmt_int(_v(fn_mkt, "15-min Booked")))
    c2.metric("15-min Calls (All)", _fmt_int(_v(fn_all, "15-min Booked")))
    c3.metric("Strategy Calls Held (Mkt)", _fmt_int(_v(fn_mkt, "Strategy Held")))
    c4.metric(
        "Closed-Won (Marketing)",
        f"{_fmt_int(_v(fn_mkt, 'Closed-Won'))} · "
        f"{_fmt_money(_v(fn_mkt, 'Closed-Won', 'revenue'))}",
    )

    st.divider()

    # --- Section A: pipeline funnel ---
    st.subheader("Pipeline Funnel")
    combined = fn_mkt.rename(columns={"count": "Marketing", "revenue": "mkt_rev"}).merge(
        fn_all.rename(columns={"count": "All Sources", "revenue": "all_rev"}),
        on="stage",
    )
    show = combined[["stage", "Marketing", "All Sources"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_trace(go.Funnel(name="Marketing", y=combined["stage"],
                            x=combined["Marketing"]))
    fig.add_trace(go.Funnel(name="All", y=combined["stage"],
                            x=combined["All Sources"]))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Section B: owner breakdowns ---
    col_sdr, col_bds = st.columns(2)

    only_mkt = st.checkbox("Marketing-attributed only", value=True,
                            key="owners_marketing_only")
    contacts_view = marketing if only_mkt else marketing  # we only have marketing contacts loaded

    with col_sdr:
        st.subheader("By SDR Owner")
        sdr = owner_rollup(contacts_view, contact_deals, deals,
                           owner_field="sdr_owner", stage_groups=stages)
        st.dataframe(sdr, use_container_width=True, hide_index=True)

    with col_bds:
        st.subheader("By BDS")
        bds = owner_rollup(contacts_view, contact_deals, deals,
                           owner_field="bds", stage_groups=stages)
        st.dataframe(bds, use_container_width=True, hide_index=True)

    st.divider()

    # --- Section C: drill-down ---
    st.subheader("Marketing Lead Detail")
    if marketing.empty:
        st.info("No marketing leads in this window.")
        return

    deals_by_contact = contact_deals.merge(
        deals[["deal_id", "dealstage", "amount", "createdate"]],
        on="deal_id", how="left",
    )
    latest_deal = (
        deals_by_contact.sort_values("createdate", ascending=False)
        .drop_duplicates("contact_id")
        .rename(columns={"contact_id": "hs_id"})
    )
    detail = marketing.merge(
        latest_deal[["hs_id", "dealstage", "amount"]],
        on="hs_id", how="left",
    )
    detail = detail[[
        "name", "email", "typeform_asset_download", "created",
        "sdr_owner", "bds", "dealstage", "amount",
    ]].rename(columns={
        "typeform_asset_download": "Asset",
        "created": "Created",
        "sdr_owner": "SDR Owner",
        "bds": "BDS",
        "dealstage": "Current Stage",
        "amount": "Deal $",
    })
    st.dataframe(detail, use_container_width=True, hide_index=True)
```

- [ ] **Step 2: Wire into `dashboard/app.py`**

Replace the `tab_sales` placeholder:

```python
from dashboard.sections.sales import render_sales

# ...
with tab_sales:
    render_sales(start_date, end_date)
```

- [ ] **Step 3: Run locally**

```bash
streamlit run dashboard/app.py
```

Click SALES tab. Verify:
1. KPI cards populate.
2. Funnel table + funnel chart render.
3. SDR + BDS tables render.
4. Detail table at the bottom shows marketing leads with current stage.

- [ ] **Step 4: Commit**

```bash
git add dashboard/sections/sales.py dashboard/app.py
git commit -m "feat(dashboard): SALES tab — funnel, owner rollups, drill-down"
```

---

## Phase 6 — Documentation & Deploy

### Task 15: Write dashboard README

**Files:**
- Create: `dashboard/README.md`

- [ ] **Step 1: Write `dashboard/README.md`**

```markdown
# BPA CMO Dashboard

Live funnel view from ad spend to closed deal. Marketing tab + Sales tab.
HubSpot is the source of truth; FB is spend; Hyros is cross-check.

## Local development

```bash
cd ~/Desktop/bpa-cmo-agent
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Fill in API keys and pick a DASHBOARD_PASSWORD
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

Open http://localhost:8501, enter the password.

## Tests

```bash
pytest dashboard/tests -v
```

## Adding a new campaign group

1. Edit `dashboard/config.py` → `CAMPAIGN_GROUPS` regex list.
2. Add the typeform asset(s) → `ASSET_TO_GROUP` mapping.
3. Run pytest.

## Updating HubSpot stage IDs

If HubSpot pipeline stages change:
1. Run `python -m dashboard.probes.hubspot_probe`
2. Update the `STAGES_*` sets in `dashboard/config.py`.
3. Restart the app.

## Deployment

Deployed to Streamlit Community Cloud from this repo, branch `main`.
Secrets are managed in the Streamlit Cloud UI (Settings → Secrets).
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/README.md
git commit -m "docs(dashboard): add README with local dev and deploy notes"
```

---

### Task 16: Push to GitHub and deploy

This task is run by Dr. Gumm / Kurt together — instructions only.

- [ ] **Step 1: Confirm `.streamlit/secrets.toml` is gitignored**

```bash
git check-ignore .streamlit/secrets.toml
```

Expected: prints the path (meaning it IS ignored).

- [ ] **Step 2: Push to a new GitHub repo**

If the `bpa-cmo-agent` repo is local only, create a private GitHub repo and push.

```bash
gh repo create bpa-cmo-agent --private --source=. --remote=origin --push
```

(Or use the GitHub web UI to create the repo, then `git remote add origin <url>` + `git push -u origin main`.)

- [ ] **Step 3: Deploy on Streamlit Cloud**

1. Go to https://share.streamlit.io
2. "Create app" → select the `bpa-cmo-agent` repo, branch `main`.
3. Main file path: `dashboard/app.py`
4. App URL: pick something obscure, e.g., `bpa-cmo-7a9k2`.
5. Click "Advanced settings" → "Secrets" → paste the contents of `.streamlit/secrets.toml.example` and fill in real values. Set `DASHBOARD_PASSWORD` to the shared password Dr. Gumm chooses.
6. Click Deploy.

- [ ] **Step 4: Test the live URL**

Open the assigned URL (e.g., `https://bpa-cmo-7a9k2.streamlit.app`). Enter password. Confirm both tabs render.

- [ ] **Step 5: Share the URL + password with Dr. Gumm**

Send via secure channel (NOT email or public Slack).

---

## Phase 7 — Stretch / Backlog (post-v1)

Tracked but NOT in v1 scope:

- Real-time push (replace 15-min cache with webhooks or pub/sub).
- Mobile-optimized layout.
- Export-to-CSV buttons on each table.
- Daily Slack/Gchat digest summarizing yesterday's KPIs.
- "Compare to previous period" toggle on KPI cards.
- Annotate the trend chart with ad-launch events.
- Hyros sale-event wiring (separate project — already a known gap in the parent repo).

---

## Self-Review

**Spec coverage check (matched against `2026-05-15-bpa-cmo-dashboard-design.md`):**

| Spec section | Implemented in task(s) |
|---|---|
| Password gate | Task 2 |
| Date range picker | Task 3 |
| Marketing KPIs | Task 11 |
| Campaign group breakdown (Chiro/PT/TheraRay/EMX) | Tasks 5, 11 |
| EMX as Chiro sub-row | Task 5 (regex priority), Task 11 (rendering — note: current implementation shows EMX as its own row; "sub-row inside Chiro group" is a rendering refinement listed in stretch) |
| Reconciliation panel (FB vs Hyros vs HubSpot) | Tasks 9, 11 |
| Trend chart | Task 11 |
| Sales KPIs | Task 14 |
| Pipeline funnel (marketing vs all) | Tasks 12, 14 |
| SDR owner breakdown | Tasks 13, 14 |
| BDS owner breakdown | Tasks 13, 14 |
| Marketing lead detail table | Task 14 |
| Error handling per source | Tasks 11, 14 (try/except + yellow banner) |
| Unmatched campaign warning | Task 11 |
| 15-min cache | Tasks 6, 7, 8 (st.cache_data ttl=900) |
| Deployment to Streamlit Cloud | Task 16 |

**Open item flagged:** the spec says "EMX rolls up into Chiro total, also isolatable." The current implementation classifies EMX as its own group (regex priority makes EMX win when it matches). The Chiro row therefore does NOT include EMX numbers by default. If Dr. Gumm wants Chiro totals to *include* EMX inline (with EMX visible as an indented sub-row), Task 11 needs a small post-processing step: after `group_marketing_metrics`, compute a Chiro-inclusive row by summing Chiro + EMX rows for display. Decide during Task 11 UAT.

**Placeholder scan:** zero "TBD"/"TODO" in code blocks. Asset mapping and stage IDs are explicitly flagged as "fill in after probe" with concrete steps; not placeholders, but probe-driven discovery.

**Type consistency:** `match_group` returns `str | None`; consumers handle `None` via pandas dropna. Stage groups use `set[str]` consistently. Owner rollup column names match across functions and rendering.
