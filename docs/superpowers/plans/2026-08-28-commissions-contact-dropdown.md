# COMMISSIONS Contact Drill-Down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-role HubSpot-contact drill-down to the COMMISSIONS tab so Garrett/Callum can see, and click into, every contact behind each SDR/BDS/SME's monthly commission.

**Architecture:** The detail is emitted from the SAME loop that computes the totals, so per-rep detail sums equal the payout by construction. A new per-contact SDR-call helper feeds both the (unchanged) aggregate and the new detail; `compute_monthly_commissions` gains a `detail` DataFrame; the render adds one expander per role.

**Tech Stack:** Python, pandas, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-commissions-contact-dropdown-design.md`

## Global Constraints

- Detail rows are emitted from the identical code path that increments the totals — never a parallel/duplicated commission calculation. Reconciliation (per role+rep, `sum(detail.amount) == table total`) must hold by construction and be asserted by a test.
- Commission rates, stages, and the no-double-pay conversion logic are UNCHANGED. This feature only adds detail emission and a richer SDR-call input.
- MAP-style money-critical care: this is payroll math. Follow TDD; run the full commission test file before committing.
- `detail` DataFrame columns (exact): `role, rep_id, contact_id, contact_name, event, amount`. `role` in {"sdr","bds","sme"}. `event` in {"disco","strategy","full","ninety","conversion"}.
- `sdr_completion_contacts` output columns (exact): `sdr_owner, contact_id, contact_name, event, temp`. `event` in {"disco","strategy"}. `temp` in {"warm","cold"}.
- Gerri produces NO detail rows and keeps its single `st.metric`.
- No em dashes or AI-style punctuation in user-facing strings; standard hyphens only.
- Write files with Write/Edit only. Run tests via the Bash tool from repo root `C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent`.
- Branch: `feature/cmo-dashboard`. Commit after each task; do not push (Kurt pushes).
- Commit trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: `sdr_completion_contacts` helper + refactor `sdr_completions_by_owner`

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `sdr_completion_contacts` before `sdr_completions_by_owner` ~line 3135; reimplement `sdr_completions_by_owner` as an aggregation over it)
- Test: `dashboard/tests/test_commissions.py`

**Interfaces:**
- Produces: `sdr_completion_contacts(meetings, contacts, start, end) -> pd.DataFrame` with columns `sdr_owner, contact_id, contact_name, event ("disco"|"strategy"), temp ("warm"|"cold")`.
- `sdr_completions_by_owner(meetings, contacts, start, end) -> dict[str, dict[str,int]]` keeps its exact existing output shape `{owner: {disco_warm, disco_cold, strat_warm, strat_cold}}`.

- [ ] **Step 1: Write the failing test for the per-contact helper**

Append to `dashboard/tests/test_commissions.py` (note `sdr_completion_contacts` import):

```python
from dashboard.data.reconcile import sdr_completion_contacts


def test_sdr_completion_contacts_rows():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "S1", "name": "Alice",
         "typeform_asset_download": "Top 10 typeform"},   # warm
        {"hs_id": "2", "sdr_owner": "S1", "name": "Bob",
         "typeform_asset_download": ""},                    # cold
    ])
    meetings = pd.DataFrame([
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "COMPLETED",
         "start_time": "2026-06-03T15:00:00Z"},             # warm disco held
        {"contact_id": "2", "activity_type": "Strategy Call", "outcome": "COMPLETE - QUALIFIED",
         "start_time": "2026-06-04T15:00:00Z"},             # cold strategy held
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-06-05T15:00:00Z"},             # not held -> ignored
    ])
    out = sdr_completion_contacts(meetings, contacts, date(2026, 6, 1), date(2026, 6, 30))
    rows = {(r["contact_id"], r["event"], r["temp"], r["contact_name"], r["sdr_owner"])
            for _, r in out.iterrows()}
    assert rows == {("1", "disco", "warm", "Alice", "S1"),
                    ("2", "strategy", "cold", "Bob", "S1")}


def test_sdr_completion_contacts_empty():
    empty = pd.DataFrame(columns=["contact_id", "activity_type", "outcome", "start_time"])
    out = sdr_completion_contacts(empty, pd.DataFrame(), date(2026, 6, 1), date(2026, 6, 30))
    assert list(out.columns) == ["sdr_owner", "contact_id", "contact_name", "event", "temp"]
    assert out.empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_commissions.py::test_sdr_completion_contacts_rows dashboard/tests/test_commissions.py::test_sdr_completion_contacts_empty -v`
Expected: FAIL — `ImportError: cannot import name 'sdr_completion_contacts'`.

- [ ] **Step 3: Add `sdr_completion_contacts` and refactor the aggregate**

In `dashboard/data/reconcile.py`, REPLACE the existing `sdr_completions_by_owner` function (currently ~lines 3135-3166) with these two functions:

```python
def sdr_completion_contacts(meetings: pd.DataFrame, contacts: pd.DataFrame,
                            start: date, end: date) -> pd.DataFrame:
    """Held 15-min + strategy completions in [start, end], one row per contact
    meeting, tagged with the lead's sdr_owner and warm/cold. Columns:
    sdr_owner, contact_id, contact_name, event ("disco"|"strategy"),
    temp ("warm"|"cold"). Held = outcome COMPLETE*; month = meeting start_time;
    rows with an empty sdr_owner are dropped. Source of truth for SDR call
    commissions (both the aggregate and the per-contact detail)."""
    cols = ["sdr_owner", "contact_id", "contact_name", "event", "temp"]
    if meetings.empty or contacts.empty:
        return pd.DataFrame(columns=cols)
    owner_map = dict(zip(contacts["hs_id"].astype(str),
                         contacts["sdr_owner"].fillna("").astype(str)))
    warm_map = dict(zip(
        contacts["hs_id"].astype(str),
        contacts["typeform_asset_download"].fillna("").astype(str).str.strip() != "",
    ))
    name_map = dict(zip(contacts["hs_id"].astype(str),
                        contacts.get("name", pd.Series(dtype=object)).fillna("").astype(str)))
    types = meetings["activity_type"].fillna("").astype(str).str.lower()
    outc = meetings["outcome"].fillna("").astype(str).str.upper()
    mstart = pd.to_datetime(meetings["start_time"], utc=True, errors="coerce").dt.date
    cid = meetings["contact_id"].astype(str)
    held = outc.str.startswith("COMPLETE")
    in_win = mstart.apply(lambda d: bool(pd.notna(d)) and start <= d <= end)
    sdr = cid.map(owner_map).fillna("")
    warm = cid.map(warm_map).fillna(False)
    base = held & in_win & (sdr != "")
    rows = []
    for kind, kmask in (("disco", discovery_mask(types)),
                        ("strategy", types.str.contains("strategy", na=False))):
        sub = base & kmask
        for c, o, w in zip(cid[sub], sdr[sub], warm[sub]):
            rows.append({"sdr_owner": o, "contact_id": c,
                         "contact_name": name_map.get(c, ""),
                         "event": kind, "temp": "warm" if w else "cold"})
    return pd.DataFrame(rows, columns=cols)


def sdr_completions_by_owner(meetings: pd.DataFrame, contacts: pd.DataFrame,
                             start: date, end: date) -> dict[str, dict[str, int]]:
    """Held 15-min + strategy completions in [start, end], grouped by the lead's
    sdr_owner, split warm (contact has a typeform) vs cold. Held = outcome
    COMPLETE*. Month = meeting start_time. Returns
    {sdr_owner: {disco_warm, disco_cold, strat_warm, strat_cold}}. Thin
    aggregation over sdr_completion_contacts (single source of truth)."""
    detail = sdr_completion_contacts(meetings, contacts, start, end)
    out: dict[str, dict[str, int]] = {}
    for _, r in detail.iterrows():
        rec = out.setdefault(str(r["sdr_owner"]),
                             {"disco_warm": 0, "disco_cold": 0,
                              "strat_warm": 0, "strat_cold": 0})
        prefix = "disco" if r["event"] == "disco" else "strat"
        rec[f"{prefix}_{r['temp']}"] += 1
    return out
```

- [ ] **Step 4: Run the new tests + the existing aggregate regression test**

Run: `python -m pytest dashboard/tests/test_commissions.py -k "sdr_completion_contacts or sdr_completions_by_owner" -v`
Expected: PASS — including the pre-existing `test_sdr_completions_by_owner_warm_cold_and_type` (proves the refactor preserved the aggregate output).

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_commissions.py
git commit -m "feat(commissions): sdr_completion_contacts helper; aggregate reuses it

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `compute_monthly_commissions` — per-contact input + `detail` output

**Files:**
- Modify: `dashboard/data/reconcile.py` (`compute_monthly_commissions` ~lines 3169-3260)
- Test: `dashboard/tests/test_commissions.py`

**Interfaces:**
- Consumes: `sdr_completion_contacts` output (Task 1) as the new 2nd parameter.
- Produces: `compute_monthly_commissions(closed_deals, sdr_call_contacts, start, end, *, rates)` returning `{"sdr","bds","sme","gerri","detail"}` where `detail` is a DataFrame with columns `role, rep_id, contact_id, contact_name, event, amount`. The `sdr`/`bds`/`sme` frames and `gerri` dict are unchanged.

- [ ] **Step 1: Update the existing compute tests to the new input, and add detail tests**

In `dashboard/tests/test_commissions.py`:

(a) Add a module-level empty-calls constant near the other compute-test helpers (after `_MAY = ...`):

```python
_NO_CALLS = pd.DataFrame(columns=["sdr_owner", "contact_id", "contact_name", "event", "temp"])
```

(b) Add `contact_name` to the `_deal` helper so detail rows carry a name. Change its returned dict to include:

```python
        "hs_id": did, "contact_name": f"C-{did}", "sdr_owner": sdr, "bds": bds, "sme": sme,
```

(c) Replace the `{}` second argument in the three deal-based compute tests with `_NO_CALLS`:
- `test_commissions_direct_full_close_warm`: `compute_monthly_commissions(deals, _NO_CALLS, *_JUN, rates=CR)`
- `test_commissions_90day_then_conversion_split_across_months`: every `compute_monthly_commissions(deals, {}, ...)` becomes `compute_monthly_commissions(deals, _NO_CALLS, ...)`
- `test_commissions_diy_pays_only_gerri`: `compute_monthly_commissions(deals, _NO_CALLS, *_JUN, rates=CR)` and add `assert res["detail"].empty`

(d) Replace `test_commissions_sdr_call_completions` with the per-contact version:

```python
def test_commissions_sdr_call_completions():
    calls = pd.DataFrame([
        {"sdr_owner": "S1", "contact_id": "a", "contact_name": "A", "event": "disco", "temp": "warm"},
        {"sdr_owner": "S1", "contact_id": "b", "contact_name": "B", "event": "disco", "temp": "warm"},
        {"sdr_owner": "S1", "contact_id": "c", "contact_name": "C", "event": "disco", "temp": "cold"},
        {"sdr_owner": "S1", "contact_id": "d", "contact_name": "D", "event": "strategy", "temp": "warm"},
    ])
    res = compute_monthly_commissions(pd.DataFrame(columns=["hs_id"]), calls, *_JUN, rates=CR)
    sdr = res["sdr"].set_index("rep_id")
    # disco: 2*20 + 1*100 = 140 ; strategy: 1*100 = 100
    assert sdr.loc["S1", "disco"] == 140.0 and sdr.loc["S1", "strategy"] == 100.0
    assert sdr.loc["S1", "total"] == 240.0
```

(e) Add the detail + reconciliation test:

```python
def test_commissions_detail_reconciles_to_totals():
    deals = pd.DataFrame([_deal("d1", "24094605", sdr="S1", bds="B1", sme="M1",
                                warm=True, entered_primary1="2026-06-10T00:00:00Z")])
    calls = pd.DataFrame([
        {"sdr_owner": "S1", "contact_id": "x", "contact_name": "X", "event": "disco", "temp": "warm"},
    ])
    res = compute_monthly_commissions(deals, calls, *_JUN, rates=CR)
    det = res["detail"]
    assert list(det.columns) == ["role", "rep_id", "contact_id", "contact_name", "event", "amount"]
    # Reconciliation: per role+rep, detail sum equals the summary-table total.
    for role in ("sdr", "bds", "sme"):
        tbl = res[role].set_index("rep_id")
        for rep in tbl.index:
            s = det[(det["role"] == role) & (det["rep_id"] == rep)]["amount"].sum()
            assert abs(s - tbl.loc[rep, "total"]) < 1e-9
    # SDR rows: a full-close (200) from the deal + a disco (20) from the call.
    sdr_det = det[(det["role"] == "sdr") & (det["rep_id"] == "S1")]
    assert set(sdr_det["event"]) == {"full", "disco"}
    assert "X" in set(sdr_det["contact_name"])       # the call contact
    assert "C-d1" in set(sdr_det["contact_name"])     # the deal contact
```

- [ ] **Step 2: Run to verify the new/updated tests fail**

Run: `python -m pytest dashboard/tests/test_commissions.py -k "compute or detail or sdr_call" -v`
Expected: FAIL — the detail assertions fail (`KeyError: 'detail'`) and/or the signature still expects a dict.

- [ ] **Step 3: Rewrite `compute_monthly_commissions` to take per-contact calls and emit `detail`**

In `dashboard/data/reconcile.py`, change the signature and body. New signature line:

```python
def compute_monthly_commissions(closed_deals: pd.DataFrame,
                                sdr_call_contacts: pd.DataFrame, start: date, end: date,
                                *, rates: dict) -> dict:
```

Update the docstring's 2nd-arg line to:
```
    sdr_call_contacts: sdr_completion_contacts(...) output for the SAME month.
```
and the Returns line to mention `"detail"`.

Add a `detail_rows` list and change `_add` to record detail. Replace the accumulator setup + `_add` (currently ~lines 3192-3202) with:

```python
    # accumulators: role -> rep -> {component: amount}
    sdr: dict = {}
    bds: dict = {}
    sme: dict = {}
    gerri_count = 0
    detail_rows: list = []  # role, rep_id, contact_id, contact_name, event, amount

    def _add(acc, role, rep, comp, amt, cid, cname):
        if not rep:
            return
        acc.setdefault(rep, {})
        acc[rep][comp] = acc[rep].get(comp, 0.0) + amt
        detail_rows.append({"role": role, "rep_id": rep, "contact_id": cid,
                            "contact_name": cname, "event": comp, "amount": amt})
```

Replace the deal loop body (currently ~lines 3204-3234) with (adds `cid`/`cname` and the role literal to each `_add`):

```python
    for _, r in closed_deals.iterrows():
        stage = str(r.get("dealstage") or "")
        warm = str(r.get("typeform") or "").strip() != ""
        temp = "warm" if warm else "cold"
        sdr_owner = str(r.get("sdr_owner") or "")
        bds_owner = str(r.get("bds") or "")
        sme_owner = str(r.get("sme") or "")
        cid = str(r.get("hs_id") or "")
        cname = str(r.get("contact_name") or "")
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
            _add(sdr, "sdr", sdr_owner, "ninety", rates["sdr"]["ninety_day"][temp], cid, cname)
            _add(bds, "bds", bds_owner, "ninety", rates["bds"]["ninety_day"], cid, cname)
            _add(sme, "sme", sme_owner, "ninety", rates["sme"]["ninety_day"], cid, cname)
        if stage in full_stages:
            full_month = p1 if p1 is not None else close_d
            if _in(full_month):
                if d90 is not None:  # converted -> bonus only
                    _add(sdr, "sdr", sdr_owner, "conversion", rates["sdr"]["conversion_bonus"][temp], cid, cname)
                    _add(bds, "bds", bds_owner, "conversion", rates["bds"]["conversion_bonus"], cid, cname)
                    _add(sme, "sme", sme_owner, "conversion", rates["sme"]["conversion_bonus"], cid, cname)
                else:                # direct full close
                    _add(sdr, "sdr", sdr_owner, "full", rates["sdr"]["full_close"][temp], cid, cname)
                    _add(bds, "bds", bds_owner, "full", rates["bds"]["full_close"], cid, cname)
                    _add(sme, "sme", sme_owner, "full", rates["sme"]["full_close"], cid, cname)
```

Replace the SDR-call aggregate loop (currently ~lines 3236-3243) with a per-contact loop:

```python
    # SDR call completions (this month) -- one detail row per held call
    if sdr_call_contacts is not None and not sdr_call_contacts.empty:
        for _, cc in sdr_call_contacts.iterrows():
            owner = str(cc.get("sdr_owner") or "")
            temp = "warm" if cc.get("temp") == "warm" else "cold"
            comp = "disco" if cc.get("event") == "disco" else "strategy"
            rate_key = "disco_complete" if comp == "disco" else "strategy_complete"
            amt = rates["sdr"][rate_key][temp]
            _add(sdr, "sdr", owner, comp, amt,
                 str(cc.get("contact_id") or ""), str(cc.get("contact_name") or ""))
```

In the `return {...}` dict, add the `detail` key (build the frame just before returning):

```python
    detail = pd.DataFrame(
        detail_rows,
        columns=["role", "rep_id", "contact_id", "contact_name", "event", "amount"])
    return {
        "sdr": _frame(sdr, ["disco", "strategy", "full", "ninety", "conversion"]),
        "bds": _frame(bds, ["full", "ninety", "conversion"]),
        "sme": _frame(sme, ["full", "ninety", "conversion"]),
        "gerri": {"count": gerri_count, "total": gerri_count * rates["gerri_per_close"]},
        "detail": detail,
    }
```

- [ ] **Step 4: Run the full commission test file**

Run: `python -m pytest dashboard/tests/test_commissions.py -v`
Expected: PASS — all compute tests (now using `_NO_CALLS` / per-contact calls), the detail + reconciliation test, and the Task 1 helper tests.

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_commissions.py
git commit -m "feat(commissions): compute_monthly_commissions emits reconciling per-contact detail

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Render per-role detail expanders (COMMISSIONS tab)

**Files:**
- Modify: `dashboard/sections/commissions.py` (imports ~line 12; call site ~lines 85-87; render ~lines 89-111)

**Interfaces:**
- Consumes: `sdr_completion_contacts` (Task 1) and `compute_monthly_commissions`'s new `detail` key (Task 2).
- Produces: no new callable; UI only.

- [ ] **Step 1: Swap the SDR-call helper import**

In `dashboard/sections/commissions.py`, change the reconcile import (line ~12-14) from:

```python
from dashboard.data.reconcile import (
    build_closed_deals_table, sdr_completions_by_owner, compute_monthly_commissions,
)
```

to:

```python
from dashboard.data.reconcile import (
    build_closed_deals_table, sdr_completion_contacts, compute_monthly_commissions,
)
```

- [ ] **Step 2: Feed per-contact calls into the engine**

Replace the call-completions line (~line 85) and the compute call (~line 87):

```python
    call_contacts = sdr_completion_contacts(meetings, mc, m_start, m_end) if not mc.empty \
        else pd.DataFrame(columns=["sdr_owner", "contact_id", "contact_name", "event", "temp"])

    res = compute_monthly_commissions(ct, call_contacts, m_start, m_end, rates=cfg.COMMISSION_RATES)
```

- [ ] **Step 3: Add the per-role detail expander helper and call it after each role table**

In `render_commissions`, after the `_show` inner function definition (~line 100) add a `_detail_expander` helper and the event-label map:

```python
    _EVENT_LABELS = {"disco": "15-min Call", "strategy": "Strategy Call",
                     "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion"}

    def _detail_expander(role, role_label):
        with st.expander(f"{role_label} commission detail (contacts)"):
            d = res["detail"]
            d = d[d["role"] == role].copy()
            if not d.empty:
                d["Rep"] = d["rep_id"].map(cfg.resolve_owner)
                d = d[d["Rep"] != "(unassigned)"]
            if d.empty:
                st.caption(f"No {role_label} commission detail in {m_start.strftime('%B %Y')}.")
                return
            d = d.sort_values(["Rep", "amount"], ascending=[True, False])
            d["Contact"] = d["contact_name"]
            d["Event"] = d["event"].map(_EVENT_LABELS)
            d["Open"] = d["contact_id"].map(cfg.hubspot_contact_url)
            d["Amount"] = d["amount"].map(_MONEY)
            d = d[["Rep", "Contact", "Event", "Amount", "Open"]]
            st.dataframe(
                d, use_container_width=True, hide_index=True,
                column_config={"Open": st.column_config.LinkColumn(
                    "Open", display_text="HubSpot ↗")})
```

Then interleave the expander after each role's `_show(...)`. The current block calls `_show("SDR", ...)`, `_show("BDS", ...)`, `_show("SME", ...)` consecutively; add a `_detail_expander(...)` call after each so the final ordering is:

```python
    _show("SDR", res["sdr"].rename(columns={
        "disco": "15-min", "strategy": "Strategy", "full": "Full Close",
        "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["15-min", "Strategy", "Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("sdr", "SDR")
    _show("BDS", res["bds"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("bds", "BDS")
    _show("SME", res["sme"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("sme", "SME")
```

(The Gerri `st.metric` block below stays unchanged.)

- [ ] **Step 4: Sanity-check import + full suite**

Run: `python -c "import dashboard.sections.commissions"` (Expected: no error.)
Run: `python -m pytest dashboard/tests/ -q` (Expected: all pass.)

- [ ] **Step 5: Commit**

```bash
git add dashboard/sections/commissions.py
git commit -m "feat(commissions): per-role HubSpot contact drill-down expanders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Live verification (after all tasks)

Not a code task, but required before declaring done:
- Open COMMISSIONS, pick a recent month with commissions.
- Under each role table, expand the detail: confirm the contacts listed, that "Open" links to the right HubSpot contacts, and that each rep's detail rows sum to that rep's Total in the table above (spot-check one SDR whose total mixes calls + a close).

## Self-Review (completed)

1. **Spec coverage:** per-contact helper + aggregate refactor (Task 1), detail-emitting engine with reconciliation (Task 2), per-role expanders + link column (Task 3). All spec sections A/B/C covered.
2. **Placeholder scan:** none — every step carries concrete code.
3. **Type consistency:** `detail` columns `role, rep_id, contact_id, contact_name, event, amount` are identical across Task 2 (producer) and Task 3 (consumer); `sdr_completion_contacts` columns `sdr_owner, contact_id, contact_name, event, temp` identical across Task 1 (producer), Task 2 (consumer), Task 3 (call site). `event` values {disco,strategy,full,ninety,conversion} match the `_EVENT_LABELS` map keys. Signature change to `compute_monthly_commissions` is reflected in every call site (render Task 3) and every test (Task 2).
4. **Reconciliation guaranteed:** `_add` increments the accumulator and appends the detail row with the same `amt` in one place, so per role+rep the detail sum equals the summary total by construction; Task 2's `test_commissions_detail_reconciles_to_totals` asserts it.
