# COMMISSIONS Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a COMMISSIONS tab with a month picker showing per-SDR/BDS/SME/Gerri monthly commissions per the locked matrix, with 90-day→Primary-1 conversion bonuses.

**Architecture:** New `COMMISSION_RATES` config; a loader change surfacing the Primary-1 + 90-Day stage-entry dates so conversions are detectable; `build_closed_deals_table` gains `dealstage` + those entry dates; a pure `sdr_completions_by_owner` (held 15-min/strategy by the lead's SDR, warm/cold) and a pure `compute_monthly_commissions` (the whole matrix, no double-pay on conversions); a `render_commissions` tab.

**Tech Stack:** Python, pandas, Streamlit. Tests: `python -m pytest dashboard/tests -q` via the Bash tool (context-mode python is a stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-07-10-commissions-tab-design.md`.

**Conventions:** PURE reconcile functions (config injected, never imported). No em dashes in user-facing copy. Stage ONLY the files each task names (repo has unrelated pre-existing modified/untracked files; leave them). End every commit with:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Tier stage ids: full/Primary-1 = `24094605` or `closedwon`; 90-Day = `1123458844`; DIY = `1163151789`. Held = `outcome.upper().startswith("COMPLETE")`. Warm = contact typeform non-empty (SDR only). `_safe_div`, `discovery_mask` already exist.

---

## Task 1: `COMMISSION_RATES` config

**Files:** Modify `dashboard/config.py` (after `FLAT_CLOSE_COMMISSION`, ~line 279); Test `dashboard/tests/test_commissions.py` (extend).

- [ ] **Step 1: Write the failing test** — append to `dashboard/tests/test_commissions.py`:

```python
from dashboard.config import COMMISSION_RATES as CR


def test_commission_rates_shape():
    assert CR["sdr"]["disco_complete"] == {"warm": 20.0, "cold": 100.0}
    assert CR["sdr"]["strategy_complete"] == {"warm": 100.0, "cold": 100.0}
    assert CR["sdr"]["full_close"] == {"warm": 200.0, "cold": 400.0}
    assert CR["sdr"]["ninety_day"] == {"warm": 50.0, "cold": 100.0}
    assert CR["sdr"]["conversion_bonus"] == {"warm": 150.0, "cold": 300.0}
    assert CR["bds"] == {"full_close": 300.0, "ninety_day": 50.0, "conversion_bonus": 250.0}
    assert CR["sme"] == {"full_close": 2000.0, "ninety_day": 500.0, "conversion_bonus": 1500.0}
    assert CR["gerri_per_close"] == 25.0
    assert CR["stages"]["full"] == ("24094605", "closedwon")
    assert CR["stages"]["ninety_day"] == "1123458844"
    assert CR["stages"]["diy"] == "1163151789"
```

- [ ] **Step 2: Run — expect FAIL** (`COMMISSION_RATES` undefined):
`cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_commissions.py::test_commission_rates_shape -q`

- [ ] **Step 3: Add the config** (config.py, after line 279):

```python
# --- COMMISSIONS tab payout matrix (Garrett/Callum review; 2026-07-10) ---
# Separate from the CAC constants above so the executive CAC number is
# undisturbed. SDR is warm/cold; BDS/SME/Gerri are flat. Full close = Primary-1;
# a 90-day pays a base, and converting to Primary-1 pays the bonus (base+bonus =
# full). DIY closes pay nothing to SDR/BDS/SME (Gerri still counts them).
COMMISSION_RATES: dict = {
    "sdr": {
        "disco_complete":   {"warm": 20.0,  "cold": 100.0},
        "strategy_complete": {"warm": 100.0, "cold": 100.0},
        "full_close":       {"warm": 200.0, "cold": 400.0},
        "ninety_day":       {"warm": 50.0,  "cold": 100.0},
        "conversion_bonus": {"warm": 150.0, "cold": 300.0},
    },
    "bds": {"full_close": 300.0, "ninety_day": 50.0, "conversion_bonus": 250.0},
    "sme": {"full_close": 2000.0, "ninety_day": 500.0, "conversion_bonus": 1500.0},
    "gerri_per_close": 25.0,
    "stages": {
        "full": ("24094605", "closedwon"),
        "ninety_day": "1123458844",
        "diy": "1163151789",
    },
}
```

- [ ] **Step 4: Run — expect PASS.** - [ ] **Step 5: Commit** `git add dashboard/config.py dashboard/tests/test_commissions.py && git commit -m "feat(commissions): COMMISSION_RATES payout matrix config" ...`

---

## Task 2: Loader — surface Primary-1 + 90-Day stage-entry dates

**Files:** Modify `dashboard/data/hubspot_loader.py` (`load_closed_deals_in_window`, ~915-1014).

Additive: keep `stage_entry_date` (used by METRICS) as-is; add two explicit columns.

- [ ] **Step 1: Add the two columns to `deal_cols`** (~line 932):

```python
    deal_cols = ["deal_id", "dealname", "amount", "dealstage", "pipeline",
                 "createdate", "closedate", "stage_entry_date",
                 "entered_primary1", "entered_90day"]
```

- [ ] **Step 2: Fetch both entry-date properties** — change the `properties` list (~977-979) to always request them:

```python
        "properties": ["dealname", "amount", "dealstage", "pipeline",
                       "createdate", "closedate",
                       "hs_v2_date_entered_24094605",   # Primary-1
                       "hs_v2_date_entered_1123458844", # 90-Day
                       *stage_entry_props.values()],
```

- [ ] **Step 3: Populate the columns in the row dict** (~1002-1011) — add two keys:

```python
            deal_rows.append({
                "deal_id": str(did) if did is not None else None,
                "dealname": p.get("dealname"),
                "amount": float(p.get("amount") or 0),
                "dealstage": stage_id,
                "pipeline": p.get("pipeline"),
                "createdate": p.get("createdate"),
                "closedate": p.get("closedate"),
                "stage_entry_date": stage_entry,
                "entered_primary1": p.get("hs_v2_date_entered_24094605"),
                "entered_90day": p.get("hs_v2_date_entered_1123458844"),
            })
```

- [ ] **Step 4: Ensure the empty-return keeps the columns** — the `return pd.DataFrame(columns=deal_cols)` at ~973 now includes them automatically (deal_cols updated). Verify the final `return pd.DataFrame(deal_rows, columns=deal_cols)` uses `deal_cols`.

- [ ] **Step 5: Verify parse + smoke + suite:**
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/data/hubspot_loader.py', encoding='utf-8').read()); print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "
from datetime import date
import dashboard.config as cfg
from dashboard.data.hubspot_loader import load_closed_deals_in_window
d = load_closed_deals_in_window.__wrapped__(date(2026,1,1), date.today(), tuple(cfg.STAGES_CLOSED_WON), tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE))
print('cols:', [c for c in ['entered_primary1','entered_90day'] if c in d.columns])
print('primary1 non-null:', int(d['entered_primary1'].notna().sum()), ' 90day non-null:', int(d['entered_90day'].notna().sum()))
" 2>&1 | grep -v "No runtime found"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q
```
Expected: `ast OK`; both columns present with some non-null; suite green.

- [ ] **Step 6: Commit** `git add dashboard/data/hubspot_loader.py && git commit -m "feat(loader): closed deals carry entered_primary1 + entered_90day stage dates" ...`

---

## Task 3: `build_closed_deals_table` — expose stage + entry dates

**Files:** Modify `dashboard/data/reconcile.py` (`build_closed_deals_table`, cols ~2656-2658 + row ~2782-2801); Test `dashboard/tests/test_commissions.py`.

- [ ] **Step 1: Write the failing test** — append:

```python
import pandas as pd
from dashboard.data.reconcile import build_closed_deals_table


def test_closed_deals_table_exposes_stage_and_entry_dates():
    deals = pd.DataFrame([{
        "deal_id": "d1", "dealstage": "24094605", "amount": 5000.0,
        "closedate": "2026-06-15T00:00:00Z", "stage_entry_date": None,
        "createdate": "2026-01-01T00:00:00Z",
        "entered_primary1": "2026-06-15T00:00:00Z", "entered_90day": "2026-05-01T00:00:00Z",
    }])
    contacts = pd.DataFrame([{
        "hs_id": "c1", "name": "X", "email": "x@x.com",
        "typeform_asset_download": "Top 10 typeform", "sdr_owner": "S", "bds": "B", "sme": "M",
        "send_contract_options": "", "created": "2026-01-01T00:00:00Z",
    }])
    cd = pd.DataFrame([{"contact_id": "c1", "deal_id": "d1"}])
    t = build_closed_deals_table(
        deals, cd, contacts, asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={}, source_overrides=None, stage_source_fallback=None,
    )
    row = t.iloc[0]
    assert row["dealstage"] == "24094605"
    assert row["entered_primary1"] == "2026-06-15T00:00:00Z"
    assert row["entered_90day"] == "2026-05-01T00:00:00Z"
```

- [ ] **Step 2: Run — expect FAIL** (KeyError: those columns not in output).

- [ ] **Step 3: Add the columns.** In `cols` (reconcile.py ~2656-2658) append `"dealstage", "entered_primary1", "entered_90day"`:

```python
    cols = ["hs_id", "contact_name", "email", "typeform", "group", "asset", "source",
            "tier", "send_contract", "is_marketing", "closedate", "deal_amount",
            "sales_cycle_days", "sdr_owner", "bds", "sme",
            "dealstage", "entered_primary1", "entered_90day"]
```
In the `rows.append({...})` (reconcile.py ~2782-2801) add three keys, reading from the loop's `deal` row (the deal dict already in scope where `deal.get("dealstage")` is read):

```python
            "dealstage": deal.get("dealstage") or "",
            "entered_primary1": deal.get("entered_primary1"),
            "entered_90day": deal.get("entered_90day"),
```

(If the loop variable is named differently than `deal`, match the existing `deal.get("dealstage")` usage in the function — same variable.)

- [ ] **Step 4: Run — expect PASS** (+ full suite green). - [ ] **Step 5: Commit** `git add dashboard/data/reconcile.py dashboard/tests/test_commissions.py && git commit -m "feat(commissions): closed-deals table exposes dealstage + stage-entry dates" ...`

---

## Task 4: `sdr_completions_by_owner` — held 15-min/strategy by SDR, warm/cold

**Files:** Modify `dashboard/data/reconcile.py` (new function near the other rollups); Test `dashboard/tests/test_commissions.py`.

- [ ] **Step 1: Write the failing test** — append:

```python
from datetime import date
from dashboard.data.reconcile import sdr_completions_by_owner


def test_sdr_completions_by_owner_warm_cold_and_type():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "S1", "typeform_asset_download": "Top 10 typeform"},  # warm
        {"hs_id": "2", "sdr_owner": "S1", "typeform_asset_download": ""},                  # cold
    ])
    meetings = pd.DataFrame([
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "COMPLETED",
         "start_time": "2026-06-03T15:00:00Z"},                          # warm disco held
        {"contact_id": "2", "activity_type": "Strategy Call", "outcome": "COMPLETE - QUALIFIED",
         "start_time": "2026-06-04T15:00:00Z"},                          # cold strat held
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-06-05T15:00:00Z"},                          # not held -> ignored
    ])
    out = sdr_completions_by_owner(meetings, contacts, date(2026, 6, 1), date(2026, 6, 30))
    assert out["S1"] == {"disco_warm": 1, "disco_cold": 0, "strat_warm": 0, "strat_cold": 1}
```

- [ ] **Step 2: Run — expect FAIL** (function undefined).

- [ ] **Step 3: Implement** (reconcile.py):

```python
def sdr_completions_by_owner(meetings: pd.DataFrame, contacts: pd.DataFrame,
                             start: date, end: date) -> dict[str, dict[str, int]]:
    """Held 15-min + strategy completions in [start, end], grouped by the lead's
    sdr_owner, split warm (contact has a typeform) vs cold. Held = outcome
    COMPLETE*. Month = meeting start_time. Returns
    {sdr_owner: {disco_warm, disco_cold, strat_warm, strat_cold}}."""
    out: dict[str, dict[str, int]] = {}
    if meetings.empty or contacts.empty:
        return out
    owner_map = dict(zip(contacts["hs_id"].astype(str),
                         contacts["sdr_owner"].fillna("").astype(str)))
    warm_map = dict(zip(
        contacts["hs_id"].astype(str),
        contacts["typeform_asset_download"].fillna("").astype(str).str.strip() != "",
    ))
    types = meetings["activity_type"].fillna("").astype(str).str.lower()
    outc = meetings["outcome"].fillna("").astype(str).str.upper()
    mstart = pd.to_datetime(meetings["start_time"], utc=True, errors="coerce").dt.date
    cid = meetings["contact_id"].astype(str)
    held = outc.str.startswith("COMPLETE")
    in_win = mstart.apply(lambda d: bool(pd.notna(d)) and start <= d <= end)
    sdr = cid.map(owner_map).fillna("")
    warm = cid.map(warm_map).fillna(False)
    base = held & in_win & (sdr != "")
    for kind, kmask in (("disco", discovery_mask(types)),
                        ("strat", types.str.contains("strategy", na=False))):
        sub = base & kmask
        for owner, w in zip(sdr[sub], warm[sub]):
            rec = out.setdefault(owner, {"disco_warm": 0, "disco_cold": 0,
                                         "strat_warm": 0, "strat_cold": 0})
            rec[f"{kind}_{'warm' if w else 'cold'}"] += 1
    return out
```

- [ ] **Step 4: Run — expect PASS.** - [ ] **Step 5: Commit** `git add dashboard/data/reconcile.py dashboard/tests/test_commissions.py && git commit -m "feat(commissions): sdr_completions_by_owner (held 15-min/strategy, warm/cold)" ...`

---

## Task 5: `compute_monthly_commissions` — the engine

**Files:** Modify `dashboard/data/reconcile.py` (new function); Test `dashboard/tests/test_commissions.py`.

Semantics (from the spec): each closed deal contributes commission EVENTS whose date falls in the month. Full-close month = `entered_primary1` (else `closedate`); 90-day month = `entered_90day` (else `stage_entry_date`/`closedate`); a deal in a full stage WITH a non-null `entered_90day` is a CONVERSION (bonus only, in its full-close month) — the 90-day base was already counted in its 90-day month. A deal in the 90-day stage counts the 90-day base. DIY pays nothing (SDR/BDS/SME); Gerri = $25 × each deal counted once in its first-closed month.

- [ ] **Step 1: Write the failing test** — append:

```python
from dashboard.data.reconcile import compute_monthly_commissions
from dashboard.config import COMMISSION_RATES as CR

_JUN = (date(2026, 6, 1), date(2026, 6, 30))
_MAY = (date(2026, 5, 1), date(2026, 5, 31))


def _deal(did, stage, *, sdr="S1", bds="B1", sme="M1", warm=True,
          entered_primary1=None, entered_90day=None, closedate=None):
    return {
        "hs_id": did, "sdr_owner": sdr, "bds": bds, "sme": sme,
        "typeform": "Top 10 typeform" if warm else "",
        "dealstage": stage, "entered_primary1": entered_primary1,
        "entered_90day": entered_90day, "closedate": closedate, "deal_amount": 0.0,
    }


def test_commissions_direct_full_close_warm():
    deals = pd.DataFrame([_deal("d1", "24094605", warm=True,
                                entered_primary1="2026-06-10T00:00:00Z")])
    res = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)
    sdr = res["sdr"].set_index("rep_id")
    assert sdr.loc["S1", "full"] == 200.0 and sdr.loc["S1", "ninety"] == 0.0 and sdr.loc["S1", "conversion"] == 0.0
    assert res["bds"].set_index("rep_id").loc["B1", "full"] == 300.0
    assert res["sme"].set_index("rep_id").loc["M1", "full"] == 2000.0
    assert res["gerri"]["count"] == 1 and res["gerri"]["total"] == 25.0


def test_commissions_90day_then_conversion_split_across_months():
    # Entered 90-day in May, converted to Primary-1 in June. Cold lead.
    deal = _deal("d2", "24094605", warm=False,
                 entered_90day="2026-05-20T00:00:00Z",
                 entered_primary1="2026-06-12T00:00:00Z")
    deals = pd.DataFrame([deal])
    may = compute_monthly_commissions(deals, {}, *_MAY, rates=CR)["sdr"].set_index("rep_id")
    jun = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["sdr"].set_index("rep_id")
    assert may.loc["S1", "ninety"] == 100.0 and may.loc["S1", "conversion"] == 0.0 and may.loc["S1", "full"] == 0.0
    assert jun.loc["S1", "conversion"] == 300.0 and jun.loc["S1", "full"] == 0.0 and jun.loc["S1", "ninety"] == 0.0
    # BDS/SME conversion in June
    assert compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["bds"].set_index("rep_id").loc["B1", "conversion"] == 250.0
    assert compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["sme"].set_index("rep_id").loc["M1", "conversion"] == 1500.0


def test_commissions_diy_pays_only_gerri():
    deals = pd.DataFrame([_deal("d3", "1163151789", entered_primary1=None,
                                closedate="2026-06-05T00:00:00Z")])
    res = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)
    assert res["sdr"].empty or "S1" not in res["sdr"].set_index("rep_id").index
    assert res["gerri"]["count"] == 1 and res["gerri"]["total"] == 25.0


def test_commissions_sdr_call_completions():
    comps = {"S1": {"disco_warm": 2, "disco_cold": 1, "strat_warm": 1, "strat_cold": 0}}
    res = compute_monthly_commissions(pd.DataFrame(columns=["hs_id"]), comps, *_JUN, rates=CR)
    sdr = res["sdr"].set_index("rep_id")
    # disco: 2*20 + 1*100 = 140 ; strategy: 1*100 = 100
    assert sdr.loc["S1", "disco"] == 140.0 and sdr.loc["S1", "strategy"] == 100.0
    assert sdr.loc["S1", "total"] == 240.0
```

- [ ] **Step 2: Run — expect FAIL** (function undefined).

- [ ] **Step 3: Implement** (reconcile.py):

```python
def compute_monthly_commissions(closed_deals: pd.DataFrame,
                                sdr_completions: dict, start: date, end: date,
                                *, rates: dict) -> dict:
    """Per-rep commissions for the month [start, end].

    closed_deals: build_closed_deals_table output (needs sdr_owner, bds, sme,
      typeform, dealstage, entered_primary1, entered_90day, closedate).
    sdr_completions: sdr_completions_by_owner(...) output for the SAME month.
    Returns {"sdr": df, "bds": df, "sme": df, "gerri": {count, total}} where each
    df has rep_id + component columns + total. No double-pay: a converted deal's
    90-day base counts in its 90-day month, its bonus in its Primary-1 month.
    """
    full_stages = set(rates["stages"]["full"])
    ninety_stage = rates["stages"]["ninety_day"]
    diy_stage = rates["stages"]["diy"]

    def _d(v):
        ts = pd.to_datetime(v, utc=True, errors="coerce")
        return ts.date() if pd.notna(ts) else None

    def _in(d):
        return d is not None and start <= d <= end

    # accumulators: role -> rep -> {component: amount}
    sdr: dict = {}
    bds: dict = {}
    sme: dict = {}
    gerri_count = 0

    def _add(acc, rep, comp, amt):
        if not rep:
            return
        acc.setdefault(rep, {})
        acc[rep][comp] = acc[rep].get(comp, 0.0) + amt

    for _, r in closed_deals.iterrows():
        stage = str(r.get("dealstage") or "")
        warm = str(r.get("typeform") or "").strip() != ""
        temp = "warm" if warm else "cold"
        sdr_owner = str(r.get("sdr_owner") or "")
        bds_owner = str(r.get("bds") or "")
        sme_owner = str(r.get("sme") or "")
        p1 = _d(r.get("entered_primary1"))
        d90 = _d(r.get("entered_90day"))
        close_d = _d(r.get("closedate"))
        first_closed = d90 or p1 or close_d  # earliest closed-won signal for Gerri
        if _in(first_closed):
            gerri_count += 1
        if stage == diy_stage:
            continue  # Gerri only
        # 90-day base counts in the 90-day month (whether or not it later converts)
        if d90 is not None and _in(d90):
            _add(sdr, sdr_owner, "ninety", rates["sdr"]["ninety_day"][temp])
            _add(bds, bds_owner, "ninety", rates["bds"]["ninety_day"])
            _add(sme, sme_owner, "ninety", rates["sme"]["ninety_day"])
        if stage in full_stages:
            full_month = p1 if p1 is not None else close_d
            if _in(full_month):
                if d90 is not None:  # converted -> bonus only
                    _add(sdr, sdr_owner, "conversion", rates["sdr"]["conversion_bonus"][temp])
                    _add(bds, bds_owner, "conversion", rates["bds"]["conversion_bonus"])
                    _add(sme, sme_owner, "conversion", rates["sme"]["conversion_bonus"])
                else:                # direct full close
                    _add(sdr, sdr_owner, "full", rates["sdr"]["full_close"][temp])
                    _add(bds, bds_owner, "full", rates["bds"]["full_close"])
                    _add(sme, sme_owner, "full", rates["sme"]["full_close"])

    # SDR call completions (this month) — from sdr_completions
    for owner, c in (sdr_completions or {}).items():
        disco = c.get("disco_warm", 0) * rates["sdr"]["disco_complete"]["warm"] \
            + c.get("disco_cold", 0) * rates["sdr"]["disco_complete"]["cold"]
        strat = c.get("strat_warm", 0) * rates["sdr"]["strategy_complete"]["warm"] \
            + c.get("strat_cold", 0) * rates["sdr"]["strategy_complete"]["cold"]
        _add(sdr, owner, "disco", disco)
        _add(sdr, owner, "strategy", strat)

    def _frame(acc, comps):
        rows = []
        for rep, d in acc.items():
            row = {"rep_id": rep}
            for comp in comps:
                row[comp] = float(d.get(comp, 0.0))
            row["total"] = float(sum(d.values()))
            rows.append(row)
        return pd.DataFrame(rows, columns=["rep_id"] + comps + ["total"])

    return {
        "sdr": _frame(sdr, ["disco", "strategy", "full", "ninety", "conversion"]),
        "bds": _frame(bds, ["full", "ninety", "conversion"]),
        "sme": _frame(sme, ["full", "ninety", "conversion"]),
        "gerri": {"count": gerri_count, "total": gerri_count * rates["gerri_per_close"]},
    }
```

- [ ] **Step 4: Run — expect PASS** (all 4 tests + full suite). - [ ] **Step 5: Commit** `git add dashboard/data/reconcile.py dashboard/tests/test_commissions.py && git commit -m "feat(commissions): compute_monthly_commissions engine (matrix + conversions)" ...`

---

## Task 6: Render the COMMISSIONS tab

**Files:** Create `dashboard/sections/commissions.py`; Modify `dashboard/app.py` (import + `st.tabs`).

No unit test (Streamlit render); verified by ast + full suite + Task 7 live probe.

- [ ] **Step 1: Create `dashboard/sections/commissions.py`:**

```python
"""COMMISSIONS tab — per-rep monthly commissions for Garrett/Callum."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import dashboard.config as cfg
from dashboard.data.hubspot_loader import (
    load_marketing_contacts, load_contact_deals, load_closed_deals_in_window,
    load_meetings_in_window, load_contacts_by_ids, load_deal_contacts,
)
from dashboard.data.reconcile import (
    build_closed_deals_table, sdr_completions_by_owner, compute_monthly_commissions,
)

_MONEY = lambda v: f"${v:,.0f}"


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start.replace(year=start.year + 1, month=1, day=1)
           if start.month == 12 else start.replace(month=start.month + 1, day=1))
    return start, nxt - timedelta(days=1)


def render_commissions(start: date, end: date) -> None:
    st.subheader("Commissions")
    st.caption("Monthly commission payouts by rep. SDR is warm/cold; BDS/SME/Gerri "
               "are flat. A 90-day pays a base; converting to a full (Primary-1) "
               "pays the bonus in the conversion month. DIY closes pay Gerri only.")
    today = date.today()
    msel = st.date_input("Commission month (pick any day in it)", value=today.replace(day=1),
                         key="commissions_month")
    if isinstance(msel, (tuple, list)):
        msel = msel[0] if msel else today
    m_start, m_end = _month_bounds(msel)
    st.caption(f"**Showing:** {m_start.strftime('%B %Y')}")

    # Closed deals over a broad window (Jan 1 of the month's year -> its end) so
    # conversions of deals that entered 90-day earlier are visible.
    broad_start = date(m_start.year, 1, 1)
    try:
        deals = load_closed_deals_in_window(
            broad_start, m_end, tuple(cfg.STAGES_CLOSED_WON),
            tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE))
    except Exception as e:
        st.warning(f"Deals unavailable: {e}")
        deals = pd.DataFrame()
    # Contacts for those deals (for sdr_owner/bds/sme + warm/cold).
    contacts = pd.DataFrame()
    try:
        if not deals.empty:
            dc = load_deal_contacts(deals["deal_id"].astype(str).tolist())
            cids = list({str(x) for x in dc["contact_id"]}) if not dc.empty else []
            if cids:
                contacts = load_contacts_by_ids(cids)
    except Exception as e:
        st.warning(f"Deal contacts unavailable: {e}")
    try:
        cd = load_contact_deals(contacts["hs_id"].tolist()) if not contacts.empty \
            else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception:
        cd = pd.DataFrame(columns=["contact_id", "deal_id"])

    ct = build_closed_deals_table(
        deals, cd, contacts, asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
    ) if not deals.empty else pd.DataFrame(
        columns=["sdr_owner", "bds", "sme", "typeform", "dealstage",
                 "entered_primary1", "entered_90day", "closedate", "deal_amount"])

    # Held 15-min/strategy in the month, by SDR (needs meetings + their contacts).
    try:
        meetings = load_meetings_in_window(m_start, m_end)
    except Exception:
        meetings = pd.DataFrame(columns=["contact_id", "activity_type", "outcome", "start_time"])
    mc = pd.DataFrame()
    try:
        if not meetings.empty:
            mcids = list({str(x) for x in meetings["contact_id"].dropna()})
            if mcids:
                mc = load_contacts_by_ids(mcids)
    except Exception:
        pass
    comps = sdr_completions_by_owner(meetings, mc, m_start, m_end) if not mc.empty else {}

    res = compute_monthly_commissions(ct, comps, m_start, m_end, rates=cfg.COMMISSION_RATES)

    def _show(title, df, label_cols):
        st.markdown(f"**{title}**")
        if df.empty:
            st.info(f"No {title} commissions in {m_start.strftime('%B %Y')}.")
            return
        d = df.copy()
        d["Rep"] = d["rep_id"].map(cfg.resolve_owner)
        d = d[d["Rep"] != "(unassigned)"]
        for c in [c for c in d.columns if c not in ("rep_id", "Rep")]:
            d[c] = d[c].map(_MONEY)
        d = d[["Rep"] + label_cols]
        st.dataframe(d, use_container_width=True, hide_index=True)

    _show("SDR", res["sdr"].rename(columns={
        "disco": "15-min", "strategy": "Strategy", "full": "Full Close",
        "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["15-min", "Strategy", "Full Close", "90-Day", "Conversion", "Total"])
    _show("BDS", res["bds"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    _show("SME", res["sme"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    g = res["gerri"]
    st.markdown("**Gerri**")
    st.metric("Gerri (flat $25 / close)", _MONEY(g["total"]), delta=f"{g['count']} closes",
              delta_color="off")
```

Note: the `_show` rename maps the compute columns; `label_cols` are the post-rename display names. Confirm every compute column (`disco, strategy, full, ninety, conversion, total`) is mapped.

- [ ] **Step 2: Wire the tab in `app.py`** — add the import (with the other `sections` imports, ~15-17) and the 4th tab:

```python
from dashboard.sections.commissions import render_commissions
```
Change the `st.tabs` unpack (~90):
```python
    tab_executive, tab_sales, tab_metrics, tab_commissions = st.tabs(
        ["EXECUTIVE", "SALES", "METRICS", "COMMISSIONS"])
    with tab_executive:  render_executive(start_date, end_date)
    with tab_sales:      render_sales(start_date, end_date)
    with tab_metrics:    render_metrics()
    with tab_commissions: render_commissions(start_date, end_date)
```

- [ ] **Step 3: Verify:**
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['dashboard/sections/commissions.py','dashboard/app.py']]; print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "from dashboard.sections.commissions import render_commissions; print('import OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q
```
Expected: `ast OK`, `import OK`, suite green.

- [ ] **Step 4: Commit** `git add dashboard/sections/commissions.py dashboard/app.py && git commit -m "feat(commissions): COMMISSIONS tab render + wire into app" ...`

---

## Task 7: Live verify + push

Orchestrator-run (interactive).

- [ ] **Step 1** Write `_probe_commissions_verify.py` mirroring the render's load (broad window closed deals + deal contacts + month meetings + their contacts), call `build_closed_deals_table` + `sdr_completions_by_owner` + `compute_monthly_commissions` for the current month, and print each role's rows + Gerri. Confirm: SDR/BDS/SME rows have sensible per-rep totals; conversions land as `conversion` not double-counted; Gerri count = the month's closed-won deals. Sanity-check one converted deal by hand against HubSpot if any appear.
- [ ] **Step 2** Present the numbers to Kurt (per-rep monthly totals) for a gut-check before pushing.
- [ ] **Step 3** `rm -f _probe_commissions_verify.py && git push origin feature/cmo-dashboard`.
- [ ] **Step 4** After deploy, screenshot the COMMISSIONS tab; confirm the month picker re-computes.

---

## Self-Review

**Spec coverage:** matrix -> Task 1 config + Task 5 engine; conversion no-double-pay -> Task 5 (90-day base in its month, bonus in Primary-1 month, converted deal skips the direct-full branch); loader stage-entry dates -> Task 2; dealstage+entry on the table -> Task 3; SDR held-by-owner warm/cold -> Task 4; DIY = Gerri-only -> Task 5 (`continue` after gerri_count); Gerri = every close once -> Task 5 (`first_closed` month); month picker + per-rep tables -> Task 6; verify -> Task 7. CAC left alone (out of scope). ✓

**Placeholder scan:** every code step is complete; commands have expected output. The one conditional ("if the loop variable is named differently than `deal`") points the implementer at the existing `deal.get("dealstage")` usage — the actual code to add is fully specified.

**Type/name consistency:** `compute_monthly_commissions` returns `{"sdr","bds","sme","gerri"}`; component keys `disco, strategy, full, ninety, conversion, total` are identical across the engine, the tests, and the render's rename maps. `sdr_completions_by_owner` returns `{owner: {disco_warm,disco_cold,strat_warm,strat_cold}}` — consumed by the engine's SDR-call block with those exact keys. `COMMISSION_RATES` keys (`sdr/bds/sme/gerri_per_close/stages`, and `disco_complete/strategy_complete/full_close/ninety_day/conversion_bonus`) match between config, engine, and tests. Loader columns `entered_primary1`/`entered_90day` match across loader, table, and engine. Warm = `typeform` non-empty in the engine; `typeform_asset_download` non-empty in the SDR-completions helper (correct: the closed-deals table calls its column `typeform`, the contacts frame calls it `typeform_asset_download`).
