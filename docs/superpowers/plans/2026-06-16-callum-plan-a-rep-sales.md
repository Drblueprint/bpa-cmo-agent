# Callum Plan A — Rep Sales Attribution + Total Sales/Revenue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** Show Total Sales + Total Revenue (not First/FU close) per SME, add "Sales Influenced" per SDR and per BDS, and rename Discovery "Held" → "Show" — all sourced from the closed-deals table so closes attribute correctly (fixes SME showing 0 sales).

**Architecture:** One pure tested helper `rep_sales_rollup(closed_deals_table, by)` groups window-closed deals by a rep field (`sme`/`sdr_owner`/`bds`) → sales count + revenue. Wire it into the Sales-tab SME/SDR/BDS sections. Revenue = HubSpot `deal.amount` (decision D1 — no tier engine).

**Spec:** docs/superpowers/specs/2026-06-16-callum-sales-reporting-review.md (decisions LOCKED).

---

### Task 1: `rep_sales_rollup` helper

**Files:** Modify `dashboard/data/reconcile.py`; Test `dashboard/tests/test_sales_rollups.py`.

- [ ] **Step 1: failing test**
```python
def test_rep_sales_rollup():
    from dashboard.data.reconcile import rep_sales_rollup
    # closed-deals-table shape (build_closed_deals_table output subset)
    cdt = pd.DataFrame([
        {"hs_id": "1", "sme": "S1", "bds": "B1", "sdr_owner": "D1", "deal_amount": 47928.0},
        {"hs_id": "2", "sme": "S1", "bds": "B2", "sdr_owner": "D1", "deal_amount": 5991.0},
        {"hs_id": "3", "sme": "S2", "bds": "B1", "sdr_owner": "",   "deal_amount": 40000.0},
    ])
    by_sme = rep_sales_rollup(cdt, by="sme")
    r = {x["rep_id"]: x for _, x in by_sme.iterrows()}
    assert r["S1"]["sales"] == 2 and r["S1"]["revenue"] == 47928.0 + 5991.0
    assert r["S2"]["sales"] == 1 and r["S2"]["revenue"] == 40000.0
    by_sdr = rep_sales_rollup(cdt, by="sdr_owner")
    rs = {x["rep_id"]: x for _, x in by_sdr.iterrows()}
    assert rs["D1"]["sales"] == 2
    # blank rep id is dropped (no "" row)
    assert "" not in rs
    # empty table -> empty frame with the right columns
    empty = rep_sales_rollup(pd.DataFrame(columns=["sme", "deal_amount"]), by="sme")
    assert list(empty.columns) == ["rep_id", "sales", "revenue"] and empty.empty
```

- [ ] **Step 2: run, confirm fail** — `python -m pytest dashboard/tests/test_sales_rollups.py::test_rep_sales_rollup -q` → ImportError.

- [ ] **Step 3: implement** (add near the other sales rollups in reconcile.py)
```python
def rep_sales_rollup(closed_deals_table: pd.DataFrame, *, by: str) -> pd.DataFrame:
    """Sales count + revenue per rep, from the closed-deals table.

    `by` is the rep column to group on: "sme" (the closer), "sdr_owner"
    (the lead's SDR — 'sales influenced'), or "bds". Revenue = sum of
    deal_amount (HubSpot deal.amount). Blank/NaN rep ids are dropped.
    Columns: rep_id, sales, revenue. Sorted by sales desc.
    """
    cols = ["rep_id", "sales", "revenue"]
    if closed_deals_table is None or closed_deals_table.empty or by not in closed_deals_table.columns:
        return pd.DataFrame(columns=cols)
    t = closed_deals_table.copy()
    t["_rep"] = t[by].fillna("").astype(str).str.strip()
    t = t[t["_rep"] != ""]
    if t.empty:
        return pd.DataFrame(columns=cols)
    t["_amt"] = pd.to_numeric(t["deal_amount"], errors="coerce").fillna(0.0)
    g = t.groupby("_rep")
    out = pd.DataFrame({
        "rep_id": list(g.groups.keys()),
        "sales": g.size().values,
        "revenue": g["_amt"].sum().values,
    })
    return out.sort_values("sales", ascending=False).reset_index(drop=True)
```

- [ ] **Step 4: run, confirm pass.**
- [ ] **Step 5: commit** — `feat: add rep_sales_rollup (sales+revenue by rep)`.

---

### Task 2: SME Performance → Total Sales + Total Revenue (drop First/FU)

**Files:** Modify `dashboard/sections/sales.py` (SME section ~lines 1020-1110).

- [ ] **Step 1: build a window closed-deals table.** Near the SME section (after `deals_for_sme`), build a per-deal closed table for the window from the YTD-closed pull already loaded (`deals_ytd`, `contact_deals_ytd`, `contacts_ytd`). Filter `deals_ytd` to closedate/stage-entry/createdate in `[start, end]` (reuse the existing `_m_close | _m_stage | _m_create` logic against `deals_ytd`), then:
```python
        _win_closed = build_closed_deals_table(
            deals_ytd[_ytd_win_mask], contact_deals_ytd, contacts_ytd,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
            stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        ) if not deals_ytd.empty else pd.DataFrame(
            columns=["hs_id","sme","bds","sdr_owner","deal_amount"])
```
(Compute `_ytd_win_mask` with the same close/stage/create logic used for `deals_for_sme`, but against `deals_ytd`.)

- [ ] **Step 2: SME table — keep the meeting funnel (Appointments/Showed from `sales_sme_rollup`), replace the deal columns.** Drop `deals_closed`, `first_closes`, `fu_closes`, `first_close_rate`, `fu_close_rate`, and the old `revenue` from the displayed SME table. Instead join `rep_sales_rollup(_win_closed, by="sme")` on the SME id to add **Sales** (count) and **Revenue** (sum deal_amount). Keep `appointments`, `showed`, `show_rate`, `disqualified`, `dq_rate`. Add a **Close %** = Sales / Showed (recomputed in the team-total too). Map sme_id → name, drop `(unassigned)`, keep the bold TEAM TOTAL row (sum Sales + Revenue; Close% from totals).

- [ ] **Step 3: update the SME caption** — remove the First/FU Close sentences; state "Sales = closed-won deals (deal.amount) whose closedate is in window, by the SME on the deal. Revenue = sum of deal.amount. Close % = Sales / Showed."

- [ ] **Step 4: compile + suite** — `python -m py_compile dashboard/sections/sales.py && python -m pytest dashboard/tests -q`.
- [ ] **Step 5: commit** — `feat: SME Performance shows Total Sales + Revenue (drop first/FU)`.

---

### Task 3: SDR + BDS "Sales Influenced" + Discovery "Show" rename

**Files:** Modify `dashboard/sections/sales.py` (SDR ~694-820, BDS ~860-915) and `dashboard/sections/executive.py` (BDS panel labels).

- [ ] **Step 1: SDR Performance — add "Sales Influenced".** After the SDR rollup display is built, join `rep_sales_rollup(_win_closed, by="sdr_owner")` keyed on the SDR's HubSpot owner id to add a **Sales Influenced** column (closes whose contact's sdr_owner = this SDR). Include it in the TEAM TOTAL sum. Note: the SDR rollup keys on AirCall user → `aircall_to_sdr_owner` HubSpot id; map rep_sales_rollup's `rep_id` (sdr_owner id) to the same SDR rows. If a clean join isn't possible, attribute by resolving both to owner name via `cfg.resolve_owner` and joining on name.

- [ ] **Step 2: BDS Performance — add "Sales Influenced"** = `rep_sales_rollup(_win_closed, by="bds")` joined on bds id. Include in TEAM TOTAL.

- [ ] **Step 3: rename Discovery "Held" → "Show".** Sales BDS table: `Disco Held` → `Discovery Show`, `Held %` → `Show %` (rename the display columns only; underlying keys unchanged). Executive BDS panel: `Discovery Held` → `Discovery Show` (the column rename dict). Update captions that say "held" for the discovery show metric.

- [ ] **Step 4: compile + suite.**
- [ ] **Step 5: commit** — `feat: SDR/BDS Sales Influenced + Discovery Show rename`.

---

### Task 4: verify + push
- [ ] Full suite green (`python -m pytest dashboard/tests -q`).
- [ ] Smoke probe (delete after): build `_win_closed` for MTD, print rep_sales_rollup by sme / sdr_owner / bds — confirm sales attribute to reps and totals match the Executive closed-deals count.
- [ ] `git push origin feature/cmo-dashboard`.

## Self-Review notes
- `rep_sales_rollup` is the one pure/tested unit; the rest is render wiring verified by compile + smoke probe.
- Revenue is deal.amount (D1) — Sales count is reliable immediately; revenue fills in as the team enters amounts.
- SME sales now come from the closed-deals table (closer = deal's `sme`), not the marketing-lead-set intersection — fixes the "0 sales" bug and matches the Executive closed-deals figures.
- "Sales influenced" double-counts across reps by design (one deal credits its SDR, its BDS, and its SME) — that's the intent (influence, not exclusive attribution); note it in captions.
