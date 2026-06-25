# Practice Growth Workshop Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register a new "Practice Growth Workshop" marketing group so its FB spend (and later, typeform leads) is tracked across the dashboard like EMX — with spend visible immediately even at zero leads.

**Architecture:** Mirror EMX. A new `CAMPAIGN_GROUPS` regex tags FB spend; an `ASSET_TO_GROUP` entry tags typeform leads; the group is added to the Cost-per-Stage funnel tuple + the Executive group-ordering list; and `weekly_metrics` gets standalone `pgw_ad_spend`/`pgw_leads` rows plus a roll-in to the blended "Chiro" top-line. The Executive "Breakdown by group" surfaces the spend-only group automatically (it enumerates the union of spend+lead groups).

**Tech Stack:** Python, pandas, Streamlit. Tests: `python -m pytest dashboard/tests -q` (run via the Bash tool — context-mode python is a Windows stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-06-17-practice-growth-workshop-group-design.md`.

**Conventions:** PURE rollups (config injected, never imported). No em dashes in user-facing labels. Stage ONLY the files each task names — the repo has unrelated pre-existing modified/untracked files; leave them. End every commit message with:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

The group label string is exactly `Practice Growth Workshop`. Note: SME commission needs NO change — `SME_CLOSE_COMMISSION` has `"_default": 1000.0`, so a PGW deal already bills at $1000 like EMX.

---

## Task 1: Register the group (spend + funnel + breakdown)

This task alone makes PGW spend show in the Executive "Breakdown by group" even with zero leads.

**Files:**
- Modify: `dashboard/config.py` (`CAMPAIGN_GROUPS` ~line 129; `ASSET_TO_GROUP` ~line 145)
- Modify: `dashboard/data/reconcile.py` (`group_funnel_costs` default `groups` tuple, line 2588)
- Modify: `dashboard/sections/executive.py` (`preferred` list, line 338)
- Test: `dashboard/tests/test_practice_growth_workshop.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `dashboard/tests/test_practice_growth_workshop.py`:

```python
import pandas as pd
from dashboard.data.groups import match_group
from dashboard.config import ASSET_TO_GROUP
from dashboard.data.reconcile import group_marketing_metrics

CAMPAIGN = ("DS | __Practice Growth Workshop Dallas__ Funnel Setup | CBO | "
            "USA | CA | Images June 2026 | C1")


def test_match_group_practice_growth_workshop():
    assert match_group(CAMPAIGN) == "Practice Growth Workshop"


def test_asset_to_group_pgw_dallas():
    assert ASSET_TO_GROUP["Practice Growth Workshop Dallas"] == "Practice Growth Workshop"


def test_group_marketing_metrics_shows_spend_only_group():
    # Spend but no leads -> the group must still get a row (drives the
    # Executive "Breakdown by group" spend-only requirement).
    fb = pd.DataFrame([
        {"group": "Practice Growth Workshop", "spend": 500.0, "fb_leads": 0},
    ])
    contacts = pd.DataFrame(columns=["hs_id", "typeform_asset_download"])
    gm = group_marketing_metrics(
        fb, contacts,
        pd.DataFrame(columns=["contact_id", "deal_id"]),
        pd.DataFrame(columns=["deal_id", "dealstage", "amount"]),
        asset_to_group=ASSET_TO_GROUP,
        stages_15min_booked=set(),
        stages_strategy=set(),
        stages_closed_won=set(),
        meetings=None,
    ).set_index("group")
    assert gm.loc["Practice Growth Workshop", "spend"] == 500.0
    assert gm.loc["Practice Growth Workshop", "marketing_leads"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_practice_growth_workshop.py -q`
Expected: FAIL (match_group returns None; KeyError on ASSET_TO_GROUP).

- [ ] **Step 3: Add the FB regex** (`config.py`, after the EMX entry, line 130)

```python
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",                      re.compile(r"__EMX__|\bEMX\b", re.IGNORECASE)),
    ("Practice Growth Workshop", re.compile(r"__Practice Growth Workshop", re.IGNORECASE)),
    ("Chiro",                    re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery",              re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",                 re.compile(r"__Theraray__", re.IGNORECASE)),
    ("NLAP",                     re.compile(r"__NLAP__", re.IGNORECASE)),
]
```

- [ ] **Step 4: Add the typeform asset mapping** (`config.py` `ASSET_TO_GROUP`, add a line)

```python
    "Practice Growth Workshop Dallas": "Practice Growth Workshop",
```

- [ ] **Step 5: Add to the Cost-per-Stage funnel groups** (`reconcile.py:2588`)

Change:
```python
    groups: tuple[str, ...] = ("Chiro", "EMX", "PT Recovery", "TheraRay", "NLAP"),
```
to:
```python
    groups: tuple[str, ...] = ("Chiro", "EMX", "Practice Growth Workshop", "PT Recovery", "TheraRay", "NLAP"),
```

- [ ] **Step 6: Add to the Executive group ordering** (`executive.py:338`)

Change:
```python
        preferred = ["Chiro", "EMX", "PT Recovery", "TheraRay", "NLAP"]
```
to:
```python
        preferred = ["Chiro", "EMX", "Practice Growth Workshop", "PT Recovery", "TheraRay", "NLAP"]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (existing suite + 3 new).

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/config.py dashboard/data/reconcile.py dashboard/sections/executive.py dashboard/tests/test_practice_growth_workshop.py
git commit -m "feat(metrics): register Practice Growth Workshop group (spend + funnel + breakdown)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Weekly Metrics — standalone PGW rows + Chiro roll-in

**Files:**
- Modify: `dashboard/data/reconcile.py` (`_METRIC_LABELS`; the `chiro_*` + new `pgw_*` branches in `weekly_metrics`)
- Modify: `dashboard/config.py` (`METRICS_GOALS`)
- Test: `dashboard/tests/test_weekly_scorecard.py` (add `"PGW"` to `_run`'s asset map; add one test)

- [ ] **Step 1: Add `"PGW"` to the shared `_run` asset map**

In `dashboard/tests/test_weekly_scorecard.py`, `_run`'s `asset_to_group`:
```python
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro", "EM": "EMX",
                        "PGW": "Practice Growth Workshop"},
```

- [ ] **Step 2: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
def test_pgw_weekly_rows_and_chiro_rollin():
    fb = pd.DataFrame([
        {"group": "Practice Growth Workshop", "spend": 800.0, "inline_link_clicks": 12,
         "fb_leads": 0, "date_start": "2026-06-09"},
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 4,
         "fb_leads": 0, "date_start": "2026-06-09"},
    ])
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "PGW",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-06-09T09:00:00Z", "email": "a@x.com"},
    ])
    r = _run(contacts, fb=fb)
    # standalone PGW rows
    assert r.loc["pgw_ad_spend", "w0"] == 800.0
    assert r.loc["pgw_leads", "w0"] == 1
    # rolled into the blended Chiro top-line
    assert r.loc["chiro_ad_spend", "w0"] == 900.0          # Chiro 100 + PGW 800
    assert r.loc["chiro_link_clicks", "w0"] == 16          # 4 + 12
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 1    # PGW submit rolls in
    assert r.loc["chiro_new_leads", "w0"] == 1             # PGW submit+created -> net-new
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_pgw_weekly_rows_and_chiro_rollin -q`
Expected: FAIL (KeyError on `pgw_ad_spend`; chiro_ad_spend == 100).

- [ ] **Step 4: Add the two standalone labels** (`reconcile.py` `_METRIC_LABELS`, after the `emx_leads` line)

```python
    "emx_ad_spend": "EMX - Ad Spend",
    "emx_leads": "EMX - Leads",
    "pgw_ad_spend": "Practice Growth Workshop - Ad Spend",
    "pgw_leads": "Practice Growth Workshop - Leads",
```

- [ ] **Step 5: Relabel the blended Chiro rows** (`reconcile.py` `_METRIC_LABELS`)

```python
    "chiro_ad_spend": "Chiro - Ad Spend (incl. EMX + DTI + Workshop)",
    "chiro_link_clicks": "Chiro - Link Clicks (incl. EMX + DTI + Workshop)",
    "chiro_cpc": "Chiro - Cost-Per-Click (incl. EMX + DTI + Workshop)",
    "chiro_lead_magnet_optins": "Chiro - Lead Magnet Opt-Ins (incl. EMX + Workshop)",
    "chiro_new_leads": "Chiro - New Leads (incl. EMX + Workshop)",
```

- [ ] **Step 6: Roll PGW into the blended Chiro branches** (`reconcile.py` `weekly_metrics` loop)

Update the four chiro branches to add the Practice Growth Workshop term:

```python
            if metric_id == "chiro_ad_spend":
                weekly_values.append(
                    _fb_sum("Chiro", "spend", ws, we)
                    + _fb_sum("EMX", "spend", ws, we)
                    + _fb_sum("TheraRay", "spend", ws, we)
                    + _fb_sum("NLAP", "spend", ws, we)
                    + _fb_sum("Practice Growth Workshop", "spend", ws, we)
                )
            elif metric_id == "chiro_link_clicks":
                weekly_values.append(
                    _fb_clicks("Chiro", ws, we)
                    + _fb_clicks("EMX", ws, we)
                    + _fb_clicks("TheraRay", ws, we)
                    + _fb_clicks("NLAP", ws, we)
                    + _fb_clicks("Practice Growth Workshop", ws, we)
                )
            elif metric_id == "chiro_cpc":
                spend = (_fb_sum("Chiro", "spend", ws, we)
                         + _fb_sum("EMX", "spend", ws, we)
                         + _fb_sum("TheraRay", "spend", ws, we)
                         + _fb_sum("NLAP", "spend", ws, we)
                         + _fb_sum("Practice Growth Workshop", "spend", ws, we))
                clicks = (_fb_clicks("Chiro", ws, we)
                          + _fb_clicks("EMX", ws, we)
                          + _fb_clicks("TheraRay", ws, we)
                          + _fb_clicks("NLAP", ws, we)
                          + _fb_clicks("Practice Growth Workshop", ws, we))
                weekly_values.append(spend / clicks if clicks else 0.0)
            elif metric_id == "chiro_lead_magnet_optins":
                weekly_values.append(
                    _contacts_in_group_with_submit("Chiro", ws, we)
                    + _contacts_in_group_with_submit("EMX", ws, we)
                    + _contacts_in_group_with_submit("Practice Growth Workshop", ws, we)
                )
            elif metric_id == "chiro_new_leads":
                weekly_values.append(
                    _contacts_in_group_new("Chiro", ws, we)
                    + _contacts_in_group_new("EMX", ws, we)
                    + _contacts_in_group_new("Practice Growth Workshop", ws, we)
                )
```

- [ ] **Step 7: Add the two standalone PGW branches** (`reconcile.py` `weekly_metrics` loop, after the `emx_leads` branch)

```python
            elif metric_id == "pgw_ad_spend":
                weekly_values.append(_fb_sum("Practice Growth Workshop", "spend", ws, we))
            elif metric_id == "pgw_leads":
                weekly_values.append(_contacts_in_group_with_submit("Practice Growth Workshop", ws, we))
```

- [ ] **Step 8: Add the two goals** (`config.py` `METRICS_GOALS`)

```python
    "pgw_ad_spend": 0,
    "pgw_leads": 0,
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS. The `test_scorecard_labels_present_and_clean` test still holds (`set(_METRIC_LABELS) == set(METRICS_GOALS)`; no em dashes).

- [ ] **Step 10: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/config.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): PGW standalone weekly rows + roll into Chiro top-line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Verify live, then push

Run by the ORCHESTRATOR (interactive), not a fresh subagent.

- [ ] **Step 1: Probe FB spend classification + breakdown**

Create `_probe_pgw_verify.py` at repo root:

```python
from datetime import date
import dashboard.config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import load_marketing_contacts, load_contact_deals, load_closed_deals_in_window
from dashboard.data.reconcile import group_marketing_metrics

start, end = date(2026, 6, 1), date(2026, 6, 25)
fb = load_fb_insights.__wrapped__(start, end)
print("PGW FB rows:")
pgw = fb[fb["group"] == "Practice Growth Workshop"]
print(pgw[["campaign_name", "group", "spend"]].to_string() if not pgw.empty else "  (none)")
print(f"PGW total spend: {pgw['spend'].sum() if not pgw.empty else 0}")

contacts = load_marketing_contacts.__wrapped__(start, end)
cds = load_contact_deals.__wrapped__(contacts["hs_id"].tolist())
deals = load_closed_deals_in_window.__wrapped__(
    start, end, closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
    no_closedate_stages=tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE))
gm = group_marketing_metrics(
    fb, contacts, cds, deals, asset_to_group=cfg.ASSET_TO_GROUP,
    stages_15min_booked=cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
    stages_strategy=cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
    stages_closed_won=cfg.STAGES_CLOSED_WON, meetings=None)
print("\nBreakdown rows:")
print(gm[["group", "spend", "marketing_leads", "cpl"]].to_string())
```

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python _probe_pgw_verify.py 2>&1 | grep -v "No runtime found"`
Expected: the PGW campaign classifies to group "Practice Growth Workshop" with spend > 0, AND a "Practice Growth Workshop" row appears in the breakdown with `marketing_leads == 0`.

- [ ] **Step 2: Report to Kurt + clean up + push**

Confirm the PGW spend figure to Kurt. Then:
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
rm -f _probe_pgw_verify.py
git push origin feature/cmo-dashboard
```

- [ ] **Step 3: Live confirm** after deploy (~1-2 min): EXECUTIVE "Breakdown by group" shows the Practice Growth Workshop row with spend; METRICS weekly grid shows the standalone PGW rows; the Chiro top-line label reads "(incl. EMX + DTI + Workshop)".

---

## Self-Review

**Spec coverage:**
- FB regex (spend) → Task 1 Step 3. ✓
- ASSET_TO_GROUP (leads) → Task 1 Step 4. ✓
- Cost-per-Stage funnel groups → Task 1 Step 5. ✓
- Executive group ordering → Task 1 Step 6. ✓
- Spend-only visibility (explicit requirement) → Task 1 Step 1 test (`group_marketing_metrics` spend-only row) + Task 3 live verify. ✓
- Standalone weekly rows `pgw_ad_spend`/`pgw_leads` → Task 2 Steps 4,7. ✓
- Roll into blended Chiro (spend+clicks+cpc+optins+new) + relabels → Task 2 Steps 5,6. ✓
- Goals → Task 2 Step 8. ✓
- SME commission $1000 → already via `SME_CLOSE_COMMISSION["_default"]`, no task needed (noted in header). ✓
- Out of scope (deal-amount default, VA block, per-city rows) → not built. ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; commands have expected output. ✓

**Type/name consistency:** group label `Practice Growth Workshop` and metric_ids `pgw_ad_spend`/`pgw_leads` identical across config, branches, labels, goals, tests. `pgw_leads` uses `_contacts_in_group_with_submit` (matches the real `emx_leads` branch). The 4 chiro branches use the exact helper names already in the file (`_fb_sum`, `_fb_clicks`, `_contacts_in_group_with_submit`, `_contacts_in_group_new`). `_run` gains a `"PGW"` asset key consumed by the Task 2 test. ✓
