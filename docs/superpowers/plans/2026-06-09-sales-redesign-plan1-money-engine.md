# Sales Tab Redesign - Plan 1: Tier Money Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace HubSpot's `deal.amount` ($40k placeholder) with tier-derived revenue and estimated cash collected, so all money figures are correct.

**Architecture:** Add numeric tier constants to `config.py` and two pure functions to `reconcile.py` - `classify_tier()` (contract_tier string -> plan + group) and `deal_money()` (plan/group/closedate -> booked revenue + est cash). Wire them into the shared money functions (`build_closed_deals_table`, `windowed_sales_money`, `compute_ytd_money`) and the SME revenue rollup. Because `build_closed_deals_table` and `compute_ytd_money` are shared, the Executive "Money YTD" and Metrics money also become correct - intended.

**Tech Stack:** Python 3, pandas, pytest. Functions are pure (dependency-injected config values), matching the existing reconcile.py style.

**Spec:** `docs/superpowers/specs/2026-06-09-sales-tab-redesign-design.md`

**Cross-tab note / known follow-ups (NOT in this plan):**
- `executive_kpis()` computes its own `new_revenue` from `deal.amount`/`group_default` (separate from `compute_ytd_money`). It stays on the old calc here and is a follow-up when the Executive tab is addressed.
- Plan 2 (section restructure) and Plan 3 (Asset Performance / Upcoming Calls / Roster) build on this money API.

---

### Task 1: Tier constants + `classify_tier()`

**Files:**
- Modify: `dashboard/config.py` (add constants near `GROUP_DEFAULT_DEAL_AMOUNT`, ~line 218)
- Modify: `dashboard/data/reconcile.py` (add `classify_tier` near `_group_from_tier`)
- Test: `dashboard/tests/test_money_engine.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_money_engine.py`:

```python
import pytest
from dashboard.data.reconcile import classify_tier


@pytest.mark.parametrize("raw,plan,group", [
    ("1:  PRIMARY", "FULL", "Chiro"),
    ("PT - Primary", "FULL", "PT"),
    ("90-DAY - C", "90DAY", "Chiro"),
    ("DIY - C", "DIY", "Chiro"),
    ("BASIC - NOT CERTIFIED", "BASIC", "Chiro"),
    ("PT - DIY", "DIY", "PT"),
    ("", "UNKNOWN", "Chiro"),
    (None, "UNKNOWN", "Chiro"),
])
def test_classify_tier(raw, plan, group):
    assert classify_tier(raw) == (plan, group)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_money_engine.py -q`
Expected: FAIL with `ImportError: cannot import name 'classify_tier'`

- [ ] **Step 3: Add constants to config.py**

Insert after the `GROUP_CASH_COLLECTED_PER_DEAL` block (after line 230):

```python
# --- Tier money model (Kurt, 2026-06-09) ---------------------------------
# HubSpot deal.amount is a flat $40k placeholder unrelated to the real
# contract, so all money is derived from contract_tier instead.
#   Full / PRIMARY: $1,997/mo x 24mo = $47,928 (Chiro)
#   90-Day:         $5,991 one-time (Chiro)
#   DIY:            $997/mo, month-to-month, no fixed term (Chiro)
#   PT Recovery   = 0.5 x Chiro for every tier.
FULL_MONTHLY = 1997.0
FULL_TERM_MONTHS = 24
NINETY_DAY_AMOUNT = 5991.0
DIY_MONTHLY = 997.0
PT_MULTIPLIER = 0.5
```

- [ ] **Step 4: Add `classify_tier` to reconcile.py**

Add immediately above `def _group_from_tier(` (find it with `grep -n "_group_from_tier" dashboard/data/reconcile.py`):

```python
def classify_tier(contract_tier) -> tuple[str, str]:
    """Map a HubSpot contract_tier string to (plan, group).

    plan in {"FULL", "90DAY", "DIY", "BASIC", "UNKNOWN"};
    group in {"Chiro", "PT"}. Substring match, order-sensitive: DIY / 90 /
    BASIC are checked before PRIMARY / FULL so e.g. "PT - DIY" is DIY, not FULL.
    """
    s = (str(contract_tier) if contract_tier is not None else "").upper()
    group = "PT" if "PT" in s else "Chiro"
    if "DIY" in s:
        plan = "DIY"
    elif "90" in s:
        plan = "90DAY"
    elif "BASIC" in s:
        plan = "BASIC"
    elif "PRIMARY" in s or "FULL" in s:
        plan = "FULL"
    else:
        plan = "UNKNOWN"
    return plan, group
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest dashboard/tests/test_money_engine.py -q`
Expected: PASS (8 cases)

- [ ] **Step 6: Commit**

```bash
git add dashboard/config.py dashboard/data/reconcile.py dashboard/tests/test_money_engine.py
git commit -m "feat: add tier money constants + classify_tier"
```

---

### Task 2: `deal_money()` per-deal calculator

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_months_elapsed` + `deal_money` below `classify_tier`)
- Test: `dashboard/tests/test_money_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_money_engine.py`:

```python
from datetime import date
from dashboard.data.reconcile import deal_money

RATES = dict(full_monthly=1997.0, full_term_months=24,
             ninety_day_amount=5991.0, diy_monthly=997.0, pt_multiplier=0.5)
TODAY = date(2026, 6, 9)


def test_deal_money_full_chiro():
    m = deal_money("FULL", "Chiro", "2026-04-15T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 47928.0          # 1997 * 24
    assert m["monthly"] == 1997.0
    assert m["est_cash_collected"] == 1997.0 * 2   # Apr->Jun = 2 months
    assert m["counts_as_sale"] is True


def test_deal_money_full_pt_halves():
    m = deal_money("FULL", "PT", "2026-06-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 23964.0          # 47928 / 2
    assert m["monthly"] == 998.5
    assert m["est_cash_collected"] == 998.5 * 1    # same month -> 1


def test_deal_money_full_caps_at_term():
    m = deal_money("FULL", "Chiro", "2023-01-01T00:00:00Z", TODAY, **RATES)
    assert m["est_cash_collected"] == 1997.0 * 24  # capped at 24mo


def test_deal_money_ninety_day():
    m = deal_money("90DAY", "Chiro", "2026-05-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 5991.0
    assert m["est_cash_collected"] == 5991.0       # one-time, not monthly
    assert m["monthly"] == 0.0


def test_deal_money_diy_accrues_no_tcv():
    m = deal_money("DIY", "Chiro", "2026-03-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 0.0              # no contract total
    assert m["monthly"] == 997.0
    assert m["est_cash_collected"] == 997.0 * 3    # Mar->Jun = 3


def test_deal_money_basic_excluded():
    m = deal_money("BASIC", "Chiro", "2026-05-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 0.0
    assert m["est_cash_collected"] == 0.0
    assert m["counts_as_sale"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_money_engine.py -q`
Expected: FAIL with `ImportError: cannot import name 'deal_money'`

- [ ] **Step 3: Implement `_months_elapsed` + `deal_money`**

Add directly below `classify_tier` in `reconcile.py`:

```python
def _months_elapsed(closedate, today) -> int:
    """Whole calendar months from close to today, floored at 1 (0 if no date)."""
    c = pd.to_datetime(closedate, utc=True, errors="coerce")
    if pd.isna(c):
        return 0
    months = (today.year - c.year) * 12 + (today.month - c.month)
    return max(1, months)


def deal_money(plan, group, closedate, today, *,
               full_monthly, full_term_months,
               ninety_day_amount, diy_monthly, pt_multiplier) -> dict:
    """Tier-derived money for one closed deal.

    Returns {booked_revenue, est_cash_collected, monthly, counts_as_sale}.
    - FULL:  booked = monthly x term;  cash = monthly x min(months, term)
    - 90DAY: booked = cash = one-time amount
    - DIY:   booked = 0 (no TCV);      cash = monthly x months
    - BASIC/UNKNOWN: all 0, counts_as_sale False
    PT group halves every dollar figure (pt_multiplier).
    """
    factor = pt_multiplier if group == "PT" else 1.0
    if plan == "FULL":
        monthly = full_monthly * factor
        months = min(_months_elapsed(closedate, today), full_term_months)
        return {"booked_revenue": monthly * full_term_months,
                "est_cash_collected": monthly * months,
                "monthly": monthly, "counts_as_sale": True}
    if plan == "90DAY":
        amt = ninety_day_amount * factor
        return {"booked_revenue": amt, "est_cash_collected": amt,
                "monthly": 0.0, "counts_as_sale": True}
    if plan == "DIY":
        monthly = diy_monthly * factor
        months = _months_elapsed(closedate, today)
        return {"booked_revenue": 0.0, "est_cash_collected": monthly * months,
                "monthly": monthly, "counts_as_sale": True}
    return {"booked_revenue": 0.0, "est_cash_collected": 0.0,
            "monthly": 0.0, "counts_as_sale": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest dashboard/tests/test_money_engine.py -q`
Expected: PASS (all cases)

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_money_engine.py
git commit -m "feat: add deal_money tier calculator"
```

---

### Task 3: Wire tier money into `build_closed_deals_table`

Replace the `deal.amount` "Option C" logic with `deal_money`. `deal_amount` column becomes tier-derived **booked revenue**; add `est_cash_collected`, `monthly`, and `plan` columns. Keep all group/source/cycle logic untouched.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`build_closed_deals_table`, ~lines 1878-2032)
- Test: `dashboard/tests/test_money_engine.py`

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_money_engine.py`:

```python
import pandas as pd
from dashboard.data.reconcile import build_closed_deals_table

RATE_KW = dict(full_monthly=1997.0, full_term_months=24,
               ninety_day_amount=5991.0, diy_monthly=997.0, pt_multiplier=0.5)


def test_build_closed_deals_table_uses_tier_not_amount():
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 40000.0,
         "createdate": "2026-04-01T00:00:00Z", "closedate": "2026-04-15T00:00:00Z",
         "stage_entry_date": None},
        {"deal_id": "d2", "dealstage": "1163151789", "amount": 40000.0,
         "createdate": "2026-03-01T00:00:00Z", "closedate": None,
         "stage_entry_date": "2026-03-10T00:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "c1", "deal_id": "d1"},
        {"contact_id": "c2", "deal_id": "d2"},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "c1", "name": "Full Doc", "email": "f@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": "1:  PRIMARY",
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-04-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
        {"hs_id": "c2", "name": "DIY Doc", "email": "d@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": "DIY - C",
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-03-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
    ])
    t = build_closed_deals_table(
        deals, contact_deals, contacts,
        asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        today=date(2026, 6, 9), **RATE_KW,
    )
    full = t[t["hs_id"] == "c1"].iloc[0]
    diy = t[t["hs_id"] == "c2"].iloc[0]
    # deal.amount ($40k) ignored; FULL booked = 47928
    assert full["deal_amount"] == 47928.0
    assert full["est_cash_collected"] == 1997.0 * 2
    assert full["plan"] == "FULL"
    # DIY: no booked TCV, cash accrues (Mar->Jun = 3)
    assert diy["deal_amount"] == 0.0
    assert diy["est_cash_collected"] == 997.0 * 3
    assert diy["plan"] == "DIY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_money_engine.py::test_build_closed_deals_table_uses_tier_not_amount -q`
Expected: FAIL with `TypeError` (unexpected keyword `today`) or missing `plan` column.

- [ ] **Step 3: Update the signature**

Change the `build_closed_deals_table` signature (line 1878) to add the rate params and `today`:

```python
def build_closed_deals_table(
    deals: pd.DataFrame,
    contact_deals: pd.DataFrame,
    contacts: pd.DataFrame,
    *,
    asset_to_group: dict[str, str],
    group_default_amount: dict[str, float],
    source_overrides: dict | None = None,
    stage_source_fallback: dict | None = None,
    today=None,
    full_monthly: float = 1997.0,
    full_term_months: int = 24,
    ninety_day_amount: float = 5991.0,
    diy_monthly: float = 997.0,
    pt_multiplier: float = 0.5,
) -> pd.DataFrame:
```

`group_default_amount` stays in the signature (callers still pass it) but is no longer used for money - leave it for now to avoid touching every caller. Add `today` resolution at the top of the body, right after the empty-guard `if deals.empty ...: return`:

```python
    from datetime import date as _date
    if today is None:
        today = _date.today()
```

- [ ] **Step 4: Update the `cols` list**

Change the `cols` list (line 1894-1896) to add the three new columns:

```python
    cols = ["hs_id", "contact_name", "email", "typeform", "group", "asset", "source",
            "tier", "send_contract", "is_marketing", "closedate", "deal_amount",
            "est_cash_collected", "monthly", "plan",
            "sales_cycle_days", "sdr_owner", "bds", "sme"]
```

- [ ] **Step 5: Replace the Option-C money line with deal_money**

Delete line 1941-1942:

```python
        # Option C: deal.amount if > 0, else group default
        effective_amt = amt if amt > 0 else float(group_default_amount.get(group, 0.0))
```

and insert (same location) the tier-derived calc. Note: use the **effective close date** (closedate, else stage_entry_date, else createdate) so DIY/90-Day stages get a valid date:

```python
        # Tier-derived money (deal.amount is a $40k placeholder, ignored).
        _plan, _mgroup = classify_tier(tier_val)
        _eff_close = (deal.get("closedate") or deal.get("stage_entry_date")
                      or deal.get("createdate"))
        _money = deal_money(
            _plan, _mgroup, _eff_close, today,
            full_monthly=full_monthly, full_term_months=full_term_months,
            ninety_day_amount=ninety_day_amount, diy_monthly=diy_monthly,
            pt_multiplier=pt_multiplier,
        )
```

**Important:** `tier_val` is currently computed lower down (line 1997: `tier_val = primary_contact.get("contract_tier") or ""`). Move that single line UP to just before this new block so `classify_tier(tier_val)` has it. (Leave the later group-derivation use of `tier_val` as-is; it will still be defined.)

- [ ] **Step 6: Use the money in the row dict**

In the `rows.append({...})` dict (line 2006-2025), change `"deal_amount": effective_amt,` to and add the new keys:

```python
            "deal_amount": _money["booked_revenue"],
            "est_cash_collected": _money["est_cash_collected"],
            "monthly": _money["monthly"],
            "plan": _plan,
```

- [ ] **Step 7: Run the new test**

Run: `python -m pytest dashboard/tests/test_money_engine.py::test_build_closed_deals_table_uses_tier_not_amount -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_money_engine.py
git commit -m "feat: build_closed_deals_table uses tier-derived money"
```

---

### Task 4: Tier money in `windowed_sales_money` (+ fix its test)

`windowed_sales_money` already calls `build_closed_deals_table`. Switch its revenue to the table's tier-derived `deal_amount` (already changed) and its cash to the new `est_cash_collected` column instead of `group_cash_per_deal`.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`windowed_sales_money`, ~lines 1359-1442)
- Modify: `dashboard/tests/test_sales_rollups.py` (`test_windowed_sales_money_filters_by_closedate`, lines 303-349)

- [ ] **Step 1: Update the failing test to the new model**

In `dashboard/tests/test_sales_rollups.py`, set real tiers on the contacts and update expectations. Replace `contract_tier` values: `c1 -> "1:  PRIMARY"`, `c2 -> "1:  PRIMARY"`, `c3 -> "DIY - C"`. Then pass `today=_d(2026, 5, 31)` and rate kwargs to the call, and replace the assertions (lines 345-349) with:

```python
    # d1 closed 2026-05-10 FULL -> booked 47928; d3 DIY in window -> booked 0
    assert result["window_closed_count"] == 2
    assert result["window_revenue"] == 47928.0 + 0.0
    # Est cash: d1 FULL closed May, today May 31 -> 1mo = 1997;
    #           d3 DIY stage-entered May -> 1mo = 997
    assert result["window_cash_collection"] == 1997.0 + 997.0
```

(Keep `group_default_amount` / `group_cash_per_deal` kwargs in the call - they are now ignored but still accepted.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py::test_windowed_sales_money_filters_by_closedate -q`
Expected: FAIL (old code returns 50000+47928 revenue, group-cash logic).

- [ ] **Step 3: Update `windowed_sales_money`**

Add `today=None` + rate kwargs to its signature (mirror Task 3 Step 3). Pass them through to its `build_closed_deals_table(...)` call (currently ~line 1416). Then change the money aggregation block (lines 1423-1434):

```python
    n = int(len(table))
    revenue = float(table["deal_amount"].sum()) if n else 0.0
    avg = (revenue / n) if n else None
    cycle_vals = table["sales_cycle_days"].dropna().tolist() if n else []
    cycle_median = float(pd.Series(cycle_vals).median()) if cycle_vals else None
    cash = float(table["est_cash_collected"].sum()) if n else 0.0
```

Leave the `group_cash_per_deal` param in the signature (ignored). Keep the return dict keys identical (`window_cash_collection` = `cash`).

- [ ] **Step 4: Run it to confirm it passes**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py::test_windowed_sales_money_filters_by_closedate -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_sales_rollups.py
git commit -m "feat: windowed_sales_money uses tier-derived revenue + est cash"
```

---

### Task 5: Tier money in `compute_ytd_money` (+ fix its tests)

`compute_ytd_money` calls `build_closed_deals_table`, so revenue auto-switches to booked. Add an `est_cash_collected` total and pass `today`/rates through.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`compute_ytd_money`, lines 2035-2082)
- Modify: `dashboard/tests/test_reconcile.py` (tests asserting `new_revenue == 47928` from `amount`)

- [ ] **Step 1: Update failing tests to set tiers**

In `dashboard/tests/test_reconcile.py`, every `compute_ytd_money` test contact that should produce $47,928 revenue must have `contract_tier="1:  PRIMARY"` (search the test bodies; the deals carry `amount: 47928` today but amount is now ignored). For `test_executive_kpis_revenue_fallback_option_c` (lines 553-586): this test asserts the Option-C fallback; since amount is no longer used, repurpose it - rename to `test_compute_ytd_money_tier_revenue`, set the contact `contract_tier="1:  PRIMARY"`, and assert `new_revenue == 47928.0`. Add a cash assertion only if the test calls `compute_ytd_money` directly.

NOTE for executor: `executive_kpis` tests (lines 481-510, 536-550) assert `new_revenue`/`avg_deal_size` from `executive_kpis`, which is OUT OF SCOPE (Task list header). Do NOT change `executive_kpis` here. If those two tests fail because they share `group_default`, leave `executive_kpis` untouched and only adjust the assertion if the value genuinely changed; `executive_kpis` still uses `deal.amount`, so `amount: 47928` keeps `new_revenue == 47928` - they should still pass. Verify, don't pre-edit.

- [ ] **Step 2: Update `compute_ytd_money`**

Add `today=None` + rate kwargs to the signature, pass through to `build_closed_deals_table`. Add cash to `_kpis`:

```python
    def _kpis(df: pd.DataFrame) -> dict:
        n = int(len(df))
        revenue = float(df["deal_amount"].sum()) if not df.empty else 0.0
        cash = float(df["est_cash_collected"].sum()) if not df.empty else 0.0
        avg = (revenue / n) if n else None
        cycle_vals = df["sales_cycle_days"].dropna().tolist()
        cycle_median = float(pd.Series(cycle_vals).median()) if cycle_vals else None
        return {
            "new_revenue": revenue,
            "est_cash_collected": cash,
            "avg_deal_size": avg,
            "new_customers": n,
            "sales_cycle_median": cycle_median,
        }
```

Add `total_est_cash_collected` and `mkt_est_cash_collected` to the returned dict (mirror the existing `total_*`/`mkt_*` keys).

- [ ] **Step 3: Run the reconcile suite**

Run: `python -m pytest dashboard/tests/test_reconcile.py -q`
Expected: PASS (after Step 1 fixture updates)

- [ ] **Step 4: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat: compute_ytd_money tier revenue + est cash total"
```

---

### Task 6: Tier money in `sales_sme_rollup` revenue (+ fix its tests)

`sales_sme_rollup` computes `revenue` per contact from `deal.amount`/`group_default` via the inner `_deal_revenue`. Switch it to tier-derived booked revenue using each won contact's `contract_tier`.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`sales_sme_rollup`, ~lines 1180-1356; the revenue block is ~1244-1272)
- Modify: `dashboard/tests/test_reconcile.py` (lines ~633-730: `scott["revenue"]`, `eric["revenue"]` asserts)

- [ ] **Step 1: Update failing tests to set tiers**

In the SME rollup tests (the ones asserting `revenue == 47928.0` and `revenue_per_call == 47928/2`), add `contract_tier="1:  PRIMARY"` to the relevant contact rows so the tier-derived booked revenue is $47,928. The deals already have `closedate`; pass `today=date(2026, 6, 9)` to the `sales_sme_rollup` call (add the param in Step 2).

- [ ] **Step 2: Update the signature + revenue block**

Add to `sales_sme_rollup` signature: `today=None` and the five rate kwargs (defaults as in Task 3). Replace the `_deal_revenue` inner function + revenue map (lines ~1244-1272) with a tier-based map. The new block:

```python
    # Revenue per contact = tier-derived booked revenue of their won deal(s).
    # deal.amount is a $40k placeholder and is NOT used.
    from datetime import date as _date
    if today is None:
        today = _date.today()
    tier_by_contact = dict(zip(contacts["hs_id"].astype(str),
                               contacts.get("contract_tier", pd.Series(dtype=object))))
    contact_revenue: dict[str, float] = {}
    if not deals.empty and not contact_deals.empty and won_set:
        won_deal_ids = set(deals.loc[deals["dealstage"].isin(won_set), "deal_id"])
        # earliest close per won deal for the cash/booked date
        won_close = dict(zip(
            deals["deal_id"],
            deals.get("closedate").fillna(deals.get("createdate"))
            if "closedate" in deals.columns else deals.get("createdate"),
        ))
        for _, cd_row in contact_deals.iterrows():
            cid = str(cd_row["contact_id"])
            did = cd_row["deal_id"]
            if did not in won_deal_ids:
                continue
            plan, mgroup = classify_tier(tier_by_contact.get(cid))
            money = deal_money(
                plan, mgroup, won_close.get(did), today,
                full_monthly=full_monthly, full_term_months=full_term_months,
                ninety_day_amount=ninety_day_amount, diy_monthly=diy_monthly,
                pt_multiplier=pt_multiplier,
            )
            contact_revenue[cid] = contact_revenue.get(cid, 0.0) + money["booked_revenue"]
```

(Keep `group_default_amount`/`asset_to_group` params for signature compatibility; they're unused for revenue now. The `contacts["group"]` derivation earlier in the function stays.)

- [ ] **Step 3: Run reconcile suite**

Run: `python -m pytest dashboard/tests/test_reconcile.py dashboard/tests/test_sales_rollups.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat: sales_sme_rollup revenue uses tier-derived booked value"
```

---

### Task 7: Wire call sites + full green + commit

The Sales tab callers in `sections/sales.py` call `windowed_sales_money`, `build_closed_deals_table`, and `sales_sme_rollup`. They must pass `today=date.today()` (and may pass `cfg.FULL_MONTHLY` etc., but defaults match, so `today` is the only required add).

**Files:**
- Modify: `dashboard/sections/sales.py` (the three call sites)
- Modify: `dashboard/sections/executive.py` (if it calls `compute_ytd_money` / `build_closed_deals_table`, pass `today`)

- [ ] **Step 1: Find the call sites**

Run: `grep -n "windowed_sales_money\|build_closed_deals_table\|sales_sme_rollup\|compute_ytd_money" dashboard/sections/sales.py dashboard/sections/executive.py`

- [ ] **Step 2: Add `today` to each call**

At the top of each caller that doesn't already have it, ensure `from datetime import date` is imported, then add `today=date.today(),` to each of the four function calls. Defaults cover the rate kwargs, so no other change is needed.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest dashboard/tests -q`
Expected: PASS (all, including the 50 prior + new money-engine tests)

- [ ] **Step 4: Smoke-test the money numbers**

Create a throwaway probe (delete after) that loads YTD closed deals and prints `build_closed_deals_table(...)` `deal_amount` + `est_cash_collected` totals; confirm revenue is no longer ~$2.29M (57 x $40k) and that DIY rows show $0 booked. Delete the probe.

- [ ] **Step 5: Commit + push**

```bash
git add dashboard/sections/sales.py dashboard/sections/executive.py
git commit -m "feat: pass today to tier-money call sites"
git push origin feature/cmo-dashboard
```

---

## Self-Review notes

- Spec coverage: this plan implements the **Money model** section of the spec (tier map, booked vs est cash, PT halving, DIY no-TCV, Basic excluded). Upsell detection, the roster, team-total rows, Asset Performance, and Upcoming Calls are Plans 2-3.
- `group_default_amount` / `group_cash_per_deal` params are intentionally retained-but-unused to avoid editing every caller in one plan; a later cleanup can drop them.
- Cross-tab: `compute_ytd_money` + `build_closed_deals_table` are shared, so Executive "Money YTD" and Metrics money become tier-correct automatically. `executive_kpis`' own `new_revenue` is a separate, deferred follow-up.
