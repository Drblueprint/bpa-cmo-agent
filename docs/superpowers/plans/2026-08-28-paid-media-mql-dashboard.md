# Paid Media MQL Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PAID MEDIA tab to the BPA CMO dashboard with three tables: a daily MQL summary, a per-segment funnel with cost at every stage, and an ad-level creative tracker scored on cost per callable MQL.

**Architecture:** All rollup logic lives in one new pure module, `dashboard/data/paid_mql.py`, with zero I/O and config injected as parameters. Three new cached loaders supply the data it does not already have: HubSpot MQL entry dates, FB ad-level entities, and Hyros lead records retaining ad ids. One new section module renders the tab. Tasks 1 to 5 ship a working two-table tab; tasks 6 to 9 add the creative tracker on top.

**Tech Stack:** Python 3.13, pandas (< 2.1 API floor), Streamlit, requests, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md`

## Global Constraints

- Repo root: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`. Working branch: `feature/cmo-dashboard`. Push there, never `main`.
- Target pandas is **< 2.1** (Streamlit Cloud floor). pandas Styler row styling MUST use `.apply(axis=1)`, never `.map()`.
- New pure logic goes in `dashboard/data/paid_mql.py`. Do **not** add to `dashboard/data/reconcile.py`, already 3,240 lines.
- Pure functions take config values as **parameters, not imports**, matching the existing `reconcile.py` and `paid_media.py` convention.
- Division by zero returns `None` and renders as an em-free dash `-`, never `0`. Use `_safe_div` semantics: `if not den: return None`.
- Loaders are wrapped in `@st.cache_data(ttl=900)`. In probes, bypass with `getattr(fn, "__wrapped__", fn)`.
- Probes run from repo root via the **Bash tool**: `python <path>`. The context-mode sandbox's `python` is a Windows stub and will not work.
- All probe output goes to the scratchpad, never the repo: `C:\Users\kxbox\AppData\Local\Temp\claude\C--Users-kxbox--claude\1115b3fa-cbdd-47c7-8c7d-cdfe6c2e67f7\scratchpad`
- Tests: `python -m pytest dashboard/tests -q`. Full suite must stay green. **Currently 155 passing.**
- All prose, comments, commit messages and UI copy use **standard hyphens. No em dashes.**
- Secrets already in `.streamlit/secrets.toml`: `FB_ADS_TOKEN`, `FB_AD_ACCOUNT_ID`, `HYROS_API_KEY`, `HUBSPOT_TOKEN`.
- All API access is **read-only**. GET, or POST only to HubSpot and Hyros search/list endpoints. No PATCH, PUT, or DELETE.

### Fixed values from the spec

| Constant | Value | Meaning |
|---|---|---|
| MQL entry property | `hs_v2_date_entered_marketingqualifiedlead` | Callable MQL source. Filterable server-side. |
| Segment roll-up | `EMX` + `Practice Growth Workshop` -> `Event` | Table 2 and 3 row labels |
| Creative spend floor | `500.0` | Default, UI-adjustable |
| Winner threshold | `0.25` | 25% below segment average cost per callable MQL |
| Stand Out threshold | `0.10` | 10% below segment average |
| Label volume guard | `3` | Minimum callable MQLs before any label is assigned |

### Prerequisite: already complete, do not redo

The spec lists an attribution fix as a prerequisite. **It shipped on
2026-08-28 as commit `4a88ca3`** and is already live. `CAMPAIGN_GROUPS` gained
a MAP pattern, and `ASSET_TO_GROUP` gained `Top 10 Things Muiltimillion Dollar
Practices Do`, `BPA Revenue Pyramid`, and `Movement Activation Protocol `
(that last one keeps a trailing space that is part of the stored HubSpot
value; a test pins it).

Verified impact on a 120-day window: Chiro leads 171 to 241, MAP leads 0 to
13, unattributed leads 315 to 232, unmatched spend $4,542 to $0, Chiro cost
per lead $314.88 to $223.42.

Do not re-apply these edits. Task 2 builds on them.

---

## File Structure

| File | Responsibility |
|---|---|
| `dashboard/config.py` (modify) | Add `SEGMENT_ROLLUP`, `CREATIVE_SPEND_FLOOR`, `CREATIVE_WINNER_PCT`, `CREATIVE_STANDOUT_PCT`, `CREATIVE_MIN_MQL`. |
| `dashboard/data/paid_mql.py` (create) | All pure rollup logic: segment resolution, daily activity summary, cohort segment results, creative tracker scoring. Zero I/O. |
| `dashboard/data/hubspot_loader.py` (modify) | Add `load_mql_entries`. |
| `dashboard/data/fb_loader.py` (modify) | Add `load_fb_ad_insights` and `load_fb_ad_entities`. |
| `dashboard/data/hyros_loader.py` (modify) | Add `load_hyros_leads_with_ads`, retaining `sourceLinkAd.adSourceId` and paginating. |
| `dashboard/sections/paid_media.py` (create) | `render_paid_media(start_date, end_date)`. All Streamlit rendering. |
| `dashboard/app.py` (modify) | Wire the fifth tab. |
| `dashboard/tests/test_paid_mql.py` (create) | Unit tests for every pure function. |

Loaders own I/O and are verified by running them. `paid_mql.py` owns judgment and is verified by unit tests. That boundary is why the Performance thresholds can be tested without ever calling an API.

---

### Task 1: Callable MQL loader

**Files:**
- Modify: `dashboard/data/hubspot_loader.py` (append after `load_marketing_contacts`)
- Test: verified by probe, not unit test (it is I/O)

**Interfaces:**
- Consumes: the module-level `_hs_search(token, object_type, body)` helper already in this file, which handles cursor paging.
- Produces: `load_mql_entries(start: date, end: date) -> pd.DataFrame` with columns `hs_id`, `email`, `mql_entered_at` (ISO string), `lifecycle_stage`, `typeform_asset_download`, `createdate`.

- [ ] **Step 1: Add the property constant to config**

In `dashboard/config.py`, directly below `HS_LIFECYCLE_MQL_VALUE`:

```python
# Date a contact entered the Marketing Qualified Lead lifecycle stage.
# This is the Callable MQL source, NOT lifecyclestage. lifecyclestage
# ratchets forward, so a contact promoted to salesqualifiedlead stops
# reading as MQL; this property is stamped once and never moves.
# Verified 2026-08-28: filterable server-side, 189 entries in 60 days,
# 98% stamp rate for contacts created in-window who booked a discovery call.
HS_PROP_MQL_ENTERED = "hs_v2_date_entered_marketingqualifiedlead"
```

- [ ] **Step 2: Add the loader**

Append to `dashboard/data/hubspot_loader.py`:

```python
@st.cache_data(ttl=900, show_spinner="Loading callable MQLs...")
def load_mql_entries(start: date, end: date) -> pd.DataFrame:
    """Return contacts that ENTERED the MQL lifecycle stage in the window.

    Callable MQL for the PAID MEDIA tab. Filters on the v2 stage-entry
    timestamp rather than current lifecyclestage: lifecyclestage ratchets
    forward, so counting it would both undercount (a contact promoted to
    salesqualifiedlead no longer reads as MQL) and rewrite history on every
    refresh.

    Columns: hs_id, email, mql_entered_at, lifecycle_stage,
             typeform_asset_download, createdate
    """
    token = st.secrets["HUBSPOT_TOKEN"]
    start_ms = int(datetime.combine(start, datetime.min.time(),
                                    tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end, datetime.max.time(),
                                  tzinfo=timezone.utc).timestamp() * 1000)
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": cfg.HS_PROP_MQL_ENTERED,
                 "operator": "BETWEEN",
                 "value": start_ms, "highValue": end_ms},
            ]
        }],
        "properties": [
            "email", "createdate", cfg.HS_PROP_MQL_ENTERED,
            cfg.HS_PROP_LIFECYCLE_STAGE, cfg.HS_PROP_TYPEFORM_ASSET,
            "firstname", "lastname",
        ],
        "limit": 100,
    }
    results = _hs_search(token, "contacts", body)

    rows = []
    for r in results:
        p = r.get("properties", {})
        _fn = (p.get("firstname") or "").strip().lower()
        _ln = (p.get("lastname") or "").strip().lower()
        if _fn == "test" or _ln == "test":
            continue
        _em = (p.get("email") or "").strip().lower()
        if _em in cfg.MARKETING_EXCLUDED_EMAILS:
            continue
        rows.append({
            "hs_id": r.get("id"),
            "email": _em,
            "mql_entered_at": p.get(cfg.HS_PROP_MQL_ENTERED),
            "lifecycle_stage": p.get(cfg.HS_PROP_LIFECYCLE_STAGE),
            "typeform_asset_download": p.get(cfg.HS_PROP_TYPEFORM_ASSET),
            "createdate": p.get("createdate"),
        })
    return pd.DataFrame(rows, columns=[
        "hs_id", "email", "mql_entered_at", "lifecycle_stage",
        "typeform_asset_download", "createdate",
    ])
```

- [ ] **Step 3: Probe it against live data**

Write to the scratchpad as `probe_mql_loader.py` and run from repo root with `python <scratchpad>/probe_mql_loader.py`:

```python
import sys
from datetime import date, timedelta
sys.path.insert(0, ".")
from dashboard.data.hubspot_loader import load_mql_entries

W = lambda fn: getattr(fn, "__wrapped__", fn)
END = date.today()
START = END - timedelta(days=60)
df = W(load_mql_entries)(START, END)
print(f"rows={len(df)}  columns={list(df.columns)}")
print(f"null mql_entered_at: {df['mql_entered_at'].isna().sum()}")
print(f"distinct lifecycle stages: {sorted(df['lifecycle_stage'].dropna().unique())}")
print(df.head(3).to_string())
```

Expected: roughly 189 rows for a 60-day window, zero null `mql_entered_at`, and lifecycle stages including values PAST `marketingqualifiedlead` such as `salesqualifiedlead` and `opportunity`. Seeing later stages is the point: it proves the ratchet problem is solved.

- [ ] **Step 4: Commit**

```bash
git add dashboard/config.py dashboard/data/hubspot_loader.py
git commit -m "feat(loader): load_mql_entries by MQL stage-entry date"
```

---

### Task 2: Segment resolution

**Files:**
- Modify: `dashboard/config.py`
- Create: `dashboard/data/paid_mql.py`
- Test: `dashboard/tests/test_paid_mql.py`

**Interfaces:**
- Consumes: `dashboard.data.groups.match_group(name) -> str | None`, already present.
- Produces: `resolve_segment(campaign_name: str, *, segment_rollup: dict[str, str], unmatched_label: str = "(unmatched)") -> str`.

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_paid_mql.py`:

```python
"""Tests for the PAID MEDIA tab's pure rollup logic."""
import pytest

from dashboard.data.paid_mql import resolve_segment

ROLLUP = {"EMX": "Event", "Practice Growth Workshop": "Event"}


@pytest.mark.parametrize("campaign,expected", [
    ("DS | EMX 2026 Kansas City Mixed Funnel Setup", "Event"),
    ("DS | __Practice Growth Workshop Dallas__ Funnel Setup", "Event"),
    ("DS | __Chiro__ Mixed Funnel Setup | CBO | USA", "Chiro"),
    ("DS | __NLAP__ Funnel Setup | CBO | USA", "NLAP"),
    ("DS | __Theraray__ Funnel Setup | CBO | USA", "TheraRay"),
    ("DS | MAP Protocol Funnel Setup | CBO | USA", "MAP"),
])
def test_resolve_segment(campaign, expected):
    assert resolve_segment(campaign, segment_rollup=ROLLUP) == expected


def test_unrecognized_campaign_is_flagged_not_dropped():
    """A new campaign whose name we do not recognize must surface as a
    tripwire row. Silently dropping it is how MAP spend went unreported."""
    assert resolve_segment("Brand New Thing 2027",
                           segment_rollup=ROLLUP) == "(unmatched)"


def test_empty_campaign_name_is_unmatched():
    assert resolve_segment("", segment_rollup=ROLLUP) == "(unmatched)"
    assert resolve_segment(None, segment_rollup=ROLLUP) == "(unmatched)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dashboard.data.paid_mql'`

- [ ] **Step 3: Add the config constants**

In `dashboard/config.py`, directly below the `EMX_PARENT` line:

```python
# --- PAID MEDIA tab (2026-08-28) ---
# Segment roll-up for the PAID MEDIA tab ONLY. Existing tabs keep their own
# group labels; this must not disturb the EMX-into-Chiro roll-in the weekly
# metrics depend on.
SEGMENT_ROLLUP: dict[str, str] = {
    "EMX": "Event",
    "Practice Growth Workshop": "Event",
}

# Creative Tracker. 500 ads delivered in the trailing 90 days but only 37
# cleared $500, and the reference deck shows 16 rows, so a floor is required
# for the table to be readable.
CREATIVE_SPEND_FLOOR: float = 500.0
# An ad is a Winner at 25% below its own segment's average cost per callable
# MQL, Stand Out between 10% and 25% below. Scored per segment so a Chiro ad
# is judged against Chiro, not against NLAP.
CREATIVE_WINNER_PCT: float = 0.25
CREATIVE_STANDOUT_PCT: float = 0.10
# Volume guard. Without it, one callable MQL on $600 of spend scores as a
# Winner on noise alone.
CREATIVE_MIN_MQL: int = 3
```

- [ ] **Step 4: Write the minimal implementation**

Create `dashboard/data/paid_mql.py`:

```python
"""Pure rollup logic for the PAID MEDIA tab. No I/O.

Config values arrive as parameters rather than imports, matching the
convention in reconcile.py and paid_media.py, so every function here is
testable without touching Streamlit secrets or any API.

Spec: docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md
"""
from __future__ import annotations

from dashboard.data.groups import match_group

UNMATCHED = "(unmatched)"


def _safe_div(num: float, den: float) -> float | None:
    """None on a zero denominator, never 0. A zero denominator and a genuine
    zero are different facts and must render differently."""
    if not den:
        return None
    return num / den


def resolve_segment(campaign_name, *, segment_rollup: dict[str, str],
                    unmatched_label: str = UNMATCHED) -> str:
    """Map an FB campaign name to a PAID MEDIA segment.

    Applies the existing CAMPAIGN_GROUPS match, then folds groups into their
    roll-up segment (EMX and Practice Growth Workshop both become Event).
    A campaign matching nothing returns the unmatched label rather than None,
    so it surfaces as a visible row instead of vanishing.
    """
    if not campaign_name:
        return unmatched_label
    group = match_group(campaign_name)
    if not group:
        return unmatched_label
    return segment_rollup.get(group, group)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: 163 passed (155 existing + 8 new).

- [ ] **Step 7: Commit**

```bash
git add dashboard/config.py dashboard/data/paid_mql.py dashboard/tests/test_paid_mql.py
git commit -m "feat(paid-media): segment resolution with unmatched tripwire"
```

---

### Task 3: Daily MQL summary rollup

**Files:**
- Modify: `dashboard/data/paid_mql.py`
- Test: `dashboard/tests/test_paid_mql.py`

**Interfaces:**
- Consumes: `resolve_segment` from Task 2.
- Produces: `daily_mql_summary(fb_daily, leads, mql_entries, *, segment_rollup, segments=None) -> pd.DataFrame` with columns `date`, `leads`, `callable_mql`, `lead_to_callable_pct`, `cost_per_lead`, `cost_per_callable_mql`, plus a final `Total` row where `date` is the string `"Total"`.

Input frames:
- `fb_daily`: columns `date_start` (ISO date string), `campaign_name`, `spend`
- `leads`: columns `email`, `lead_date` (ISO date string), `typeform_asset_download`, `segment`
- `mql_entries`: columns `email`, `mql_date` (ISO date string), `segment`

Dating is **by event**, per the spec: a lead counts on the day it was created, an MQL counts on the day it entered MQL, and these are often different days for the same contact. Once a day passes its row never changes.

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_paid_mql.py`:

```python
import pandas as pd

from dashboard.data.paid_mql import daily_mql_summary


def _fb(rows):
    return pd.DataFrame(rows, columns=["date_start", "campaign_name", "spend"])


def _leads(rows):
    return pd.DataFrame(rows, columns=["email", "lead_date", "segment"])


def _mqls(rows):
    return pd.DataFrame(rows, columns=["email", "mql_date", "segment"])


CHIRO = "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"


def test_daily_summary_is_activity_dated():
    """A lead arriving 08-20 that becomes an MQL on 08-24 counts on TWO
    different rows. This is the whole point of activity dating: each day's
    row stops moving once the day has passed."""
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0), ("2026-08-24", CHIRO, 50.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro")]),
        _mqls([("a@x.com", "2026-08-24", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    rows = out[out["date"] != "Total"].set_index("date")
    assert rows.loc["2026-08-20", "leads"] == 1
    assert rows.loc["2026-08-20", "callable_mql"] == 0
    assert rows.loc["2026-08-24", "leads"] == 0
    assert rows.loc["2026-08-24", "callable_mql"] == 1


def test_daily_summary_costs():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 200.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("b@x.com", "2026-08-20", "Chiro")]),
        _mqls([("a@x.com", "2026-08-20", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["cost_per_lead"] == 100.0
    assert row["cost_per_callable_mql"] == 200.0
    assert row["lead_to_callable_pct"] == 0.5


def test_daily_summary_zero_denominator_is_none_not_zero():
    """Spend with no leads must render as a dash, not as $0.00, which would
    read as free leads."""
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 200.0)]),
        _leads([]), _mqls([]), segment_rollup=ROLLUP,
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["cost_per_lead"] is None
    assert row["cost_per_callable_mql"] is None
    assert row["lead_to_callable_pct"] is None


def test_daily_summary_total_row():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0), ("2026-08-21", CHIRO, 300.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("b@x.com", "2026-08-21", "Chiro")]),
        _mqls([("a@x.com", "2026-08-20", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    total = out[out["date"] == "Total"].iloc[0]
    assert total["leads"] == 2
    assert total["callable_mql"] == 1
    assert total["cost_per_lead"] == 200.0
    # Total ratios are computed from totals, NOT averaged across rows.
    assert total["cost_per_callable_mql"] == 400.0


def test_daily_summary_segment_filter():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0),
             ("2026-08-20", "DS | __NLAP__ Funnel Setup", 900.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("n@x.com", "2026-08-20", "NLAP")]),
        _mqls([]), segment_rollup=ROLLUP, segments=("Chiro",),
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["leads"] == 1
    assert row["cost_per_lead"] == 100.0


def test_daily_summary_row_per_calendar_day_sorted():
    out = daily_mql_summary(
        _fb([("2026-08-21", CHIRO, 10.0), ("2026-08-20", CHIRO, 10.0)]),
        _leads([]), _mqls([]), segment_rollup=ROLLUP,
    )
    dates = [d for d in out["date"] if d != "Total"]
    assert dates == ["2026-08-20", "2026-08-21"]
    assert out["date"].iloc[-1] == "Total"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: FAIL with `ImportError: cannot import name 'daily_mql_summary'`

- [ ] **Step 3: Write the implementation**

Append to `dashboard/data/paid_mql.py`:

```python
import pandas as pd

DAILY_COLUMNS = ["date", "leads", "callable_mql", "lead_to_callable_pct",
                 "cost_per_lead", "cost_per_callable_mql"]


def daily_mql_summary(fb_daily: pd.DataFrame,
                      leads: pd.DataFrame,
                      mql_entries: pd.DataFrame,
                      *,
                      segment_rollup: dict[str, str],
                      segments: tuple[str, ...] | None = None,
                      ) -> pd.DataFrame:
    """One row per calendar day, ACTIVITY dated, plus a Total row.

    A lead counts on the day it was created; a callable MQL counts on the day
    it entered MQL. For one contact those are usually different days. That is
    intentional: it keeps every past row frozen, which is what makes this the
    morning operations read.

    lead_to_callable_pct on a single row is therefore a ratio of two counts
    over the same day, NOT a cohort conversion rate. The segment table is
    where true conversion lives.
    """
    fb = fb_daily.copy() if fb_daily is not None else pd.DataFrame()
    lds = leads.copy() if leads is not None else pd.DataFrame()
    mqs = mql_entries.copy() if mql_entries is not None else pd.DataFrame()

    if not fb.empty:
        fb["segment"] = fb["campaign_name"].apply(
            lambda n: resolve_segment(n, segment_rollup=segment_rollup))
    if segments is not None:
        keep = set(segments)
        if not fb.empty:
            fb = fb[fb["segment"].isin(keep)]
        if not lds.empty:
            lds = lds[lds["segment"].isin(keep)]
        if not mqs.empty:
            mqs = mqs[mqs["segment"].isin(keep)]

    spend_by_day = (fb.groupby("date_start")["spend"].sum().to_dict()
                    if not fb.empty else {})
    leads_by_day = (lds.groupby("lead_date")["email"].nunique().to_dict()
                    if not lds.empty else {})
    mql_by_day = (mqs.groupby("mql_date")["email"].nunique().to_dict()
                  if not mqs.empty else {})

    days = sorted(set(spend_by_day) | set(leads_by_day) | set(mql_by_day))
    rows = []
    for d in days:
        spend = float(spend_by_day.get(d, 0.0))
        n_leads = int(leads_by_day.get(d, 0))
        n_mql = int(mql_by_day.get(d, 0))
        rows.append({
            "date": d,
            "leads": n_leads,
            "callable_mql": n_mql,
            "lead_to_callable_pct": _safe_div(n_mql, n_leads),
            "cost_per_lead": _safe_div(spend, n_leads),
            "cost_per_callable_mql": _safe_div(spend, n_mql),
        })

    tot_spend = float(sum(spend_by_day.values()))
    tot_leads = int(sum(leads_by_day.values()))
    tot_mql = int(sum(mql_by_day.values()))
    rows.append({
        "date": "Total",
        "leads": tot_leads,
        "callable_mql": tot_mql,
        # Ratios come from the totals, never from averaging the per-day
        # ratios, which would weight a $10 day the same as a $3,000 day.
        "lead_to_callable_pct": _safe_div(tot_mql, tot_leads),
        "cost_per_lead": _safe_div(tot_spend, tot_leads),
        "cost_per_callable_mql": _safe_div(tot_spend, tot_mql),
    })
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/paid_mql.py dashboard/tests/test_paid_mql.py
git commit -m "feat(paid-media): activity-dated daily MQL summary"
```

---

### Task 4: Segment results rollup

**Files:**
- Modify: `dashboard/data/paid_mql.py`
- Test: `dashboard/tests/test_paid_mql.py`

**Interfaces:**
- Consumes: `resolve_segment`, `_safe_div`.
- Produces: `segment_results(fb, leads, mql_emails, call_emails, sale_emails, commissions_by_segment, *, segment_rollup) -> pd.DataFrame` with columns `segment`, `spend`, `leads`, `callable_mql`, `cost_cmql`, `lead_to_callable_pct`, `calls`, `cost_per_call`, `callable_to_call_pct`, `sales`, `call_to_sale_pct`, `cost_per_close`, `segment_cac`, plus a `Total` row.

This table is **cohort dated**: every count is attributed to the lead that generated it, and counted in the window that lead arrived in. `mql_emails`, `call_emails` and `sale_emails` are sets of lead emails that reached that stage at any time, so the caller does the windowing on leads and passes through the downstream sets.

Segment CAC mirrors the existing `blended_cac` in `executive.py`: `(spend + close commissions) / sales`. It excludes payroll, exactly as `blended_cac` does. The misnamed `cac_full` in `reconcile.py` is ad spend plus payroll with no commissions and returns `None`; do not copy it.

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_paid_mql.py`:

```python
from dashboard.data.paid_mql import segment_results

NLAP = "DS | __NLAP__ Funnel Setup | CBO | USA"


def _seg_fb(rows):
    return pd.DataFrame(rows, columns=["campaign_name", "spend"])


def _seg_leads(rows):
    return pd.DataFrame(rows, columns=["email", "segment"])


def test_segment_results_full_funnel():
    out = segment_results(
        _seg_fb([(CHIRO, 1000.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("b@x.com", "Chiro"),
                    ("c@x.com", "Chiro"), ("d@x.com", "Chiro")]),
        mql_emails={"a@x.com", "b@x.com"},
        call_emails={"a@x.com"},
        sale_emails={"a@x.com"},
        commissions_by_segment={"Chiro": 2500.0},
        segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "Chiro"].iloc[0]
    assert row["spend"] == 1000.0
    assert row["leads"] == 4
    assert row["callable_mql"] == 2
    assert row["calls"] == 1
    assert row["sales"] == 1
    assert row["lead_to_callable_pct"] == 0.5
    assert row["callable_to_call_pct"] == 0.5
    assert row["call_to_sale_pct"] == 1.0
    assert row["cost_cmql"] == 500.0
    assert row["cost_per_call"] == 1000.0
    assert row["cost_per_close"] == 1000.0
    # Segment CAC = (spend + commissions) / sales, mirroring blended_cac.
    assert row["segment_cac"] == 3500.0


def test_segment_results_event_rollup():
    """EMX and Practice Growth Workshop collapse into one Event row."""
    out = segment_results(
        _seg_fb([("DS | EMX 2026 Kansas City", 700.0),
                 ("DS | __Practice Growth Workshop Dallas__", 300.0)]),
        _seg_leads([("a@x.com", "Event")]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    segs = set(out["segment"])
    assert "Event" in segs
    assert "EMX" not in segs and "Practice Growth Workshop" not in segs
    assert out[out["segment"] == "Event"].iloc[0]["spend"] == 1000.0


def test_segment_results_spend_only_segment_still_appears():
    """A segment that spent money but produced no leads must show up with a
    dash, not be dropped. Vanishing is how MAP stayed invisible."""
    out = segment_results(
        _seg_fb([(NLAP, 5000.0)]), _seg_leads([]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "NLAP"].iloc[0]
    assert row["spend"] == 5000.0
    assert row["leads"] == 0
    assert row["cost_cmql"] is None
    assert row["cost_per_close"] is None


def test_segment_results_zero_spend_segment_is_omitted():
    """PT Recovery has spent $0 for 60 days. It should not clutter the table,
    but it must reappear automatically if spend resumes."""
    out = segment_results(
        _seg_fb([(CHIRO, 100.0), ("DS | __PT__ Recovery", 0.0)]),
        _seg_leads([]), mql_emails=set(), call_emails=set(),
        sale_emails=set(), commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    assert "PT Recovery" not in set(out["segment"])


def test_segment_results_total_row_uses_totals_not_averages():
    out = segment_results(
        _seg_fb([(CHIRO, 1000.0), (NLAP, 3000.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("n@x.com", "NLAP")]),
        mql_emails={"a@x.com"}, call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    total = out[out["segment"] == "Total"].iloc[0]
    assert total["spend"] == 4000.0
    assert total["leads"] == 2
    assert total["callable_mql"] == 1
    assert total["cost_cmql"] == 4000.0
    assert out["segment"].iloc[-1] == "Total"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: FAIL with `ImportError: cannot import name 'segment_results'`

- [ ] **Step 3: Write the implementation**

Append to `dashboard/data/paid_mql.py`:

```python
SEGMENT_COLUMNS = ["segment", "spend", "leads", "callable_mql", "cost_cmql",
                   "lead_to_callable_pct", "calls", "cost_per_call",
                   "callable_to_call_pct", "sales", "call_to_sale_pct",
                   "cost_per_close", "segment_cac"]


def segment_results(fb: pd.DataFrame,
                    leads: pd.DataFrame,
                    mql_emails: set[str],
                    call_emails: set[str],
                    sale_emails: set[str],
                    commissions_by_segment: dict[str, float],
                    *,
                    segment_rollup: dict[str, str],
                    ) -> pd.DataFrame:
    """One row per segment, COHORT dated, plus a Total row.

    Every downstream count is attributed to the lead that generated it, so
    spend is matched to the leads it actually bought. Because closes lag lead
    arrival, sales and both cost-per-close columns read low on recent windows.
    That is inherent to cohort dating and is surfaced on the page rather than
    engineered around.

    segment_cac mirrors the existing blended_cac: (spend + close commissions)
    / sales. Payroll is excluded, exactly as blended_cac excludes it.
    """
    fb = fb.copy() if fb is not None else pd.DataFrame()
    lds = leads.copy() if leads is not None else pd.DataFrame()

    if not fb.empty:
        fb["segment"] = fb["campaign_name"].apply(
            lambda n: resolve_segment(n, segment_rollup=segment_rollup))
        spend_by_seg = fb.groupby("segment")["spend"].sum().to_dict()
    else:
        spend_by_seg = {}
    # A segment with no spend at all is dormant and is omitted. It reappears
    # automatically the moment spend resumes, because rows are enumerated
    # from the data rather than hardcoded.
    spend_by_seg = {k: float(v) for k, v in spend_by_seg.items() if v}

    leads_by_seg: dict[str, set[str]] = {}
    if not lds.empty:
        for seg, grp in lds.groupby("segment"):
            leads_by_seg[seg] = set(grp["email"].dropna())

    rows = []
    for seg in sorted(set(spend_by_seg) | set(leads_by_seg)):
        spend = spend_by_seg.get(seg, 0.0)
        emails = leads_by_seg.get(seg, set())
        n_leads = len(emails)
        n_mql = len(emails & mql_emails)
        n_call = len(emails & call_emails)
        n_sale = len(emails & sale_emails)
        commission = float(commissions_by_segment.get(seg, 0.0))
        rows.append({
            "segment": seg,
            "spend": spend,
            "leads": n_leads,
            "callable_mql": n_mql,
            "cost_cmql": _safe_div(spend, n_mql),
            "lead_to_callable_pct": _safe_div(n_mql, n_leads),
            "calls": n_call,
            "cost_per_call": _safe_div(spend, n_call),
            "callable_to_call_pct": _safe_div(n_call, n_mql),
            "sales": n_sale,
            "call_to_sale_pct": _safe_div(n_sale, n_call),
            "cost_per_close": _safe_div(spend, n_sale),
            "segment_cac": _safe_div(spend + commission, n_sale),
        })

    all_emails = set().union(*leads_by_seg.values()) if leads_by_seg else set()
    t_spend = float(sum(spend_by_seg.values()))
    t_leads = len(all_emails)
    t_mql = len(all_emails & mql_emails)
    t_call = len(all_emails & call_emails)
    t_sale = len(all_emails & sale_emails)
    t_comm = float(sum(commissions_by_segment.values()))
    rows.append({
        "segment": "Total",
        "spend": t_spend,
        "leads": t_leads,
        "callable_mql": t_mql,
        "cost_cmql": _safe_div(t_spend, t_mql),
        "lead_to_callable_pct": _safe_div(t_mql, t_leads),
        "calls": t_call,
        "cost_per_call": _safe_div(t_spend, t_call),
        "callable_to_call_pct": _safe_div(t_call, t_mql),
        "sales": t_sale,
        "call_to_sale_pct": _safe_div(t_sale, t_call),
        "cost_per_close": _safe_div(t_spend, t_sale),
        "segment_cac": _safe_div(t_spend + t_comm, t_sale),
    })
    return pd.DataFrame(rows, columns=SEGMENT_COLUMNS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: PASS, 19 tests.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: 174 passed.

- [ ] **Step 6: Commit**

```bash
git add dashboard/data/paid_mql.py dashboard/tests/test_paid_mql.py
git commit -m "feat(paid-media): cohort-dated segment results with segment CAC"
```

---

### Task 5: PAID MEDIA tab rendering, tables 1 and 2

**Files:**
- Create: `dashboard/sections/paid_media.py`
- Modify: `dashboard/app.py:15-18` (imports) and `dashboard/app.py:91-104` (tab wiring)

**Interfaces:**
- Consumes: `daily_mql_summary`, `segment_results`, `resolve_segment` from `paid_mql`; `load_fb_insights`, `load_marketing_contacts`, `load_mql_entries`, `load_meetings_in_window`, `load_closed_deals_in_window`; `build_closed_deals_table` and `compute_close_commissions` from `reconcile`.
- Produces: `render_paid_media(start_date: date, end_date: date) -> None`.

This task ships a **working two-table tab**. Stop here and review before starting Task 6.

- [ ] **Step 1: Create the section module**

Create `dashboard/sections/paid_media.py`:

```python
"""PAID MEDIA tab: daily MQL summary and per-segment funnel economics.

Two different dating conventions live on this page ON PURPOSE, and each
table says which it uses:
  - Daily MQL Summary is ACTIVITY dated, so past rows never move.
  - Results by Segment is COHORT dated, so spend matches the leads it bought.
Confusing the two produces wrong conclusions, hence the visible captions.

Spec: docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.hubspot_loader import (
    load_closed_deals_in_window, load_deal_contacts, load_marketing_contacts,
    load_meetings_in_window, load_mql_entries,
)
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.paid_mql import (
    daily_mql_summary, resolve_segment, segment_results,
)
from dashboard.data.reconcile import (
    DISCOVERY_MEETING_SUBSTRINGS, build_closed_deals_table,
    compute_close_commissions,
)


def _dash(v, kind: str = "money") -> str:
    """None means the denominator was zero. Render a dash, never $0.00,
    which would read as 'free'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    if kind == "money":
        return f"${v:,.2f}"
    if kind == "pct":
        return f"{v:.1%}"
    return f"{v:,.0f}"


def _iso_day(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)[:10]


def render_paid_media(start_date: date, end_date: date) -> None:
    st.header("Paid Media")
    st.caption(
        f"Window {start_date} to {end_date}. Data refreshes every 15 minutes; "
        "use Refresh data to clear the cache."
    )

    fb_daily = load_fb_insights(start_date, end_date, time_increment_days=1)
    fb_window = load_fb_insights(start_date, end_date)
    contacts = load_marketing_contacts(start_date, end_date)
    mqls = load_mql_entries(start_date, end_date)
    meetings = load_meetings_in_window(start_date, end_date)

    # Leads carry their segment from the typeform asset, which is the best
    # lead attribution available and identifies the funnel they came from.
    leads = pd.DataFrame({
        "email": contacts["email"].fillna("").str.strip().str.lower(),
        "lead_date": contacts["recent_conversion_date"].apply(_iso_day),
        "segment": contacts["typeform_asset_download"].map(
            cfg.ASSET_TO_GROUP).map(
            lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
    }).dropna(subset=["lead_date"])
    leads = leads[leads["email"] != ""]

    mql_frame = pd.DataFrame({
        "email": mqls["email"].fillna("").str.strip().str.lower(),
        "mql_date": mqls["mql_entered_at"].apply(_iso_day),
        "segment": mqls["typeform_asset_download"].map(
            cfg.ASSET_TO_GROUP).map(
            lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
    }).dropna(subset=["mql_date"])
    mql_frame = mql_frame[mql_frame["email"] != ""]

    # --- Table 1 ---
    st.subheader("Daily MQL Summary")
    st.caption(
        "Dated by event: a lead counts the day it arrived, a callable MQL "
        "counts the day it entered MQL. Past rows never change. Lead to "
        "Callable % on a single row is a ratio of that day's two counts, not "
        "a cohort conversion rate."
    )
    available = sorted({s for s in leads["segment"].dropna().unique()}
                       | {resolve_segment(n, segment_rollup=cfg.SEGMENT_ROLLUP)
                          for n in fb_window["campaign_name"].dropna()})
    picked = st.multiselect("Segments", available, default=available,
                            key="paid_media_segments")

    daily = daily_mql_summary(
        fb_daily, leads, mql_frame,
        segment_rollup=cfg.SEGMENT_ROLLUP,
        segments=tuple(picked) if picked else None,
    )
    st.dataframe(pd.DataFrame({
        "Date": daily["date"],
        "Leads": daily["leads"].map(lambda v: _dash(v, "int")),
        "Callable MQL": daily["callable_mql"].map(lambda v: _dash(v, "int")),
        "Lead to Callable %": daily["lead_to_callable_pct"].map(
            lambda v: _dash(v, "pct")),
        "Cost Per Lead": daily["cost_per_lead"].map(_dash),
        "Cost Per Callable MQL": daily["cost_per_callable_mql"].map(_dash),
    }), use_container_width=True, hide_index=True)

    # --- Table 2 ---
    st.subheader("Results by Segment")
    st.caption(
        "Dated by lead cohort: spend is matched to the leads it bought. "
        "Because closes lag lead arrival, Sales and both cost-per-close "
        "columns read low on recent windows. Money columns are acquisition "
        "cost only; revenue and ROAS are omitted because every closed-won "
        "deal in HubSpot carries an identical $40,000 placeholder amount."
    )

    disco = meetings[meetings["activity_type"].fillna("").str.lower().apply(
        lambda s: any(sub in s for sub in DISCOVERY_MEETING_SUBSTRINGS))]
    email_by_id = dict(zip(contacts["hs_id"].astype(str),
                           contacts["email"].fillna("").str.strip().str.lower()))
    call_emails = {email_by_id.get(str(c)) for c in disco["contact_id"].dropna()}
    call_emails.discard(None)
    call_emails.discard("")

    deals = load_closed_deals_in_window(
        start_date, end_date,
        tuple(cfg.STAGES_CLOSED_WON),
        tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE),
    )
    # The deal-to-contact associations are REQUIRED, not optional. Passing an
    # empty frame here makes build_closed_deals_table produce a table with no
    # contact linkage, so sale_emails comes back empty and every Sales cell
    # silently reads 0 while looking perfectly healthy.
    contact_deals = (load_deal_contacts(tuple(deals["deal_id"].astype(str)))
                     if not deals.empty else
                     pd.DataFrame(columns=["contact_id", "deal_id"]))
    try:
        deals_table = build_closed_deals_table(
            deals, contact_deals, contacts,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
            stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        )
    except Exception as e:  # noqa: BLE001
        st.warning(f"Closed-deal attribution unavailable: {e}")
        deals_table = pd.DataFrame()

    # Sales are counted cohort-style: of the leads that arrived in this
    # window, how many closed. So resolving deal contacts against the
    # in-window contact frame is correct, not a shortcut. A closed deal whose
    # contact arrived before the window is intentionally not counted here.
    sale_emails: set[str] = set()
    if not contact_deals.empty:
        for cid in contact_deals["contact_id"].dropna().astype(str):
            em = email_by_id.get(cid)
            if em:
                sale_emails.add(em)

    commissions_by_segment: dict[str, float] = {}
    if not deals_table.empty and "group" in deals_table.columns:
        for grp, sub in deals_table.groupby("group"):
            seg = cfg.SEGMENT_ROLLUP.get(grp, grp)
            comm = compute_close_commissions(
                sub,
                sdr_close=cfg.SDR_CLOSE_COMMISSION,
                bds_close=cfg.BDS_CLOSE_COMMISSION,
                sme_close=cfg.SME_CLOSE_COMMISSION,
                flat_close=cfg.FLAT_CLOSE_COMMISSION,
            )
            commissions_by_segment[seg] = (
                commissions_by_segment.get(seg, 0.0) + comm["total"])

    seg_df = segment_results(
        fb_window, leads.rename(columns={"lead_date": "_d"})[["email", "segment"]],
        mql_emails=set(mql_frame["email"]),
        call_emails=call_emails,
        sale_emails=sale_emails,
        commissions_by_segment=commissions_by_segment,
        segment_rollup=cfg.SEGMENT_ROLLUP,
    )
    st.dataframe(pd.DataFrame({
        "Segment": seg_df["segment"],
        "Spend": seg_df["spend"].map(_dash),
        "Leads": seg_df["leads"].map(lambda v: _dash(v, "int")),
        "Callable MQL": seg_df["callable_mql"].map(lambda v: _dash(v, "int")),
        "Cost CMQL": seg_df["cost_cmql"].map(_dash),
        "Lead to Callable %": seg_df["lead_to_callable_pct"].map(
            lambda v: _dash(v, "pct")),
        "Calls": seg_df["calls"].map(lambda v: _dash(v, "int")),
        "Cost per Call": seg_df["cost_per_call"].map(_dash),
        "Callable to Call %": seg_df["callable_to_call_pct"].map(
            lambda v: _dash(v, "pct")),
        "Sales": seg_df["sales"].map(lambda v: _dash(v, "int")),
        "Call to Sale %": seg_df["call_to_sale_pct"].map(
            lambda v: _dash(v, "pct")),
        "Cost per Close": seg_df["cost_per_close"].map(_dash),
        "Segment CAC": seg_df["segment_cac"].map(_dash),
    }), use_container_width=True, hide_index=True)

    if "(unmatched)" in set(seg_df["segment"]):
        st.warning(
            "An (unmatched) row is present: a campaign is running whose name "
            "matches no segment pattern in CAMPAIGN_GROUPS. Its spend is "
            "reported but its leads are not attributed. Add the pattern to "
            "config.CAMPAIGN_GROUPS and the matching typeform label to "
            "config.ASSET_TO_GROUP."
        )
```

- [ ] **Step 2: Wire the tab into app.py**

In `dashboard/app.py`, add to the imports block at lines 15-18:

```python
from dashboard.sections.paid_media import render_paid_media
```

Replace lines 91-104 with:

```python
tab_executive, tab_sales, tab_paid, tab_metrics, tab_commissions = st.tabs(
    ["EXECUTIVE", "SALES", "PAID MEDIA", "METRICS", "COMMISSIONS"])

with tab_executive:
    render_executive(start_date, end_date)

with tab_sales:
    render_sales(start_date, end_date)

with tab_paid:
    render_paid_media(start_date, end_date)

with tab_metrics:
    render_metrics()

with tab_commissions:
    render_commissions(start_date, end_date)
```

Note: read the existing `st.tabs([...])` label list at line 91-93 before replacing, and preserve any label text that differs from the above.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: 174 passed. No test touches rendering, so this is a regression check on the imports.

- [ ] **Step 4: Smoke-test the render path off-Streamlit**

Rendering bugs (an `UnboundLocalError` that crashed a whole tab) have repeatedly slipped past unit tests on this project. Write to the scratchpad as `probe_render_paid_media.py` and run from repo root:

```python
import sys
from datetime import date, timedelta
sys.path.insert(0, ".")
import dashboard.sections.paid_media as pm

# Exercise every pure path the renderer calls, with real loaded data, so a
# NameError or a column-name typo surfaces here instead of on the deployed app.
W = lambda fn: getattr(fn, "__wrapped__", fn)
END = date.today()
START = END - timedelta(days=30)

from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import load_marketing_contacts, load_mql_entries
from dashboard.data.paid_mql import daily_mql_summary, segment_results
from dashboard import config as cfg
import pandas as pd

fb_daily = W(load_fb_insights)(START, END, time_increment_days=1)
fb_win = W(load_fb_insights)(START, END)
contacts = W(load_marketing_contacts)(START, END)
mqls = W(load_mql_entries)(START, END)

leads = pd.DataFrame({
    "email": contacts["email"].fillna("").str.strip().str.lower(),
    "lead_date": contacts["recent_conversion_date"].apply(pm._iso_day),
    "segment": contacts["typeform_asset_download"].map(cfg.ASSET_TO_GROUP).map(
        lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
}).dropna(subset=["lead_date"])
mqf = pd.DataFrame({
    "email": mqls["email"].fillna("").str.strip().str.lower(),
    "mql_date": mqls["mql_entered_at"].apply(pm._iso_day),
    "segment": mqls["typeform_asset_download"].map(cfg.ASSET_TO_GROUP).map(
        lambda g: cfg.SEGMENT_ROLLUP.get(g, g) if g else None),
}).dropna(subset=["mql_date"])

daily = daily_mql_summary(fb_daily, leads, mqf, segment_rollup=cfg.SEGMENT_ROLLUP)
print(daily.tail(8).to_string(index=False))
seg = segment_results(fb_win, leads[["email", "segment"]],
                      mql_emails=set(mqf["email"]), call_emails=set(),
                      sale_emails=set(), commissions_by_segment={},
                      segment_rollup=cfg.SEGMENT_ROLLUP)
print(seg.to_string(index=False))
```

Expected: a daily table whose Total row leads count is in the same range as the METRICS tab daily summary, and a segment table listing Event, Chiro, NLAP, TheraRay and MAP with non-zero spend. **MAP must appear with non-zero spend.** If `(unmatched)` appears, a new campaign has launched since 2026-08-28 and needs a `CAMPAIGN_GROUPS` pattern.

- [ ] **Step 5: Commit and push**

```bash
git add dashboard/sections/paid_media.py dashboard/app.py
git commit -m "feat(paid-media): PAID MEDIA tab with daily MQL and segment tables"
git push origin feature/cmo-dashboard
```

- [ ] **Step 6: Verify the deploy**

Wait for the Streamlit Cloud redeploy (1 to 2 minutes) and confirm the PAID MEDIA tab renders both tables without an exception. A stale view right after a push is usually deploy lag; the in-app "Refresh data" button clears the data cache but does NOT load new code.

**STOP HERE FOR REVIEW.** Tasks 1 to 5 are a shippable increment.

---

### Task 6: FB ad-level loaders

**Files:**
- Modify: `dashboard/data/fb_loader.py`

**Interfaces:**
- Produces:
  - `load_fb_ad_insights(start: date, end: date) -> pd.DataFrame` with columns `ad_id`, `ad_name`, `campaign_name`, `spend`, `impressions`, `clicks`, `video_plays`.
  - `load_fb_ad_entities(ad_ids: tuple[str, ...]) -> pd.DataFrame` with columns `ad_id`, `created_time`, `effective_status`, `story_id`.

Two constraints discovered by probe on 2026-08-28 and encoded here:
1. `effective_status` and `creative` are **object fields, not insights fields.** Requesting them in an insights call errors. They need a separate entity pull.
2. Requesting `creative{...}` expansion with `limit=200` returns HTTP 500, "Please reduce the amount of data you're asking for." Page size must be small. Use 25.

- [ ] **Step 1: Add the ad-level insights loader**

Append to `dashboard/data/fb_loader.py`:

```python
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
            continue
        for _aid, node in (r.json() or {}).items():
            rows.append({
                "ad_id": str(node.get("id")),
                "created_time": node.get("created_time"),
                "effective_status": node.get("effective_status"),
                "story_id": (node.get("creative") or {}).get(
                    "effective_object_story_id"),
            })
    return pd.DataFrame(rows, columns=[
        "ad_id", "created_time", "effective_status", "story_id"])
```

- [ ] **Step 2: Probe both loaders**

Write to the scratchpad as `probe_fb_ads.py` and run from repo root:

```python
import sys
from datetime import date, timedelta
sys.path.insert(0, ".")
from dashboard.data.fb_loader import load_fb_ad_insights, load_fb_ad_entities

W = lambda fn: getattr(fn, "__wrapped__", fn)
END = date.today(); START = END - timedelta(days=90)
ins = W(load_fb_ad_insights)(START, END)
print(f"ads={len(ins)}  spend=${ins['spend'].sum():,.0f}")
print(f">= $500: {(ins['spend'] >= 500).sum()}")
print(f"with video plays: {(ins['video_plays'] > 0).sum()}")
top = tuple(ins.nlargest(25, 'spend')['ad_id'])
ents = W(load_fb_ad_entities)(top)
print(f"entities={len(ents)}  with story_id={ents['story_id'].notna().sum()}")
print(ents.head(3).to_string(index=False))
```

Expected: roughly 500 ads, about 37 at or above the $500 floor, a non-zero count with video plays, and 25 entities returned with `created_time` populated on all of them.

- [ ] **Step 3: Commit**

```bash
git add dashboard/data/fb_loader.py
git commit -m "feat(loader): FB ad-level insights and creative entity pulls"
```

---

### Task 7: Hyros ad-id loader

**Files:**
- Modify: `dashboard/data/hyros_loader.py`

**Interfaces:**
- Produces: `load_hyros_leads_with_ads(start: date, end: date) -> pd.DataFrame` with columns `email`, `ad_id`, `created`.

The existing `load_hyros_leads` flattens sources to a label string and drops the ad id, and its `_call` does not paginate at all. Both are blockers for ad-level attribution. The paging scheme (`nextPageId` sent back as `pageId`) was verified per-endpoint in `dashboard/probes/paid_media_hyros_probe.py`; reuse that scheme rather than re-deriving it.

- [ ] **Step 1: Add the loader**

Append to `dashboard/data/hyros_loader.py`:

```python
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
    while True:
        r = requests.get(f"{HYROS_API}/leads", headers={"API-Key": key},
                         params=params, timeout=90)
        r.raise_for_status()
        payload = r.json()
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
        params = nxt
        if seen_pages > 200:  # runaway guard
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
```

- [ ] **Step 2: Probe it**

Write to the scratchpad as `probe_hyros_ads.py` and run from repo root:

```python
import sys
from datetime import date, timedelta
sys.path.insert(0, ".")
from dashboard.data.hyros_loader import load_hyros_leads_with_ads

W = lambda fn: getattr(fn, "__wrapped__", fn)
END = date.today(); START = END - timedelta(days=90)
df = W(load_hyros_leads_with_ads)(START, END)
print(f"rows={len(df)}  with ad_id={df['ad_id'].notna().sum()}  "
      f"distinct ads={df['ad_id'].nunique()}")
print(df.head(5).to_string(index=False))
```

Expected: more rows than a single 250-row page, proving pagination works, and a meaningful share carrying an `ad_id`. Record the unattributed share; it is reported on the page in Task 9, not hidden.

- [ ] **Step 3: Commit**

```bash
git add dashboard/data/hyros_loader.py
git commit -m "feat(loader): Hyros leads retaining FB ad id, with pagination"
```

---

### Task 8: Creative tracker rollup and performance scoring

**Files:**
- Modify: `dashboard/data/paid_mql.py`
- Test: `dashboard/tests/test_paid_mql.py`

**Interfaces:**
- Consumes: `resolve_segment`, `_safe_div`.
- Produces: `creative_tracker(ad_insights, ad_entities, ad_emails, mql_emails, call_emails, sale_emails, *, segment_rollup, spend_floor, winner_pct, standout_pct, min_mql) -> pd.DataFrame` with columns `ad_id`, `ad_name`, `segment`, `format`, `launched`, `status`, `story_id`, `spend`, `callable_mql`, `cost_cmql`, `calls`, `cost_per_call`, `sales`, `performance`.

`ad_emails` is `dict[str, set[str]]` mapping ad id to the set of lead emails Hyros attributed to it.

`performance` is one of `"Winner"`, `"Stand Out"`, `""`, or `"Not enough data"`.

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_paid_mql.py`:

```python
from dashboard.data.paid_mql import creative_tracker


def _ads(rows):
    return pd.DataFrame(rows, columns=["ad_id", "ad_name", "campaign_name",
                                       "spend", "video_plays"])


def _ents(rows):
    return pd.DataFrame(rows, columns=["ad_id", "created_time",
                                       "effective_status", "story_id"])


def _tracker(ads, ad_emails, mql_emails, **kw):
    defaults = dict(segment_rollup=ROLLUP, spend_floor=500.0,
                    winner_pct=0.25, standout_pct=0.10, min_mql=3)
    defaults.update(kw)
    return creative_tracker(
        ads,
        _ents([(r[0], "2026-08-01T00:00:00-0500", "ACTIVE", "1_2")
               for r in ads.itertuples(index=False)]),
        ad_emails=ad_emails, mql_emails=mql_emails,
        call_emails=set(), sale_emails=set(), **defaults)


def test_ad_below_spend_floor_is_excluded():
    out = _tracker(_ads([("1", "Cheap ad", CHIRO, 100.0, 0.0)]), {}, set())
    assert out.empty


def test_ad_without_enough_mqls_is_not_labeled():
    """One MQL on $600 of spend must not read as a Winner. That is noise,
    and a creative tracker that promotes noise is worse than none."""
    out = _tracker(
        _ads([("1", "Thin ad", CHIRO, 600.0, 0.0)]),
        {"1": {"a@x.com"}}, {"a@x.com"})
    assert out.iloc[0]["performance"] == "Not enough data"


def test_winner_and_standout_thresholds():
    """Segment average cost per callable MQL is $100 here. An ad at $70 is
    30% below (Winner); $85 is 15% below (Stand Out); $95 is 5% below
    (neither)."""
    ads = _ads([
        ("w", "Winner ad", CHIRO, 700.0, 0.0),
        ("s", "Standout ad", CHIRO, 850.0, 0.0),
        ("n", "Normal ad", CHIRO, 950.0, 0.0),
        ("x", "Expensive ad", CHIRO, 1500.0, 0.0),
    ])
    ad_emails = {
        "w": {f"w{i}@x.com" for i in range(10)},
        "s": {f"s{i}@x.com" for i in range(10)},
        "n": {f"n{i}@x.com" for i in range(10)},
        "x": {f"x{i}@x.com" for i in range(10)},
    }
    mql = set().union(*ad_emails.values())
    out = _tracker(ads, ad_emails, mql).set_index("ad_id")
    assert out.loc["w", "performance"] == "Winner"
    assert out.loc["s", "performance"] == "Stand Out"
    assert out.loc["n", "performance"] == ""
    assert out.loc["x", "performance"] == ""


def test_scored_against_own_segment_not_account_average():
    """A cheap segment must not swallow every Winner label. Each segment
    produces its own winner."""
    ads = _ads([
        ("c1", "Chiro cheap", CHIRO, 500.0, 0.0),
        ("c2", "Chiro dear", CHIRO, 1500.0, 0.0),
        ("n1", "NLAP cheap", NLAP, 5000.0, 0.0),
        ("n2", "NLAP dear", NLAP, 15000.0, 0.0),
    ])
    ad_emails = {k: {f"{k}{i}@x.com" for i in range(10)}
                 for k in ("c1", "c2", "n1", "n2")}
    mql = set().union(*ad_emails.values())
    out = _tracker(ads, ad_emails, mql).set_index("ad_id")
    assert out.loc["c1", "performance"] == "Winner"
    assert out.loc["n1", "performance"] == "Winner"


def test_format_from_video_plays():
    ads = _ads([("v", "Video ad", CHIRO, 600.0, 42.0),
                ("s", "Static ad", CHIRO, 600.0, 0.0)])
    out = _tracker(ads, {}, set()).set_index("ad_id")
    assert out.loc["v", "format"] == "Video"
    assert out.loc["s", "format"] == "Static"


def test_ad_with_no_hyros_attribution_reports_zero_not_a_label():
    """An ad Hyros never attributed must not be scored as an infinitely
    expensive loser. It has no data, which is a different fact."""
    out = _tracker(_ads([("1", "Untracked", CHIRO, 900.0, 0.0)]), {}, set())
    row = out.iloc[0]
    assert row["callable_mql"] == 0
    assert row["cost_cmql"] is None
    assert row["performance"] == "Not enough data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: FAIL with `ImportError: cannot import name 'creative_tracker'`

- [ ] **Step 3: Write the implementation**

Append to `dashboard/data/paid_mql.py`:

```python
CREATIVE_COLUMNS = ["ad_id", "ad_name", "segment", "format", "launched",
                    "status", "story_id", "spend", "callable_mql",
                    "cost_cmql", "calls", "cost_per_call", "sales",
                    "performance"]

NOT_ENOUGH_DATA = "Not enough data"


def creative_tracker(ad_insights: pd.DataFrame,
                     ad_entities: pd.DataFrame,
                     ad_emails: dict[str, set[str]],
                     mql_emails: set[str],
                     call_emails: set[str],
                     sale_emails: set[str],
                     *,
                     segment_rollup: dict[str, str],
                     spend_floor: float,
                     winner_pct: float,
                     standout_pct: float,
                     min_mql: int,
                     ) -> pd.DataFrame:
    """One row per ad above the spend floor, scored within its own segment.

    Performance compares each ad's cost per callable MQL against the average
    for its own segment, so a Chiro ad is judged against Chiro rather than
    against NLAP. An ad must clear the spend floor AND have at least min_mql
    callable MQLs to earn any label; below that it reads "Not enough data"
    rather than being silently ranked on noise.
    """
    ads = ad_insights.copy() if ad_insights is not None else pd.DataFrame()
    if ads.empty:
        return pd.DataFrame(columns=CREATIVE_COLUMNS)

    ads = ads[ads["spend"].astype(float) >= float(spend_floor)]
    if ads.empty:
        return pd.DataFrame(columns=CREATIVE_COLUMNS)

    ents = (ad_entities.set_index("ad_id").to_dict("index")
            if ad_entities is not None and not ad_entities.empty else {})

    rows = []
    for r in ads.itertuples(index=False):
        aid = str(r.ad_id)
        emails = ad_emails.get(aid, set())
        n_mql = len(emails & mql_emails)
        spend = float(r.spend)
        ent = ents.get(aid, {})
        rows.append({
            "ad_id": aid,
            "ad_name": r.ad_name,
            "segment": resolve_segment(r.campaign_name,
                                       segment_rollup=segment_rollup),
            # The creative object reports object_type SHARE and a null
            # video_id on every ad in this account, so video plays are the
            # only reliable format signal.
            "format": "Video" if float(getattr(r, "video_plays", 0) or 0) > 0
                      else "Static",
            "launched": str(ent.get("created_time") or "")[:10] or None,
            "status": ent.get("effective_status"),
            "story_id": ent.get("story_id"),
            "spend": spend,
            "callable_mql": n_mql,
            "cost_cmql": _safe_div(spend, n_mql),
            "calls": len(emails & call_emails),
            "cost_per_call": _safe_div(spend, len(emails & call_emails)),
            "sales": len(emails & sale_emails),
            "performance": "",
        })

    # Segment averages use only ads that cleared the volume guard, so a
    # single thin ad cannot drag its segment's benchmark around.
    per_segment: dict[str, list[float]] = {}
    for row in rows:
        if row["callable_mql"] >= min_mql and row["cost_cmql"] is not None:
            per_segment.setdefault(row["segment"], []).append(row["cost_cmql"])
    seg_avg = {s: sum(v) / len(v) for s, v in per_segment.items() if v}

    for row in rows:
        if row["callable_mql"] < min_mql or row["cost_cmql"] is None:
            row["performance"] = NOT_ENOUGH_DATA
            continue
        avg = seg_avg.get(row["segment"])
        if not avg:
            row["performance"] = NOT_ENOUGH_DATA
            continue
        delta = (avg - row["cost_cmql"]) / avg  # positive means cheaper
        if delta >= winner_pct:
            row["performance"] = "Winner"
        elif delta >= standout_pct:
            row["performance"] = "Stand Out"
        else:
            row["performance"] = ""

    out = pd.DataFrame(rows, columns=CREATIVE_COLUMNS)
    return out.sort_values("launched", ascending=False, na_position="last")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_paid_mql.py -q`
Expected: PASS, 25 tests.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: 180 passed.

- [ ] **Step 6: Commit**

```bash
git add dashboard/data/paid_mql.py dashboard/tests/test_paid_mql.py
git commit -m "feat(paid-media): creative tracker with per-segment scoring"
```

---

### Task 9: Creative Tracker rendering

**Files:**
- Modify: `dashboard/sections/paid_media.py`

**Interfaces:**
- Consumes: `creative_tracker` from Task 8; `load_fb_ad_insights`, `load_fb_ad_entities` from Task 6; `load_hyros_leads_with_ads` from Task 7.

- [ ] **Step 1: Add the imports**

At the top of `dashboard/sections/paid_media.py`, extend the existing import lines:

```python
from dashboard.data.fb_loader import (
    load_fb_ad_entities, load_fb_ad_insights, load_fb_insights,
)
from dashboard.data.hyros_loader import load_hyros_leads_with_ads
from dashboard.data.paid_mql import (
    creative_tracker, daily_mql_summary, resolve_segment, segment_results,
)
```

- [ ] **Step 2: Append the third table to render_paid_media**

Add at the end of `render_paid_media`:

```python
    # --- Table 3 ---
    st.subheader("Creative Tracker")
    floor = st.number_input(
        "Minimum spend to appear", min_value=0.0, step=100.0,
        value=float(cfg.CREATIVE_SPEND_FLOOR), key="paid_media_floor")
    st.caption(
        "One row per ad above the spend floor, newest first. Performance "
        "compares each ad's cost per callable MQL against the average for "
        "its OWN segment, so a Chiro ad is judged against Chiro. An ad needs "
        f"at least {cfg.CREATIVE_MIN_MQL} callable MQLs to earn a label. "
        "Revenue and ROAS are omitted for the same reason as the segment "
        "table."
    )

    ad_ins = load_fb_ad_insights(start_date, end_date)
    kept = ad_ins[ad_ins["spend"] >= floor]
    ad_ents = load_fb_ad_entities(tuple(kept["ad_id"]))
    hyros = load_hyros_leads_with_ads(start_date, end_date)

    ad_emails: dict[str, set[str]] = {}
    for r in hyros.itertuples(index=False):
        if r.ad_id:
            ad_emails.setdefault(str(r.ad_id), set()).add(r.email)

    tracker = creative_tracker(
        kept, ad_ents, ad_emails,
        mql_emails=set(mql_frame["email"]),
        call_emails=call_emails,
        sale_emails=sale_emails,
        segment_rollup=cfg.SEGMENT_ROLLUP,
        spend_floor=floor,
        winner_pct=cfg.CREATIVE_WINNER_PCT,
        standout_pct=cfg.CREATIVE_STANDOUT_PCT,
        min_mql=cfg.CREATIVE_MIN_MQL,
    )

    if tracker.empty:
        st.info(f"No ads spent {_dash(floor)} or more in this window.")
    else:
        st.dataframe(pd.DataFrame({
            "Ad Name": tracker["ad_name"],
            "Ad Link": tracker["story_id"].map(
                lambda s: f"https://www.facebook.com/{str(s).replace('_', '/posts/')}"
                if s else ""),
            "Funnel": tracker["segment"],
            "Format": tracker["format"],
            "Launched": tracker["launched"],
            "Status": tracker["status"],
            "Performance": tracker["performance"],
            "Spend": tracker["spend"].map(_dash),
            "Callable MQL": tracker["callable_mql"].map(
                lambda v: _dash(v, "int")),
            "Cost per CMQL": tracker["cost_cmql"].map(_dash),
            "Calls": tracker["calls"].map(lambda v: _dash(v, "int")),
            "Cost per Call": tracker["cost_per_call"].map(_dash),
            "Units Sold": tracker["sales"].map(lambda v: _dash(v, "int")),
        }), use_container_width=True, hide_index=True,
            column_config={"Ad Link": st.column_config.LinkColumn(
                "Ad Link", display_text="open")})

        untracked = int((hyros["ad_id"].isna()).sum())
        st.caption(
            "Ad-level lead counts come from Hyros ad attribution, while the "
            "segment table's counts come from HubSpot typeform submissions. "
            "These are different keys reading different systems, so the two "
            "tables will NOT sum identically. Hyros only sees leads it "
            f"tracked. In this window {untracked} Hyros lead records carry no "
            "ad id and are therefore absent from every ad row above."
        )
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: 180 passed.

- [ ] **Step 4: Smoke-test the render path**

Extend the scratchpad `probe_render_paid_media.py` from Task 5 with a `creative_tracker` call using the same loaders, and run it from repo root. Expected: a table of roughly 37 rows for a 90-day window at the $500 floor, with at least one Winner and at least one "Not enough data". If every row reads "Not enough data", Hyros ad attribution is not joining and Task 7's probe output should be re-checked before shipping.

- [ ] **Step 5: Commit and push**

```bash
git add dashboard/sections/paid_media.py
git commit -m "feat(paid-media): Creative Tracker table with variance disclosure"
git push origin feature/cmo-dashboard
```

- [ ] **Step 6: Verify the deploy**

Confirm all three tables render on the deployed app. Check specifically that the Ad Link column opens a real Facebook post; if the permalink 404s, the `story_id` to URL transform needs the page id handled differently and should be reported rather than silently left broken.

---

## Verification Checklist

Run after Task 9.

- [ ] `python -m pytest dashboard/tests -q` reports 180 passed.
- [ ] The PAID MEDIA tab renders all three tables without exception on the deployed app.
- [ ] The segment table lists Event, Chiro, NLAP, TheraRay and MAP, with MAP showing non-zero spend.
- [ ] No `(unmatched)` row appears. If one does, a campaign launched after 2026-08-28 needs a `CAMPAIGN_GROUPS` pattern and an `ASSET_TO_GROUP` label.
- [ ] The daily table's Total leads count is in the same range as the METRICS tab daily summary for the same window.
- [ ] Zero denominators render as `-`, never `$0.00`.
- [ ] Every table carries its dating caption, and the Creative Tracker carries the Hyros variance caption.
- [ ] No em dashes anywhere in new code, comments or UI copy: `grep -rn "—" dashboard/` returns nothing new.

## Known Limitations To Carry Forward

These are accepted, documented in the spec, and must not be "fixed" without a decision:

- **No revenue, profit or ROAS.** All 80 closed-won deals YTD carry an identical $40,000 placeholder `amount`. These columns would present the Sales count as revenue analytics.
- **Segment CAC excludes payroll**, mirroring `blended_cac`. `SDR_PAYROLL_MONTHLY` and `SME_PAYROLL_MONTHLY` are unset, and allocating a monthly payroll figure across segments needs an allocation rule that does not exist yet.
- **Re-engaged old leads have unreliable MQL stamps.** Stamp rate is 98% for contacts created in-window but 77% for contacts created in 2021. Cohort dating on lead arrival means the segment table never counts those.
- **Tables 2 and 3 lead counts will not match**, by design. Different attribution keys against different systems.
- **The tier-derived money engine stays deleted.** It was built and reverted in June as over-engineering.
