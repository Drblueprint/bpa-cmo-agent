# MAP Group Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MAP ("Movement Activation Protocol" FB offer) a first-class, standalone marketing group across the EXECUTIVE tab, METRICS tab, Daily VA Summary, and Weekly Metrics scorecard.

**Architecture:** MAP is already grouped at the data layer (FB `match_group` tags `MAP Protocol` campaigns; asset `"Movement Activation Protocol "` maps to "MAP"). This plan propagates MAP into the display/report layer, which currently hardcodes the group set. Pure reconcile functions gain MAP outputs; the Streamlit sections render them.

**Tech Stack:** Python, pandas, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-map-group-reporting-design.md`

## Global Constraints

- MAP is **standalone**: its lead counts NEVER fold into Chiro's lead/opt-in rows. Only its **spend/clicks/CPC** roll into the combined `chiro_ad_spend` / `chiro_link_clicks` / `chiro_cpc` weekly aggregates (matching how TheraRay/NLAP/Workshop already behave there).
- MAP weekly goals default to `0`.
- No em dashes or AI-style punctuation in any user-facing string. Use standard hyphens.
- `_METRIC_LABELS` (reconcile.py) and `config.METRICS_GOALS` keys MUST stay identical sets — `test_scorecard_labels_present_and_clean` asserts `set(_METRIC_LABELS) == set(METRICS_GOALS)`. Every new label key needs a matching goal key.
- Write files with Write/Edit only. Run tests via the Bash tool from the repo root `C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent`.
- Branch: `feature/cmo-dashboard`. Commit after each task; do not push (Kurt pushes).
- The MAP group label string is exactly `"MAP"`. The MAP typeform asset is exactly `"Movement Activation Protocol "` (trailing space).

---

### Task 1: Weekly scorecard — MAP rows + combined spend/clicks/CPC rollin

**Files:**
- Modify: `dashboard/data/reconcile.py` (`_METRIC_LABELS` ~2049; `weekly_metrics` metric loop ~2512-2621)
- Modify: `dashboard/config.py` (`METRICS_GOALS` ~499)
- Test: `dashboard/tests/test_weekly_scorecard.py`

**Interfaces:**
- Consumes (existing inner helpers of `weekly_metrics`): `_fb_sum(group, field, ws, we)`, `_fb_clicks(group, ws, we)`, `_contacts_in_group_with_submit(group, ws, we)`.
- Produces: two new weekly rows keyed `map_ad_spend` and `map_leads`; the combined `chiro_ad_spend`/`chiro_link_clicks`/`chiro_cpc` rows now include MAP.

- [ ] **Step 1: Add `"MP": "MAP"` to the shared test helper's asset map**

In `dashboard/tests/test_weekly_scorecard.py`, the `_run` helper's `asset_to_group` dict (currently `{"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro", "EM": "EMX", "PGW": "Practice Growth Workshop"}`) gains one entry:

```python
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro", "EM": "EMX",
                        "PGW": "Practice Growth Workshop", "MP": "MAP"},
```

- [ ] **Step 2: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
def test_map_weekly_rows_and_combined_rollin():
    fb = pd.DataFrame([
        {"group": "MAP", "spend": 300.0, "inline_link_clicks": 20,
         "fb_leads": 0, "date_start": "2026-06-09"},
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 10,
         "fb_leads": 0, "date_start": "2026-06-09"},
    ])
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "MP",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-06-09T09:00:00Z", "email": "a@x.com"},
    ])
    r = _run(contacts, fb=fb)
    # Standalone MAP rows
    assert r.loc["map_ad_spend", "w0"] == 300.0
    assert r.loc["map_leads", "w0"] == 1
    # MAP rolls into the combined spend/clicks/cpc
    assert r.loc["chiro_ad_spend", "w0"] == 400.0          # Chiro 100 + MAP 300
    assert r.loc["chiro_link_clicks", "w0"] == 30          # 10 + 20
    assert abs(r.loc["chiro_cpc", "w0"] - (400.0 / 30)) < 1e-9
    # MAP leads stay standalone: NOT rolled into Chiro lead rows
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 0
    assert r.loc["chiro_new_leads", "w0"] == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_weekly_scorecard.py::test_map_weekly_rows_and_combined_rollin -v`
Expected: FAIL — `KeyError: 'map_ad_spend'` (row not in index).

- [ ] **Step 4: Add the two label keys to `_METRIC_LABELS`**

In `dashboard/data/reconcile.py`, immediately after the `"pgw_leads": ...` entry (~line 2068), add:

```python
    "map_ad_spend": "MAP - Ad Spend",
    "map_leads": "MAP - Leads",
```

- [ ] **Step 5: Add matching goal keys to `config.METRICS_GOALS`**

In `dashboard/config.py`, immediately after `"pgw_leads": 0,` (~line 516), add:

```python
    "map_ad_spend": 0,
    "map_leads": 0,
```

- [ ] **Step 6: Update the three combined labels to add "+ MAP"**

In `dashboard/data/reconcile.py` `_METRIC_LABELS`, change these three values:

```python
    "chiro_ad_spend": "Chiro - Ad Spend (incl. EMX + DTI + Workshop + MAP)",
    "chiro_link_clicks": "Chiro - Link Clicks (incl. EMX + DTI + Workshop + MAP)",
    "chiro_cpc": "Chiro - Cost-Per-Click (incl. EMX + DTI + Workshop + MAP)",
```

- [ ] **Step 7: Include MAP in the combined spend / clicks / cpc branches**

In `weekly_metrics`, add a `+ _fb_sum("MAP", "spend", ws, we)` term to the `chiro_ad_spend` branch, a `+ _fb_clicks("MAP", ws, we)` term to the `chiro_link_clicks` branch, and add MAP to BOTH the `spend` and `clicks` accumulators in the `chiro_cpc` branch. Final state:

```python
            if metric_id == "chiro_ad_spend":
                weekly_values.append(
                    _fb_sum("Chiro", "spend", ws, we)
                    + _fb_sum("EMX", "spend", ws, we)
                    + _fb_sum("TheraRay", "spend", ws, we)
                    + _fb_sum("NLAP", "spend", ws, we)
                    + _fb_sum("Practice Growth Workshop", "spend", ws, we)
                    + _fb_sum("MAP", "spend", ws, we)
                )
            elif metric_id == "chiro_link_clicks":
                weekly_values.append(
                    _fb_clicks("Chiro", ws, we)
                    + _fb_clicks("EMX", ws, we)
                    + _fb_clicks("TheraRay", ws, we)
                    + _fb_clicks("NLAP", ws, we)
                    + _fb_clicks("Practice Growth Workshop", ws, we)
                    + _fb_clicks("MAP", ws, we)
                )
            elif metric_id == "chiro_cpc":
                spend = (_fb_sum("Chiro", "spend", ws, we)
                         + _fb_sum("EMX", "spend", ws, we)
                         + _fb_sum("TheraRay", "spend", ws, we)
                         + _fb_sum("NLAP", "spend", ws, we)
                         + _fb_sum("Practice Growth Workshop", "spend", ws, we)
                         + _fb_sum("MAP", "spend", ws, we))
                clicks = (_fb_clicks("Chiro", ws, we)
                          + _fb_clicks("EMX", ws, we)
                          + _fb_clicks("TheraRay", ws, we)
                          + _fb_clicks("NLAP", ws, we)
                          + _fb_clicks("Practice Growth Workshop", ws, we)
                          + _fb_clicks("MAP", ws, we))
                weekly_values.append(spend / clicks if clicks else 0.0)
```

- [ ] **Step 8: Add the two standalone MAP compute branches**

In the same `weekly_metrics` metric loop, immediately after the `pgw_leads` branch (~line 2590), add:

```python
            elif metric_id == "map_ad_spend":
                weekly_values.append(_fb_sum("MAP", "spend", ws, we))
            elif metric_id == "map_leads":
                weekly_values.append(_contacts_in_group_with_submit("MAP", ws, we))
```

- [ ] **Step 9: Run the new test + the full weekly-scorecard suite**

Run: `python -m pytest dashboard/tests/test_weekly_scorecard.py -v`
Expected: PASS — including the existing `test_chiro_ad_spend_clicks_include_all_paid_groups` (its fixture has no MAP, so combined totals stay 200/20/10) and `test_scorecard_labels_present_and_clean` (label/goal key sets stay aligned).

- [ ] **Step 10: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/config.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): MAP weekly rows + roll MAP spend/clicks/cpc into combined line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Daily VA Summary — MAP submissions / spend / CPL

**Files:**
- Modify: `dashboard/data/reconcile.py` (`daily_va_summary` ~1936-2039)
- Test: `dashboard/tests/test_daily_summary.py`

**Interfaces:**
- Consumes: the `fb` and `contacts` frames already passed to `daily_va_summary` (no new parameter).
- Produces: return dict gains `map_submissions` (int), `map_ad_spend` (float), `map_cpl` (float or None).

- [ ] **Step 1: Write the failing tests**

Append to `dashboard/tests/test_daily_summary.py`:

```python
def test_daily_va_summary_map_standalone():
    fb = pd.DataFrame([
        {"group": "MAP", "spend": 120.0, "date_start": "2026-05-05"},
        {"group": "Chiro", "spend": 400.0, "date_start": "2026-05-05"},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "m1", "typeform_asset_download": "Movement Activation Protocol ",
         "typeform_submission_date": "2026-05-10T12:00:00Z",
         "created": "2026-05-10T12:00:00Z"},
        {"hs_id": "m2", "typeform_asset_download": "Movement Activation Protocol ",
         "typeform_submission_date": "2026-05-11T12:00:00Z",
         "created": "2026-05-11T12:00:00Z"},
        {"hs_id": "c1", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-10T12:00:00Z",
         "created": "2026-05-10T12:00:00Z"},
    ])
    out = daily_va_summary(
        fb=fb, contacts=contacts,
        theraray_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        nlap_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        start=_d(2026, 5, 1), end=_d(2026, 5, 21),
        asset_to_group={
            "Top 10 typeform": "Chiro",
            "Movement Activation Protocol ": "MAP",
        },
    )
    assert out["map_submissions"] == 2
    assert out["map_ad_spend"] == 120.0
    assert out["map_cpl"] == 60.0
    # MAP standalone: does not leak into Chiro totals
    assert out["chiro_spend"] == 400.0
    assert out["chiro_all_leads"] == 1
```

Also add these three assertions to the END of the existing `test_daily_va_summary_handles_empty_inputs`:

```python
    assert out["map_submissions"] == 0
    assert out["map_ad_spend"] == 0.0
    assert out["map_cpl"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dashboard/tests/test_daily_summary.py -v`
Expected: FAIL — `KeyError: 'map_submissions'`.

- [ ] **Step 3: Compute MAP submissions (asset-based)**

In `daily_va_summary`, inside the `if not cx.empty:` block (after `chiro_new_leads` is computed, ~line 1982), add:

```python
        map_mask = cx["group"] == "MAP"
        map_submissions = int((map_mask & in_submit_window).sum())
```

And in the matching `else:` block (~line 1983-1985), add:

```python
        map_submissions = 0
```

- [ ] **Step 4: Compute MAP spend (FB group-based)**

In the FB spend section, add a `map_spend` line next to `nlap_spend` in the `if not fb.empty ...:` branch:

```python
        map_spend = float(
            fb.loc[in_window & (fb["group"] == "MAP"), "spend"].sum()
        )
```

And in its `else:` branch, add:

```python
        map_spend = 0.0
```

- [ ] **Step 5: Add the three MAP keys to the return dict**

In the `return {...}` of `daily_va_summary`, after the `nlap_*` keys, add:

```python
        "map_submissions": map_submissions,
        "map_ad_spend": map_spend,
        "map_cpl": (map_spend / map_submissions) if map_submissions else None,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest dashboard/tests/test_daily_summary.py -v`
Expected: PASS (all daily-summary tests).

- [ ] **Step 7: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/tests/test_daily_summary.py
git commit -m "feat(metrics): daily VA summary exposes MAP submissions/spend/CPL

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: METRICS tab render — MAP daily-summary block + money formatting

**Files:**
- Modify: `dashboard/sections/metrics.py` (`_money_metric_ids` ~54; `_render_daily_summary` cards ~161-191; copy-text block ~233-251)
- Test: `dashboard/tests/test_metrics_render.py` (create)

**Interfaces:**
- Consumes: `daily_va_summary` output keys `map_submissions`, `map_ad_spend`, `map_cpl` (from Task 2); weekly row key `map_ad_spend` (from Task 1).
- Produces: no new callable; UI only, plus `_money_metric_ids()` now includes `map_ad_spend`.

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_metrics_render.py`:

```python
"""Guards for the METRICS tab render wiring."""
from dashboard.sections.metrics import _money_metric_ids


def test_map_ad_spend_formats_as_money():
    # MAP ad spend must render as whole dollars in the weekly scorecard grid.
    assert "map_ad_spend" in _money_metric_ids()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dashboard/tests/test_metrics_render.py -v`
Expected: FAIL — `map_ad_spend` not in the set.

- [ ] **Step 3: Add `map_ad_spend` to `_money_metric_ids`**

In `dashboard/sections/metrics.py`, update the set:

```python
def _money_metric_ids() -> set[str]:
    """Whole-dollar money metrics (rounded to integer)."""
    return {"chiro_ad_spend", "pt_ad_spend",
            "theraray_ad_spend", "emx_ad_spend", "map_ad_spend"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest dashboard/tests/test_metrics_render.py -v`
Expected: PASS.

- [ ] **Step 5: Add the MAP card block to the MTD column**

In `_render_daily_summary`, in the `with col_mtd:` block, immediately after the NLAP card block (after the `k.metric("Cost / Submission", _money_or_dash(mtd["nlap_cpl"]), help=...)` lines, ~line 167), add:

```python
        st.markdown("**MAP**")
        map_a, map_b = st.columns(2)
        map_a.metric("Submissions", mtd["map_submissions"])
        map_b.metric("Ad Spend", _money(mtd["map_ad_spend"]))
        map_c, _ = st.columns(2)
        map_c.metric("Cost / Submission", _money_or_dash(mtd["map_cpl"]),
                     help="MAP Ad Spend / Submissions.")
```

- [ ] **Step 6: Add the MAP card block to the Yesterday column**

In the `with col_yday:` block, immediately after the NLAP card block (after `k.metric("Cost / Submission", _money_or_dash(yday["nlap_cpl"]))`, ~line 191), add:

```python
        st.markdown("**MAP**")
        map_a2, map_b2 = st.columns(2)
        map_a2.metric("Submissions", yday["map_submissions"])
        map_b2.metric("Ad Spend", _money(yday["map_ad_spend"]))
        map_c2, _ = st.columns(2)
        map_c2.metric("Cost / Submission", _money_or_dash(yday["map_cpl"]))
```

- [ ] **Step 7: Add the MAP section to the copy-pastable text block**

In the `text = (...)` f-string, immediately after the final NLAP `Cost per Submission` lines (after `f"{_fmt_cpl(yday['nlap_cpl'])}\n"`, ~line 250) and before the closing `)`, insert:

```python
        f"\nMAP Submissions\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}      - "
        f"{mtd['map_submissions']} submissions\n"
        f"{yesterday.strftime('%b %d')}                    - "
        f"{yday['map_submissions']} submission\n\n"
        f"AD Spent\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}    - "
        f"${mtd['map_ad_spend']:,.2f}\n"
        f"{yesterday.strftime('%b %d')}                 - "
        f"${yday['map_ad_spend']:,.2f}\n\n"
        f"Cost per Submission\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}    - "
        f"{_fmt_cpl(mtd['map_cpl'])}\n"
        f"{yesterday.strftime('%b %d')}                 - "
        f"{_fmt_cpl(yday['map_cpl'])}\n"
```

- [ ] **Step 8: Sanity-check the module imports and full test suite**

Run: `python -c "import dashboard.sections.metrics"` (Expected: no error, confirms f-string / syntax valid.)
Run: `python -m pytest dashboard/tests/ -q` (Expected: all pass.)

- [ ] **Step 9: Commit**

```bash
git add dashboard/sections/metrics.py dashboard/tests/test_metrics_render.py
git commit -m "feat(metrics): MAP block in Daily Summary cards + copy text; money-format MAP spend

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: EXECUTIVE tab — add MAP to the group ordering

**Files:**
- Modify: `dashboard/sections/executive.py` (`preferred` list, ~line 338)

**Interfaces:**
- Consumes: `group_marketing_metrics` output (already data-driven; emits a MAP row whenever MAP spend or MAP leads exist).
- Produces: MAP appears in the "Breakdown by group" ordering and the "Conversions by group" section.

- [ ] **Step 1: Add "MAP" to the `preferred` list**

In `dashboard/sections/executive.py`, change:

```python
        preferred = ["Chiro", "EMX", "Practice Growth Workshop", "PT Recovery", "TheraRay", "NLAP"]
```

to:

```python
        preferred = ["Chiro", "EMX", "Practice Growth Workshop", "PT Recovery", "TheraRay", "NLAP", "MAP"]
```

- [ ] **Step 2: Sanity-check import + full suite**

Run: `python -c "import dashboard.sections.executive"` (Expected: no error.)
Run: `python -m pytest dashboard/tests/ -q` (Expected: all pass.)

- [ ] **Step 3: Commit**

```bash
git add dashboard/sections/executive.py
git commit -m "feat(executive): add MAP to per-group breakdown ordering

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Live verification (after all tasks)

Not a code task, but required before declaring done:
- Launch the dashboard, open EXECUTIVE → confirm a MAP row appears in "Breakdown by group" with non-zero spend/leads (MAP has ~13 leads/120d historically).
- Open METRICS → confirm the MAP block renders in both MTD and Yesterday cards, the copy-text has a MAP section, and the weekly grid shows `MAP - Ad Spend` (as `$`) and `MAP - Leads` rows plus the combined line labeled "... + MAP".
- Spot-check that the combined `chiro_ad_spend` weekly figure increased by exactly the MAP spend vs. before.

## Self-Review (completed)

1. **Spec coverage:** daily summary (Task 2 + 3), weekly scorecard rows + combined rollin (Task 1), EXECUTIVE ordering (Task 4), money formatting (Task 3). All spec sections A-D covered. FB data-layer grouping already exists (no task, per spec).
2. **Placeholder scan:** none — all steps carry concrete code.
3. **Type consistency:** key names `map_submissions` / `map_ad_spend` / `map_cpl` (daily) and `map_ad_spend` / `map_leads` (weekly) are used identically across producer (reconcile) and consumer (metrics) tasks. `_METRIC_LABELS` and `METRICS_GOALS` both gain `map_ad_spend` + `map_leads` (set-equality guard honored).
4. **Standalone-vs-rollin nuance:** MAP leads deliberately excluded from `chiro_lead_magnet_optins` / `chiro_new_leads` (Task 1 test asserts they stay 0), unlike PGW which rolls leads in. Only spend/clicks/cpc roll in.
