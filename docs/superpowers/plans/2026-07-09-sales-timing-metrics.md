# Sales Timing Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Speed to Lead (All + Prime business-hours) and Avg Time to Close (All = createdate->close, Prime = first-discovery-booking->close, median) to the SALES tab.

**Architecture:** A pure `business_minutes_between` engine (9-5 Mon-Fri America/Chicago, DST-safe) powers Speed-to-Lead Prime. `compute_speed_to_lead` returns both raw and business-minute elapsed; `sdr_call_activity` surfaces both medians. A new pure `time_to_close` computes median days-to-close under two anchors. The meetings loaders add the meeting `hs_createdate` (booked timestamp) needed for the Prime close anchor. The Sales tab renders both All/Prime medians.

**Tech Stack:** Python (`zoneinfo` stdlib), pandas, Streamlit. Tests: `python -m pytest dashboard/tests -q` via the Bash tool (context-mode python is a stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-07-09-sales-timing-metrics-design.md`.

**Conventions:** PURE functions in reconcile.py (config injected, never imported). No em dashes in user-facing copy. Stage ONLY the files each task names (repo has unrelated pre-existing modified/untracked files; leave them). End every commit with:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Verified facts: `compute_speed_to_lead` (reconcile.py:856) returns `hs_id, speed_to_lead_minutes` where lead-in = typeform_submission (createdate fallback), first-contact = earliest outbound AirCall after lead-in; both anchors are epoch SECONDS internally (`lead_in_ts`, `first_ts`). `sdr_call_activity` (reconcile.py:939) medians `speed_to_lead_minutes` per user (cols at :955). Meetings loaders `load_meetings_for_contacts` (:304) and `load_meetings_in_window` (:398) both return `cols = [meeting_id, contact_id, activity_type, outcome, start_time]` and DON'T fetch the create timestamp yet. HubSpot meetings expose `hs_createdate` 0-7 days before `hs_meeting_start_time` (verified).

---

## Task 1: `business_minutes_between` engine

**Files:**
- Modify: `dashboard/data/reconcile.py` (add near the top-level helpers, after `_safe_div`; add `from zoneinfo import ZoneInfo` to the imports)
- Test: `dashboard/tests/test_timing_metrics.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_timing_metrics.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from dashboard.data.reconcile import business_minutes_between

CT = ZoneInfo("America/Chicago")


def _ep(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=CT).timestamp())


def test_business_minutes_within_one_day():
    assert business_minutes_between(_ep(2026, 6, 1, 10), _ep(2026, 6, 1, 11)) == 60.0  # Mon 10-11


def test_business_minutes_full_workday():
    assert business_minutes_between(_ep(2026, 6, 1, 9), _ep(2026, 6, 1, 17)) == 480.0


def test_business_minutes_clamps_after_hours():
    # Mon 16:00 -> 20:00: only 16-17 counts
    assert business_minutes_between(_ep(2026, 6, 1, 16), _ep(2026, 6, 1, 20)) == 60.0


def test_business_minutes_skips_weekend():
    # Fri 16:00 -> Mon 10:00: Fri 16-17 (60) + Mon 9-10 (60) = 120; Sat/Sun excluded
    assert business_minutes_between(_ep(2026, 6, 5, 16), _ep(2026, 6, 8, 10)) == 120.0


def test_business_minutes_weekend_only_is_zero():
    assert business_minutes_between(_ep(2026, 6, 6, 10), _ep(2026, 6, 7, 12)) == 0.0


def test_business_minutes_end_before_start_is_zero():
    assert business_minutes_between(_ep(2026, 6, 1, 12), _ep(2026, 6, 1, 10)) == 0.0


def test_business_minutes_none_returns_none():
    assert business_minutes_between(None, _ep(2026, 6, 1, 10)) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_timing_metrics.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement the engine**

Add `from zoneinfo import ZoneInfo` near the top imports of `reconcile.py`, then add:

```python
_CT_TZ = ZoneInfo("America/Chicago")


def business_minutes_between(start_epoch, end_epoch, *, work_start_hour: int = 9,
                             work_end_hour: int = 17, tz=_CT_TZ):
    """Minutes between two UTC epoch-second timestamps that fall within
    work_start_hour..work_end_hour local time on Mon-Fri (weekends + after-hours
    excluded; holidays not modeled). Returns None if either input is missing,
    0.0 if end <= start. DST handled via zoneinfo (per-day local windows)."""
    if start_epoch is None or end_epoch is None \
            or pd.isna(start_epoch) or pd.isna(end_epoch):
        return None
    s = datetime.fromtimestamp(int(start_epoch), tz=timezone.utc).astimezone(tz)
    e = datetime.fromtimestamp(int(end_epoch), tz=timezone.utc).astimezone(tz)
    if e <= s:
        return 0.0
    total = 0.0
    day = s.date()
    while day <= e.date():
        if day.weekday() < 5:  # Mon-Fri
            ws = datetime(day.year, day.month, day.day, work_start_hour, tzinfo=tz)
            we = datetime(day.year, day.month, day.day, work_end_hour, tzinfo=tz)
            lo = max(s, ws)
            hi = min(e, we)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60.0
        day = day + timedelta(days=1)
    return total
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_timing_metrics.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_timing_metrics.py
git commit -m "feat(sales): business_minutes_between engine (9-5 Mon-Fri CT)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Speed to Lead — add the Prime (business-minutes) variant

**Files:**
- Modify: `dashboard/data/reconcile.py` (`compute_speed_to_lead` ~856-936; `sdr_call_activity` ~955, ~977, ~1044-1060)
- Test: `dashboard/tests/test_timing_metrics.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_timing_metrics.py`:

```python
import pandas as pd
from dashboard.data.reconcile import compute_speed_to_lead


def test_compute_speed_to_lead_all_and_prime():
    # Lead submits Fri 16:00 CT; first outbound call Mon 10:00 CT.
    # All = raw elapsed (~64.0h = 3840 min); Prime = 120 business minutes.
    lead_ts = _ep(2026, 6, 5, 16)          # Fri 16:00 CT
    call_ts = _ep(2026, 6, 8, 10)          # Mon 10:00 CT
    contacts = pd.DataFrame([{
        "hs_id": "1", "typeform_submission_date":
            datetime.fromtimestamp(lead_ts, tz=CT).astimezone(ZoneInfo("UTC")).isoformat(),
        "created": None, "phone": "+15551234567", "mobilephone": None,
    }])
    calls = pd.DataFrame([{
        "direction": "outbound", "phone_normalized": "+15551234567",
        "started_at_utc": call_ts,
    }])
    df = compute_speed_to_lead(contacts, calls).set_index("hs_id")
    assert abs(df.loc["1", "speed_to_lead_minutes"] - 3840.0) < 1.0
    assert df.loc["1", "speed_to_lead_minutes_prime"] == 120.0
```

(Note: `compute_speed_to_lead` normalizes the contact phone via `normalize_phone`; use a clean E.164 value so it matches `phone_normalized` on the call.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_timing_metrics.py::test_compute_speed_to_lead_all_and_prime -q`
Expected: FAIL (`speed_to_lead_minutes_prime` column missing).

- [ ] **Step 3: Extend `compute_speed_to_lead`**

In `reconcile.py`, update the THREE early empty-returns (currently `pd.DataFrame(columns=["hs_id", "speed_to_lead_minutes"])`) to include the new column:

```python
    return pd.DataFrame(columns=["hs_id", "speed_to_lead_minutes", "speed_to_lead_minutes_prime"])
```

In the NaN append branches (no phone / no match), add the prime key:

```python
            rows.append({"hs_id": contact["hs_id"],
                         "speed_to_lead_minutes": float("nan"),
                         "speed_to_lead_minutes_prime": float("nan")})
```
(there are two such branches — the missing-phone one and the no-match one; update both.)

In the matched branch, compute prime from the same anchors:

```python
        first_ts = matched["started_at_utc"].min()
        minutes = (first_ts - lead_in_ts) / 60.0
        prime = business_minutes_between(lead_in_ts, first_ts)
        rows.append({"hs_id": contact["hs_id"],
                     "speed_to_lead_minutes": float(minutes),
                     "speed_to_lead_minutes_prime": (float(prime) if prime is not None else float("nan"))})
```

- [ ] **Step 4: Add the Prime median to `sdr_call_activity`**

In `sdr_call_activity`: add `"median_speed_to_lead_prime_min"` to `cols` (after `median_speed_to_lead_min`); build a second map + median; add to the row dict and the object-dtype rate-col loop.

```python
    speed_map = dict(zip(speed_df["hs_id"].astype(str),
                         speed_df["speed_to_lead_minutes"]))
    speed_prime_map = dict(zip(speed_df["hs_id"].astype(str),
                               speed_df["speed_to_lead_minutes_prime"]))
```
In the per-user loop, alongside `user_speeds`:
```python
        user_speeds_prime = []
        for phone in grp["phone_normalized"].unique():
            for cid in phone_to_contacts.get(phone, []):
                mp = speed_prime_map.get(cid)
                if mp is not None and not pd.isna(mp):
                    user_speeds_prime.append(mp)
        median_speed_prime = float(pd.Series(user_speeds_prime).median()) if user_speeds_prime else None
```
Add to the row dict: `"median_speed_to_lead_prime_min": median_speed_prime,` and add `"median_speed_to_lead_prime_min"` to the `for rate_col in (...)` object-dtype tuple.

- [ ] **Step 5: Run tests**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (existing + new). If any existing test asserts the exact `sdr_call_activity` column list, update it to include the new column.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_timing_metrics.py
git commit -m "feat(sales): Speed to Lead Prime (business-hours) variant

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Meetings loaders — add the booked timestamp

**Files:**
- Modify: `dashboard/data/hubspot_loader.py` (`load_meetings_for_contacts` ~313/349/361/387; `load_meetings_in_window` ~409/424/440/487)

No unit test (live API loaders); verified by `ast.parse` + the Task 6 probe. Adds a `booked_at` column (ISO string of `hs_createdate`).

- [ ] **Step 1: `load_meetings_for_contacts`**

Add `"booked_at"` to its `cols` list (currently `["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]`). Add `"hs_createdate"` to the batch-read `properties` list. In `meetings_props[mid] = {...}` add `"booked_at": p.get("hs_createdate") or ""`. In the flattened `rows.append({...})` add `"booked_at": m.get("booked_at", "")`.

- [ ] **Step 2: `load_meetings_in_window`**

Add `"booked_at"` to its `cols`. Add `"hs_createdate"` to the search `properties`. In the `meetings.append({...})` add `"booked_at": p.get("hs_createdate")`. In the final `rows.append({...})` add `"booked_at": m.get("booked_at")`.

- [ ] **Step 3: Verify parse + a live smoke**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/data/hubspot_loader.py', encoding='utf-8').read()); print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "
from datetime import date, timedelta
from dashboard.data.hubspot_loader import load_meetings_in_window
m = load_meetings_in_window.__wrapped__(date.today()-timedelta(days=10), date.today())
print('cols:', list(m.columns)); print('booked_at non-null:', m['booked_at'].notna().sum() if 'booked_at' in m else 'MISSING')
" 2>&1 | grep -v "No runtime found"
```
Expected: `ast OK`; cols include `booked_at`; some non-null booked_at values.

- [ ] **Step 4: Full suite (no regressions)**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (loader tests, if any, still green — the added column is additive).

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/hubspot_loader.py
git commit -m "feat(loader): meetings carry booked_at (hs_createdate) for time-to-close

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `time_to_close` — median days under two anchors

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `time_to_close` near the closed-deal helpers)
- Test: `dashboard/tests/test_timing_metrics.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_timing_metrics.py`:

```python
from dashboard.data.reconcile import time_to_close


def test_time_to_close_all_and_prime():
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "won", "closedate": "2026-06-30T00:00:00Z",
         "stage_entry_date": None, "createdate": None},
        {"deal_id": "d2", "dealstage": "won", "closedate": "2026-06-20T00:00:00Z",
         "stage_entry_date": None, "createdate": None},
        {"deal_id": "d3", "dealstage": "open", "closedate": "2026-06-10T00:00:00Z",
         "stage_entry_date": None, "createdate": None},  # not won -> ignored
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "created": "2026-06-01T00:00:00Z"},   # d1: All = 29 days
        {"hs_id": "2", "created": "2026-06-10T00:00:00Z"},   # d2: All = 10 days
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
    ])
    meetings = pd.DataFrame([
        # contact 1 first discovery booked 2026-06-15 -> Prime = 15 days to 06-30
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "COMPLETED",
         "start_time": "2026-06-18T00:00:00Z", "booked_at": "2026-06-15T00:00:00Z"},
        # contact 2 has NO discovery meeting -> excluded from Prime
    ])
    r = time_to_close(deals=deals, contacts=contacts, contact_deals=contact_deals,
                      meetings=meetings, stages_closed_won={"won"})
    assert r["n_all"] == 2
    assert r["median_days_all"] == 19.5      # median(29, 10)
    assert r["n_prime"] == 1
    assert r["median_days_prime"] == 15.0     # only contact 1 has a discovery booking
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_timing_metrics.py::test_time_to_close_all_and_prime -q`
Expected: FAIL (`time_to_close` not defined).

- [ ] **Step 3: Implement `time_to_close`**

```python
def time_to_close(*, deals: pd.DataFrame, contacts: pd.DataFrame,
                  contact_deals: pd.DataFrame, meetings: pd.DataFrame,
                  stages_closed_won) -> dict:
    """Median days-to-close over closed-won deals.

    ALL   = contact createdate -> close date.
    PRIME = first discovery-meeting booked_at (hs_createdate) -> close date.
    Returns {median_days_all, n_all, median_days_prime, n_prime}. Close date =
    closedate -> stage_entry_date -> createdate. Negative deltas excluded.
    """
    out = {"median_days_all": None, "n_all": 0,
           "median_days_prime": None, "n_prime": 0}
    if deals.empty:
        return out
    won = set(stages_closed_won)
    won_deals = deals[deals["dealstage"].isin(won)]
    if won_deals.empty:
        return out

    # contact createdate + first discovery booked_at, keyed by contact id
    created_map: dict[str, "pd.Timestamp"] = {}
    if not contacts.empty:
        cc = pd.to_datetime(contacts.get("created"), utc=True, errors="coerce")
        created_map = dict(zip(contacts["hs_id"].astype(str), cc))

    disco_booked_map: dict[str, "pd.Timestamp"] = {}
    if not meetings.empty and "booked_at" in meetings.columns:
        mt = meetings.copy()
        types = mt["activity_type"].fillna("").astype(str).str.lower()
        mt = mt[discovery_mask(types)]
        if not mt.empty:
            mt["_booked"] = pd.to_datetime(mt["booked_at"], utc=True, errors="coerce")
            for cid, grp in mt.groupby(mt["contact_id"].astype(str)):
                b = grp["_booked"].dropna()
                if not b.empty:
                    disco_booked_map[cid] = b.min()

    # deal_id -> first associated contact id
    deal_to_contact: dict[str, str] = {}
    if not contact_deals.empty:
        for _, r in contact_deals.iterrows():
            did = r["deal_id"]
            if did not in deal_to_contact:
                deal_to_contact[did] = str(r["contact_id"])

    days_all, days_prime = [], []
    for _, d in won_deals.iterrows():
        close = pd.to_datetime(
            d.get("closedate") or d.get("stage_entry_date") or d.get("createdate"),
            utc=True, errors="coerce")
        if pd.isna(close):
            continue
        cid = deal_to_contact.get(d["deal_id"])
        if cid is None:
            continue
        created = created_map.get(cid)
        if created is not None and pd.notna(created):
            delta = (close - created).days
            if delta >= 0:
                days_all.append(delta)
        booked = disco_booked_map.get(cid)
        if booked is not None and pd.notna(booked):
            delta_p = (close - booked).days
            if delta_p >= 0:
                days_prime.append(delta_p)

    if days_all:
        out["median_days_all"] = float(pd.Series(days_all).median())
        out["n_all"] = len(days_all)
    if days_prime:
        out["median_days_prime"] = float(pd.Series(days_prime).median())
        out["n_prime"] = len(days_prime)
    return out
```

- [ ] **Step 4: Run tests**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_timing_metrics.py
git commit -m "feat(sales): time_to_close median (All=createdate, Prime=first discovery)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Render — Speed to Lead All/Prime + Time to Close on the SALES tab

**Files:**
- Modify: `dashboard/sections/sales.py` (Speed to Lead section ~561-597; add Time to Close before the "Closed Deals — Year to Date" subheader ~1381; import `time_to_close`)

No unit test; verified by `ast.parse` + Task 6 probe + a live screenshot.

- [ ] **Step 1: Import `time_to_close`** — add to the existing `from dashboard.data.reconcile import (...)` block (which already imports `compute_speed_to_lead`): add `time_to_close`.

- [ ] **Step 2: Speed to Lead All/Prime** — replace the current compute + metrics block (sales.py ~569-596) with:

```python
    speed_df = compute_speed_to_lead(
        marketing, aircall_calls, lead_window_start=start
    )
    speeds = speed_df["speed_to_lead_minutes"].dropna()
    speeds_prime = speed_df["speed_to_lead_minutes_prime"].dropna()
    median_all = float(speeds.median()) if not speeds.empty else None
    median_prime = float(speeds_prime.median()) if not speeds_prime.empty else None
    pct_under_5 = float((speeds <= 5).mean()) if not speeds.empty else None
    pct_under_60s = float((speeds <= 1).mean()) if not speeds.empty else None

    s1, s2, s3, s4 = st.columns(4)
    s1.metric(
        "Median Speed to Lead (All)",
        f"{median_all:.1f} min" if median_all is not None else "—",
        help="Median minutes from typeform submission to first outbound AirCall, "
             "all hours and weekends included.")
    s2.metric(
        "Median Speed to Lead (Prime)",
        f"{median_prime:.1f} min" if median_prime is not None else "—",
        help="Same, counting only 9-5 Mon-Fri Central business minutes.")
    s3.metric("% Under 5 min", _fmt_pct(pct_under_5),
              help="Share of leads first called within 5 minutes of opt-in (All).")
    s4.metric("% Under 60 sec", _fmt_pct(pct_under_60s),
              help="Share within 60 seconds (All).")
```
Also update the section caption (~564) to note "All (raw clock time) vs Prime (9-5 Mon-Fri Central)".

- [ ] **Step 3: Time to Close** — READ the section around the `st.subheader("Closed Deals — Year to Date")` (~line 1381) to confirm the closed-deal `deals`, `marketing`, `contact_deals`, and `meetings` variables in scope, then insert immediately BEFORE that subheader:

```python
    st.divider()
    st.subheader("Time to Close")
    st.caption("Median days to close for closed-won deals in this window. "
               "All = from the HubSpot contact createdate. Prime = from the first "
               "discovery-call booking. n = deals in each median.")
    ttc = time_to_close(deals=deals, contacts=marketing, contact_deals=contact_deals,
                        meetings=meetings, stages_closed_won=cfg.STAGES_CLOSED_WON)
    ttc1, ttc2 = st.columns(2)
    ttc1.metric(
        "Median Time to Close (All)",
        f"{ttc['median_days_all']:.0f} days" if ttc['median_days_all'] is not None else "—",
        delta=f"n={ttc['n_all']}", delta_color="off",
        help="Contact createdate to close date.")
    ttc2.metric(
        "Median Time to Close (Prime)",
        f"{ttc['median_days_prime']:.0f} days" if ttc['median_days_prime'] is not None else "—",
        delta=f"n={ttc['n_prime']}", delta_color="off",
        help="First discovery-call booking to close date.")
```
(If `deals` / `contact_deals` / `meetings` are named differently in that part of `render_sales`, use the in-scope names — the `deals` loaded at ~125, `marketing` at ~114, `contact_deals` at ~119, `meetings` at ~139 are all in scope for the whole function.)

- [ ] **Step 4: Verify parse + suite**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/sections/sales.py', encoding='utf-8').read()); print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q
```
Expected: `ast OK`, suite green.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/sections/sales.py
git commit -m "feat(sales): render Speed to Lead All/Prime + Time to Close

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Verify on real data, then push

Orchestrator-run (interactive).

- [ ] **Step 1: Probe** — create `_probe_timing_verify.py`:

```python
from datetime import date
import dashboard.config as cfg
from dashboard.data.hubspot_loader import (
    load_marketing_contacts, load_contact_deals, load_deals_in_window,
    load_meetings_for_contacts)
from dashboard.data.aircall_loader import load_aircall_calls
from dashboard.data.reconcile import compute_speed_to_lead, time_to_close

start, end = date(2026, 1, 1), date.today()
contacts = load_marketing_contacts.__wrapped__(start, end)
ids = contacts["hs_id"].tolist()
cd = load_contact_deals.__wrapped__(ids)
deals = load_deals_in_window.__wrapped__(start, end, data_floor_days_back=365)
meetings = load_meetings_for_contacts.__wrapped__(ids, data_floor_days_back=365)
calls = load_aircall_calls.__wrapped__(start, end)

sp = compute_speed_to_lead(contacts, calls, lead_window_start=start)
print("speed cols:", list(sp.columns))
print("median All:", sp["speed_to_lead_minutes"].dropna().median(),
      " median Prime:", sp["speed_to_lead_minutes_prime"].dropna().median())
print("meetings has booked_at:", "booked_at" in meetings.columns,
      " non-null:", meetings["booked_at"].notna().sum() if "booked_at" in meetings else 0)
print("time_to_close:", time_to_close(deals=deals, contacts=contacts, contact_deals=cd,
      meetings=meetings, stages_closed_won=cfg.STAGES_CLOSED_WON))
```

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python _probe_timing_verify.py 2>&1 | grep -v "No runtime found"`
Expected: speed cols include `speed_to_lead_minutes_prime`; Prime median <= All median; meetings carry `booked_at`; `time_to_close` returns sensible medians + n. (Speed medians may be None/empty if AirCall returns no rows in this env — note it, same caveat as the trends charts.)

- [ ] **Step 2: Present to Kurt** the probe output (the four numbers). Then clean up + push:

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
rm -f _probe_timing_verify.py
git push origin feature/cmo-dashboard
```

- [ ] **Step 3: Live confirm** after deploy: SALES tab shows Speed to Lead (All) + (Prime) and a Time to Close (All / Prime) block; screenshot for Kurt.

---

## Self-Review

**Spec coverage:**
- Speed to Lead (All) — unchanged raw elapsed, kept → Task 2/5. ✓
- Speed to Lead (Prime) — business minutes via `business_minutes_between` → Tasks 1, 2, 5. ✓
- Time to Close (All) = createdate->close, median → Task 4, 5. ✓
- Time to Close (Prime) = first discovery booked_at->close, median → Tasks 3 (booked_at), 4, 5. ✓
- Median (not mean); n surfaced → Task 4 returns medians + n; Task 5 shows n. ✓
- 9-5 Mon-Fri America/Chicago, DST-safe, holidays out of scope → Task 1 (zoneinfo, weekday<5). ✓
- Prime close excludes deals with no discovery (counted in All only), surface n → Task 4. ✓

**Placeholder scan:** every code step is complete; commands have expected output. Task 3/5 "read the section / use in-scope names" are guards against drift, with the exact variables named — not placeholders.

**Type/name consistency:** `business_minutes_between(start_epoch, end_epoch, ...)`, `compute_speed_to_lead` new column `speed_to_lead_minutes_prime`, `sdr_call_activity` new column `median_speed_to_lead_prime_min`, `time_to_close(...) -> {median_days_all, n_all, median_days_prime, n_prime}` — identical across functions, tests, and the render. `discovery_mask`, `_safe_div`, `normalize_phone` already exist. Loader `booked_at` column consumed by `time_to_close` and the render's meetings frame.
