# Sales Tab Redesign - Plan 2: Section Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the BDS rate that exceeds 100%, remove `(unassigned)` rows from BDS/SME performance tables, and add a bold pinned "TEAM TOTAL" row to the SDR, BDS, and SME performance tables.

**Architecture:** Two pure, tested units in `reconcile.py` (a BDS-rate fix and a reusable `team_total_row()` helper). Render-layer wiring in `sections/sales.py` filters unassigned and prepends/bolds the total row. Money stays on the reverted `deal.amount` logic - no tier engine.

**Tech Stack:** Python 3, pandas, pytest, Streamlit (pandas Styler must use `.apply(axis=1)`, not `.map`, for Streamlit Cloud compat).

**Spec:** `docs/superpowers/specs/2026-06-09-sales-tab-redesign-design.md` (money sections superseded by the revert; section-layout requirements stand).

**Out of scope:** Team Summary card strip (existing Money section covers it), Asset Performance / Upcoming Calls / Roster (Plan 3).

---

### Task 1: Fix BDS rate >100% (intersection numerators)

`sales_bds_rollup` computes `booking_rate = sme_booked / shows` where `sme_booked` counts contacts who booked a Strategy meeting **without requiring they showed the 15-min**, so it can exceed `shows` -> rate >100%. `dq_rate = disqualified / shows` has the same flaw. Fix: intersect both numerators with `held_15_ids` (the showed set), so each numerator is a subset of `shows`.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`sales_bds_rollup`, lines ~1158-1174 - the `rows` loop)
- Test: `dashboard/tests/test_sales_rollups.py`

- [ ] **Step 1: Write the failing test**

Add to `dashboard/tests/test_sales_rollups.py` (imports `sales_bds_rollup` already exist there; if not, add it):

```python
def test_bds_booking_and_dq_rates_capped_at_100():
    """sme_booked / disqualified must be a subset of shows, so rates <= 100%."""
    contacts = pd.DataFrame([
        {"hs_id": "1", "bds": "b1"},
        {"hs_id": "2", "bds": "b1"},
    ])
    meetings = pd.DataFrame([
        # c1: showed the 15-min (COMPLETE) AND booked a strategy
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-05-01T00:00:00Z"},
        {"meeting_id": "m2", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "SCHEDULED", "start_time": "2026-05-03T00:00:00Z"},
        # c2: did NOT show the 15-min (SCHEDULED) but still booked a strategy
        {"meeting_id": "m3", "contact_id": "2", "activity_type": "15 min call",
         "outcome": "SCHEDULED", "start_time": "2026-05-02T00:00:00Z"},
        {"meeting_id": "m4", "contact_id": "2", "activity_type": "Strategy Call",
         "outcome": "SCHEDULED", "start_time": "2026-05-04T00:00:00Z"},
    ])
    r = sales_bds_rollup(
        contacts=contacts, meetings=meetings,
        contact_deals=pd.DataFrame(columns=["contact_id", "deal_id"]),
        deals=pd.DataFrame(columns=["deal_id", "dealstage"]),
        stages_15min_dq=set(),
    )
    row = r.iloc[0]
    assert row["appointments"] == 2          # both booked a 15-min
    assert row["shows"] == 1                  # only c1 was COMPLETE
    assert row["sme_booked"] == 1             # only c1 showed AND booked strategy
    assert row["booking_rate"] == 1.0         # 1/1, was 2/1 = 2.0 before the fix
    assert row["booking_rate"] <= 1.0
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py::test_bds_booking_and_dq_rates_capped_at_100 -q`
Expected: FAIL (`sme_booked == 2`, `booking_rate == 2.0`).

- [ ] **Step 3: Fix the rollup**

In `sales_bds_rollup`, inside the `for bds_id, grp in contacts.groupby(...)` loop, change the `sme_booked` and `dq` lines (currently `len(ids & booked_strat_ids)` and `len(ids & dq_contact_ids)`) to intersect with `held_15_ids`:

```python
        sme_booked = len(ids & held_15_ids & booked_strat_ids)
        dq = len(ids & held_15_ids & dq_contact_ids)
```

Update the docstring bullets for `sme_booked` and `disqualified` to note they count only contacts who **showed** the 15-min first (so the booking/DQ rates are true post-show conversions and cannot exceed 100%).

- [ ] **Step 4: Run it, confirm it passes**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py -q`
Expected: PASS (this test + all existing rollup tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_sales_rollups.py
git commit -m "fix: BDS booking/DQ rates intersect with shows (no >100%)"
```

---

### Task 2: `team_total_row()` helper

A pure helper that prepends a "TEAM TOTAL" row to a rollup dataframe: sums the count columns and recomputes rate columns from the summed numerators/denominators. Used by all three performance tables.

**Files:**
- Modify: `dashboard/data/reconcile.py` (add near the other sales rollups)
- Test: `dashboard/tests/test_sales_rollups.py`

- [ ] **Step 1: Write the failing test**

```python
def test_team_total_row_sums_and_recomputes_rates():
    from dashboard.data.reconcile import team_total_row
    df = pd.DataFrame([
        {"sme_id": "Dr A", "appointments": 4, "showed": 3, "deals_closed": 2,
         "show_rate": 0.75, "close_rate": 2/3, "revenue": 80000.0},
        {"sme_id": "Dr B", "appointments": 6, "showed": 3, "deals_closed": 1,
         "show_rate": 0.5, "close_rate": 1/3, "revenue": 40000.0},
    ])
    out = team_total_row(
        df,
        sum_cols=["appointments", "showed", "deals_closed", "revenue"],
        rate_cols={"show_rate": ("showed", "appointments"),
                   "close_rate": ("deals_closed", "showed")},
        label_col="sme_id",
    )
    total = out.iloc[0]                       # prepended at top
    assert total["sme_id"] == "TEAM TOTAL"
    assert total["appointments"] == 10
    assert total["showed"] == 6
    assert total["deals_closed"] == 3
    assert total["revenue"] == 120000.0
    assert total["show_rate"] == 0.6          # 6/10, not avg of 0.75 & 0.5
    assert total["close_rate"] == 0.5         # 3/6
    assert len(out) == 3                       # total + 2 reps
    assert list(out["sme_id"])[1:] == ["Dr A", "Dr B"]
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py::test_team_total_row_sums_and_recomputes_rates -q`
Expected: FAIL (`ImportError: cannot import name 'team_total_row'`).

- [ ] **Step 3: Implement**

Add to `reconcile.py` (near `sales_sme_rollup`):

```python
def team_total_row(df, *, sum_cols, rate_cols, label_col, label="TEAM TOTAL"):
    """Prepend a team-total row to a per-rep rollup.

    - sum_cols: columns summed across rows.
    - rate_cols: {col: (numerator_col, denominator_col)} recomputed from the
      SUMMED totals (not averaged), so a team rate is true aggregate.
    - label_col: column that holds `label`; every other non-sum/non-rate column
      is left blank ("") in the total row.
    Returns a new df with the total row at index 0 and the original rows after.
    """
    if df.empty:
        return df
    total = {c: "" for c in df.columns}
    total[label_col] = label
    for c in sum_cols:
        total[c] = df[c].sum()
    for c, (num, den) in rate_cols.items():
        d = df[den].sum()
        total[c] = (df[num].sum() / d) if d else None
    return pd.concat([pd.DataFrame([total]), df], ignore_index=True)
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_sales_rollups.py
git commit -m "feat: add team_total_row helper for rollup tables"
```

---

### Task 3: Wire into SDR / BDS / SME render (remove unassigned + bold total row)

In `sections/sales.py`, for each of the three performance tables: (a) map owner ids to names (already done), (b) for BDS and SME drop rows whose mapped owner is `(unassigned)`, (c) prepend the TEAM TOTAL row via `team_total_row` (computed on the RAW numeric rollup BEFORE percent/money formatting), (d) bold the TEAM TOTAL row in the Styler.

**Files:**
- Modify: `dashboard/sections/sales.py` (SDR render ~lines 690-740, BDS render ~lines 768-789, SME render ~lines 857-895 - grep to confirm current lines)
- Modify: `dashboard/config.py` OR `sections/sales.py` - add a bold-total styler helper (see Step 2)

- [ ] **Step 1: Locate the three render blocks**

Run: `grep -n "sales_sdr_rollup\|sales_bds_rollup\|sales_sme_rollup\|cfg.style_unassigned" dashboard/sections/sales.py`
Read each block. Note the exact column names each renames to and the order of map/format operations.

- [ ] **Step 2: Add a bold-total Styler helper**

Add this near the top of `sections/sales.py` (after the `_fmt_*` helpers):

```python
def _style_perf_table(df, *, owner_cols, total_label_col):
    """Style a performance table: existing unassigned styling + bold TEAM TOTAL row.

    Returns a pandas Styler. Bolding uses .apply(axis=1) for Streamlit Cloud
    (pandas < 2.1) compatibility.
    """
    styler = cfg.style_unassigned(df, columns=owner_cols)

    def _bold_total(row):
        is_total = str(row.get(total_label_col, "")) == "TEAM TOTAL"
        return ["font-weight: bold" if is_total else "" for _ in row]

    return styler.apply(_bold_total, axis=1)
```

Verify `cfg.style_unassigned` returns a `Styler` (it does) so `.apply` can chain. If it returns a styled object that does not accept further `.apply`, instead build the combined styling in one function. Confirm by reading `cfg.style_unassigned`.

- [ ] **Step 3: SME table - drop unassigned + total row + bold**

In the SME render block, after `sme = sales_sme_rollup(...)` and the `display = sme.copy()` line, BEFORE the percent/money formatting:

```python
        display["sme_id"] = display["sme_id"].map(cfg.resolve_owner)
        display = display[display["sme_id"] != "(unassigned)"].reset_index(drop=True)
        display = team_total_row(
            display,
            sum_cols=["appointments", "showed", "deals_closed", "first_closes",
                      "fu_closes", "disqualified", "revenue"],
            rate_cols={"show_rate": ("showed", "appointments"),
                       "close_rate": ("deals_closed", "showed"),
                       "first_close_rate": ("first_closes", "showed"),
                       "fu_close_rate": ("fu_closes", "showed"),
                       "dq_rate": ("disqualified", "showed")},
            label_col="sme_id",
        )
```

(Remove the now-duplicate `display["sme_id"] = display["sme_id"].map(cfg.resolve_owner)` if it already existed below; keep only the one above.) Then the existing `_fmt_pct`/`_fmt_money` mapping lines run on the combined df (they handle None via the `_fmt_*` guards). Finally replace the `cfg.style_unassigned(display, columns=["SME"])` call in the `st.dataframe` with `_style_perf_table(display_renamed, owner_cols=["SME"], total_label_col="SME")` - note the rename to "SME" happens in the existing `.rename(...)`, so apply `_style_perf_table` to the renamed frame using `total_label_col="SME"`.

`team_total_row` must be imported: add `team_total_row` to the `from dashboard.data.reconcile import (...)` block.

- [ ] **Step 4: BDS table - same treatment**

In the BDS render block, after `display["bds_id"] = display["bds_id"].map(cfg.resolve_owner)`:

```python
        display = display[display["bds_id"] != "(unassigned)"].reset_index(drop=True)
        display = team_total_row(
            display,
            sum_cols=["appointments", "shows", "sme_booked", "disqualified"],
            rate_cols={"show_rate": ("shows", "appointments"),
                       "booking_rate": ("sme_booked", "shows"),
                       "dq_rate": ("disqualified", "shows")},
            label_col="bds_id",
        )
```

Then existing `_fmt_pct` maps run, the existing `.rename(...)` to "BDS" runs, and the `st.dataframe` styler becomes `_style_perf_table(display, owner_cols=["BDS"], total_label_col="BDS")`.

- [ ] **Step 5: SDR table - total row (no unassigned filter; SDR rows are AirCall users)**

In the SDR render block, after the rollup and owner/name mapping, before formatting:

```python
        display = team_total_row(
            display,
            sum_cols=["dials", "pick_ups", "contacts_made", "talk_time_min",
                      "appointments_booked"],
            rate_cols={"booking_rate": ("appointments_booked", "contacts_made")},
            label_col="user_name",
        )
```

`median_speed_to_lead_min` is a median and cannot be summed - leave it blank ("") in the total row (team_total_row already blanks non-sum/non-rate columns). Bold the total via `_style_perf_table(display, owner_cols=[...], total_label_col="user_name")` (use whatever owner column the SDR table already styles; if it styles none, call `team_total_row` then a Styler that only bolds - in that case pass `owner_cols=[]` and confirm `cfg.style_unassigned` tolerates an empty columns list, else bold inline without style_unassigned).

- [ ] **Step 6: Update captions**

Add to each of the three section captions: "**Team Total** row (bold) = sum across reps; rates recomputed from the totals. `(unassigned)` reps are excluded." (SDR caption: omit the unassigned clause.)

- [ ] **Step 7: Compile + run full suite**

Run: `python -m py_compile dashboard/sections/sales.py && python -m pytest dashboard/tests -q`
Expected: compile OK, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/sections/sales.py
git commit -m "feat: team-total rows + drop unassigned on SDR/BDS/SME tables"
```

---

### Task 4: Verify + push

- [ ] **Step 1: Full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: PASS (50 prior + 2 new from Tasks 1-2 = 52).

- [ ] **Step 2: Push**

```bash
git push origin feature/cmo-dashboard
```

---

## Self-Review notes

- BDS fix and `team_total_row` are pure + unit-tested. Render wiring is display-only (verified by compile + manual).
- Team totals are computed over the VISIBLE (assigned) reps after dropping `(unassigned)`, so the rows sum to the total. If unassigned activity is material, that signals an ownership-data gap to fix in HubSpot, not a dashboard concern - note this in the caption is optional.
- `median_speed_to_lead_min` intentionally blank in the SDR total row (medians do not aggregate).
- Styler bolding uses `.apply(axis=1)` per the Streamlit Cloud / pandas<2.1 constraint.
