# Sales Tab Redesign - Plan 3: New Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the per-lead Marketing Lead Detail table with an **Asset Performance** summary, add an **Upcoming Calls** section, and add a **DIY / 90-Day / Basic roster** dropdown.

**Architecture:** One new pure, tested rollup in `reconcile.py` (`asset_performance_rollup`). Render-layer additions in `sections/sales.py`. Upcoming Calls is derived from the already-loaded `meetings_full` frame (the meetings loader has no upper time bound, so future-dated calls are already present) filtered to `start_time > now`. The roster reuses the Closed Deals YTD table (it already carries `tier` + `deal_amount`). Money stays on the reverted `deal.amount` Option-C logic.

**Tech Stack:** Python 3, pandas, pytest, Streamlit (Styler row-styling via `.apply(axis=1)`; `_fmt_*` helpers are blank-safe after Plan 2).

**Spec:** `docs/superpowers/specs/2026-06-09-sales-tab-redesign-design.md` (sections 5-7).

---

### Task 1: `asset_performance_rollup` (pure, tested)

**Files:**
- Modify: `dashboard/data/reconcile.py` (add near `sales_sme_rollup`)
- Test: `dashboard/tests/test_sales_rollups.py`

- [ ] **Step 1: Write the failing test**

```python
def test_asset_performance_rollup():
    from dashboard.data.reconcile import asset_performance_rollup
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Top 10 typeform"},
        {"hs_id": "2", "typeform_asset_download": "Top 10 typeform"},
        {"hs_id": "3", "typeform_asset_download": "EMX Kansas City 2026"},
        {"hs_id": "4", "typeform_asset_download": ""},   # blank -> excluded
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE", "start_time": "2026-05-01T00:00:00Z"},
        {"meeting_id": "m2", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "SCHEDULED", "start_time": "2026-05-03T00:00:00Z"},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "1", "deal_id": "d1"}])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 50000.0},
    ])
    r = asset_performance_rollup(
        contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        asset_to_group={"Top 10 typeform": "Chiro",
                        "EMX Kansas City 2026": "EMX"},
        group_default_amount={"Chiro": 47928.0},
        stages_closed_won={"closedwon"},
    )
    # blank-asset contact 4 excluded -> 2 asset rows; sorted by revenue desc
    assert list(r["asset"]) == ["Top 10 typeform", "EMX Kansas City 2026"]
    top = r.iloc[0]
    assert top["leads"] == 2
    assert top["fifteen_booked"] == 1
    assert top["strategy_booked"] == 1
    assert top["closed"] == 1
    assert top["revenue"] == 50000.0          # deal.amount used (Option C)
    assert top["close_rate"] == 0.5           # 1 closed / 2 leads
    emx = r.iloc[1]
    assert emx["leads"] == 1 and emx["closed"] == 0 and emx["revenue"] == 0.0
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py::test_asset_performance_rollup -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement** (add to `reconcile.py`, reuses existing `_contacts_with_deal_in_stages` and `_safe_div`)

```python
def asset_performance_rollup(
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    contact_deals: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    asset_to_group: dict,
    group_default_amount: dict,
    stages_closed_won,
) -> pd.DataFrame:
    """Per marketing-asset performance summary.

    One row per typeform_asset_download (blank assets excluded).
    Columns: asset, group, leads, fifteen_booked, strategy_booked, closed,
             revenue, close_rate (closed / leads).
    Revenue uses Option-C: deal.amount when > 0, else group_default per group.
    Sorted by revenue, then closed, then leads (descending).
    """
    cols = ["asset", "group", "leads", "fifteen_booked", "strategy_booked",
            "closed", "revenue", "close_rate"]
    if contacts.empty:
        return pd.DataFrame(columns=cols)
    c = contacts.copy()
    c["asset"] = c["typeform_asset_download"].fillna("").astype(str).str.strip()
    c = c[c["asset"] != ""]
    if c.empty:
        return pd.DataFrame(columns=cols)

    if not meetings.empty:
        types = meetings["activity_type"].fillna("").astype(str).str.lower()
        booked_15 = set(meetings.loc[types.str.contains("15 min", na=False),
                                     "contact_id"].astype(str))
        booked_strat = set(meetings.loc[types.str.contains("strategy", na=False),
                                        "contact_id"].astype(str))
    else:
        booked_15, booked_strat = set(), set()

    won_set = set(stages_closed_won)
    won_contact_ids = _contacts_with_deal_in_stages(contact_deals, deals, won_set)

    contact_revenue: dict[str, float] = {}
    if not deals.empty and not contact_deals.empty and won_set:
        c_group = dict(zip(c["hs_id"].astype(str), c["asset"].map(asset_to_group)))
        won_deals = deals[deals["dealstage"].isin(won_set)].copy()

        def _rev(row) -> float:
            amt = float(row.get("amount") or 0)
            if amt > 0:
                return amt
            cids = contact_deals[
                contact_deals["deal_id"] == row["deal_id"]
            ]["contact_id"].astype(str)
            for cid in cids:
                g = c_group.get(cid)
                if g and g in group_default_amount:
                    return float(group_default_amount[g])
            return 0.0

        won_deals["_rev"] = won_deals.apply(_rev, axis=1)
        rev_map = dict(zip(won_deals["deal_id"], won_deals["_rev"]))
        for _, row in contact_deals.iterrows():
            did = row["deal_id"]
            cid = str(row["contact_id"])
            if did in rev_map:
                contact_revenue[cid] = contact_revenue.get(cid, 0.0) + rev_map[did]

    rows = []
    for asset, grp in c.groupby("asset"):
        ids = set(grp["hs_id"].astype(str))
        leads = len(ids)
        closed = len(ids & won_contact_ids)
        rows.append({
            "asset": asset,
            "group": asset_to_group.get(asset, ""),
            "leads": leads,
            "fifteen_booked": len(ids & booked_15),
            "strategy_booked": len(ids & booked_strat),
            "closed": closed,
            "revenue": sum(contact_revenue.get(i, 0.0) for i in ids),
            "close_rate": _safe_div(closed, leads),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        ["revenue", "closed", "leads"], ascending=False
    ).reset_index(drop=True)
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `python -m pytest dashboard/tests/test_sales_rollups.py -q`

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_sales_rollups.py
git commit -m "feat: add asset_performance_rollup"
```

---

### Task 2: Render Asset Performance (replace Marketing Lead Detail)

**Files:**
- Modify: `dashboard/sections/sales.py`

- [ ] **Step 1: Locate the block**

Run: `grep -n "Marketing Lead Detail\|asset_performance_rollup\|deals_for_sme" dashboard/sections/sales.py`
Read the full "Marketing Lead Detail" section. Note the windowed inputs in scope: `marketing` (window leads), `meetings` (windowed), `contact_deals`, and the closedate-windowed deals frame used for the SME rollup (look for `deals_for_sme`; if present, reuse it - it is the deals filtered to closedate-in-window. If it is named differently, use whatever the SME rollup call passes as `deals`).

- [ ] **Step 2: Replace the section body**

Remove the per-lead `detail` table (the `mkt_detail` / `latest_deal` / `detail` dataframe construction and its `st.dataframe`). Replace with an Asset Performance table. Add `asset_performance_rollup` to the reconcile import block. New code:

```python
    # ----- Section: Asset Performance (replaces Marketing Lead Detail) -----
    st.subheader("Asset Performance")
    st.caption(
        f"{_win_label}. One row per marketing asset (typeform). Leads = "
        "contacts who opted in via that asset this window; closed/revenue = "
        "their won deals (deal.amount, group default as fallback). "
        "Close % = closed / leads. Sorted by revenue."
    )
    asset_perf = asset_performance_rollup(
        contacts=marketing, meetings=meetings,
        contact_deals=contact_deals, deals=deals_for_sme,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
    )
    if asset_perf.empty:
        st.info("No asset-attributed leads in this window.")
    else:
        ap = asset_perf.copy()
        ap["close_rate"] = ap["close_rate"].map(_fmt_pct)
        ap["revenue"] = ap["revenue"].map(_fmt_money)
        ap = ap.rename(columns={
            "asset": "Asset", "group": "Group", "leads": "Leads",
            "fifteen_booked": "15-min Booked", "strategy_booked": "Strategy Booked",
            "closed": "Closed", "revenue": "Revenue", "close_rate": "Close %",
        })
        st.dataframe(ap, use_container_width=True, hide_index=True)
```

If the SME-rollup deals variable is NOT named `deals_for_sme`, define a local closedate-windowed frame the same way the SME section does, or reuse `deals` if no such filter exists. Prefer the in-window-closed frame for consistency with SME Performance.

- [ ] **Step 3: Compile + run suite**

Run: `python -m py_compile dashboard/sections/sales.py && python -m pytest dashboard/tests -q`

- [ ] **Step 4: Commit**

```bash
git add dashboard/sections/sales.py
git commit -m "feat: Asset Performance section replaces Marketing Lead Detail"
```

---

### Task 3: Render Upcoming Calls

**Files:**
- Modify: `dashboard/sections/sales.py`

Upcoming calls come from `meetings_full` (already loaded; includes future-dated meetings) filtered to `start_time > now`, joined to `marketing` for contact name + the relevant owner (BDS for 15-min, SME for Strategy). Flag any call more than 14 days out in red.

- [ ] **Step 1: Add the section** (place after Asset Performance, before Closed Deals YTD)

```python
    st.divider()
    st.subheader("Upcoming Calls")
    st.caption(
        "Scheduled 15-min and Strategy calls with a start time in the future. "
        "Reps should not book more than 14 days out - calls beyond that are "
        "flagged in red."
    )
    _now = pd.Timestamp.now(tz="UTC")
    if meetings_full.empty:
        st.info("No upcoming calls.")
    else:
        mf = meetings_full.copy()
        mf["_start"] = pd.to_datetime(mf["start_time"], utc=True, errors="coerce")
        upcoming = mf[mf["_start"] > _now].copy()
        if upcoming.empty:
            st.info("No upcoming calls.")
        else:
            name_map = dict(zip(marketing["hs_id"].astype(str),
                                marketing.get("name", pd.Series(dtype=object))))
            bds_map = dict(zip(marketing["hs_id"].astype(str),
                               marketing.get("bds", pd.Series(dtype=object))))
            sme_map = dict(zip(marketing["hs_id"].astype(str),
                               marketing.get("sme", pd.Series(dtype=object))))
            upcoming["_cid"] = upcoming["contact_id"].astype(str)
            upcoming["Contact"] = upcoming["_cid"].map(name_map).fillna("")
            _atype = upcoming["activity_type"].fillna("").astype(str).str.lower()
            upcoming["Type"] = upcoming["activity_type"].fillna("")
            upcoming["Owner"] = [
                cfg.resolve_owner(sme_map.get(c) if "strategy" in t else bds_map.get(c))
                for c, t in zip(upcoming["_cid"], _atype)
            ]
            upcoming["_days_out"] = (upcoming["_start"] - _now).dt.days
            upcoming = upcoming.sort_values("_start").reset_index(drop=True)
            upcoming["When (CT)"] = cfg.format_ct_series(upcoming["start_time"])
            disp = upcoming[["Contact", "Owner", "Type", "When (CT)", "_days_out"]]

            def _flag_far(row):
                far = row["_days_out"] > 14
                return ["color: #d62728; font-weight: bold" if far else "" for _ in row]

            st.dataframe(
                disp.drop(columns=["_days_out"]).style.apply(
                    lambda r: _flag_far(upcoming.loc[r.name]), axis=1
                ),
                use_container_width=True, hide_index=True,
            )
```

Note: confirm `cfg.format_ct_series` exists (used elsewhere in this file) and `cfg.resolve_owner` handles `None`. If the styler-by-position pattern is awkward, instead keep `_days_out` in `disp`, style on it, then it is acceptable to show the column - but prefer hiding it. Verify the styler renders (compile + a quick HTML render check).

- [ ] **Step 2: Compile + suite**

Run: `python -m py_compile dashboard/sections/sales.py && python -m pytest dashboard/tests -q`

- [ ] **Step 3: Commit**

```bash
git add dashboard/sections/sales.py
git commit -m "feat: Upcoming Calls section (flag >14 days out)"
```

---

### Task 4: Render DIY / 90-Day / Basic roster

**Files:**
- Modify: `dashboard/sections/sales.py`

Reuse the Closed Deals YTD table the render already builds (search for `build_closed_deals_table(` using `deals_ytd`). It has columns incl. `tier`, `contact_name`, `deal_amount`, `closedate`. Filter to tiers indicating DIY / 90-Day / Basic and show in an expander.

- [ ] **Step 1: Add the expander** (near the Closed Deals YTD section; build the table once and reuse, or rebuild if simpler)

```python
    with st.expander("DIY / 90-Day / Basic Roster", expanded=False):
        st.caption(
            "Doctors on a DIY, 90-Day, or Basic plan (by contract_tier), with "
            "their HubSpot deal value and close date. These are not on the full "
            "program."
        )
        if deals_table.empty:
            st.info("No closed deals YTD.")
        else:
            _t = deals_table.copy()
            _tier_u = _t["tier"].fillna("").astype(str).str.upper()
            mask = (_tier_u.str.contains("DIY") | _tier_u.str.contains("90")
                    | _tier_u.str.contains("BASIC"))
            roster = _t[mask].copy()
            if roster.empty:
                st.info("No DIY / 90-Day / Basic doctors YTD.")
            else:
                roster["Deal $"] = roster["deal_amount"].map(
                    lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—")
                roster["Closed"] = cfg.format_ct_series(
                    roster["closedate"], fmt=cfg.DEFAULT_DATE_FORMAT)
                roster = roster[["contact_name", "tier", "Deal $", "Closed"]].rename(
                    columns={"contact_name": "Doctor", "tier": "Tier"})
                st.dataframe(roster, use_container_width=True, hide_index=True)
```

Note: `deals_table` is the variable name the Closed Deals YTD section assigns from `build_closed_deals_table(...)`. Confirm the name by grep; if it is built inside an `if`/`else`, build a roster-scoped table or hoist it. Place the expander where `deals_table` is in scope.

- [ ] **Step 2: Compile + suite**

Run: `python -m py_compile dashboard/sections/sales.py && python -m pytest dashboard/tests -q`

- [ ] **Step 3: Commit**

```bash
git add dashboard/sections/sales.py
git commit -m "feat: DIY/90-Day/Basic roster expander"
```

---

### Task 5: Verify + push

- [ ] **Step 1: Full suite** — `python -m pytest dashboard/tests -q` (expect 53 prior + 1 new = 54).
- [ ] **Step 2: Smoke check** — quick probe (delete after) that calls `asset_performance_rollup` on live MTD/YTD data and prints the top assets, to confirm no crash and sane output.
- [ ] **Step 3: Push** — `git push origin feature/cmo-dashboard`.

---

## Self-Review notes

- Only `asset_performance_rollup` is a pure unit test; the 3 render sections are display, verified by compile + manual render.
- Asset Performance and Upcoming Calls are window-bound via the already-loaded frames; the roster is YTD (reuses the YTD closed-deals table). Captions state the scope.
- Upcoming Calls only covers contacts in the loaded `meetings_full` set (marketing-window + deal-expanded contacts). A booked future call almost always stamped a recent conversion, so coverage is good but not total - acceptable for v1; a dedicated future-meetings loader can broaden it later.
- Money is Option-C (`deal.amount` / group default), consistent with the revert. No tier engine.
