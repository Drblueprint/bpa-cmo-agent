# Weekly Metrics Definition Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four existing Weekly Metrics rows to match what Ninety/Dr. Gumm mean (all-group ad spend, All-vs-New leads, marketing-filtered webinar) and surface cold-outreach calls as their own rows.

**Architecture:** All metric logic lives in the pure `weekly_metrics()` aggregator (`dashboard/data/reconcile.py`), driven by the `_METRIC_LABELS` registry + a per-week if/elif loop. We change four branch bodies, add three helpers + a `_created` date series + a `marketing_ids` set, add 4 cold-outreach rows, and swap the meetings loader in the render so all in-window calls are counted.

**Tech Stack:** Python, pandas, Streamlit. Tests: `python -m pytest dashboard/tests -q` (run via the Bash tool — context-mode python is a Windows stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-06-17-weekly-metrics-definition-gaps-design.md`.

**Conventions:** PURE rollups (config injected, never imported). No em dashes in user-facing labels. Stage ONLY the files each task names — the repo has unrelated pre-existing modified/untracked files; leave them. End every commit message with:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Current state was at 86 passing tests. Shared test helpers live in `dashboard/tests/test_weekly_scorecard.py`: `_contacts(rows)`, `_run(contacts, *, meetings=None, bofu=None)`, `WEEK = (date(2026,6,8), date(2026,6,14))`, `asset_to_group={"TR":"TheraRay","NL":"NLAP","CH":"Chiro"}`.

---

## Task 1: Gap 1 — Chiro Ad Spend / Clicks / CPC = all paid groups

**Files:**
- Modify: `dashboard/data/reconcile.py` (`_METRIC_LABELS` labels; the `chiro_ad_spend` / `chiro_link_clicks` / `chiro_cpc` loop branches)
- Test: `dashboard/tests/test_weekly_scorecard.py` (extend `_run` with an `fb` param; add one test)

- [ ] **Step 1: Add an `fb` param to the shared `_run` helper**

In `dashboard/tests/test_weekly_scorecard.py`, change the `_run` signature/body:

```python
def _run(contacts, *, meetings=None, bofu=None, fb=None):
    return weekly_metrics(
        fb=fb if fb is not None else pd.DataFrame(),
        contacts=contacts,
        meetings=meetings if meetings is not None else pd.DataFrame(
            columns=["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]),
        contact_deals=pd.DataFrame(columns=["contact_id", "deal_id"]),
        deals=pd.DataFrame(),
        bofu_submissions=bofu if bofu is not None else pd.DataFrame(
            columns=["form_id", "submission_id", "submitted_at", "email"]),
        week_ranges=[WEEK],
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro"},
        stages_closed_won=set(),
        new_customer_stages=set(),
        goals={},
    ).set_index("metric_id")
```

- [ ] **Step 2: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
def test_chiro_ad_spend_clicks_include_all_paid_groups():
    fb = pd.DataFrame([
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 10, "fb_leads": 5, "date_start": "2026-06-09"},
        {"group": "EMX", "spend": 50.0, "inline_link_clicks": 5, "fb_leads": 2, "date_start": "2026-06-10"},
        {"group": "TheraRay", "spend": 40.0, "inline_link_clicks": 4, "fb_leads": 1, "date_start": "2026-06-11"},
        {"group": "NLAP", "spend": 10.0, "inline_link_clicks": 1, "fb_leads": 1, "date_start": "2026-06-12"},
        {"group": "PT Recovery", "spend": 999.0, "inline_link_clicks": 99, "fb_leads": 9, "date_start": "2026-06-09"},
    ])
    r = _run(_contacts([]), fb=fb)
    assert r.loc["chiro_ad_spend", "w0"] == 200.0     # Chiro+EMX+TheraRay+NLAP; PT excluded
    assert r.loc["chiro_link_clicks", "w0"] == 20      # 10+5+4+1
    assert abs(r.loc["chiro_cpc", "w0"] - 10.0) < 1e-9  # 200/20
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_chiro_ad_spend_clicks_include_all_paid_groups -q`
Expected: FAIL (`chiro_ad_spend` == 150.0, not 200.0).

- [ ] **Step 4: Update the three loop branches**

In `reconcile.py`, replace the `chiro_ad_spend`, `chiro_link_clicks`, and `chiro_cpc` branches with:

```python
            if metric_id == "chiro_ad_spend":
                weekly_values.append(
                    _fb_sum("Chiro", "spend", ws, we)
                    + _fb_sum("EMX", "spend", ws, we)
                    + _fb_sum("TheraRay", "spend", ws, we)
                    + _fb_sum("NLAP", "spend", ws, we)
                )
            elif metric_id == "chiro_link_clicks":
                weekly_values.append(
                    _fb_clicks("Chiro", ws, we)
                    + _fb_clicks("EMX", ws, we)
                    + _fb_clicks("TheraRay", ws, we)
                    + _fb_clicks("NLAP", ws, we)
                )
            elif metric_id == "chiro_cpc":
                spend = (_fb_sum("Chiro", "spend", ws, we)
                         + _fb_sum("EMX", "spend", ws, we)
                         + _fb_sum("TheraRay", "spend", ws, we)
                         + _fb_sum("NLAP", "spend", ws, we))
                clicks = (_fb_clicks("Chiro", ws, we)
                          + _fb_clicks("EMX", ws, we)
                          + _fb_clicks("TheraRay", ws, we)
                          + _fb_clicks("NLAP", ws, we))
                weekly_values.append(spend / clicks if clicks else 0.0)
```

- [ ] **Step 5: Relabel the three rows in `_METRIC_LABELS`**

```python
    "chiro_ad_spend": "Chiro - Ad Spend (incl. EMX + DTI)",
    "chiro_link_clicks": "Chiro - Link Clicks (incl. EMX + DTI)",
    "chiro_cpc": "Chiro - Cost-Per-Click (incl. EMX + DTI)",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (86 + 1).

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): Chiro ad spend/clicks/CPC span all paid groups

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Gap 2 — Lead Magnet Opt-Ins = All Leads; New Leads = net-new

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_created` parse; add `_contacts_in_group_new`; change `chiro_lead_magnet_optins` + `chiro_new_leads` branches)
- Test: `dashboard/tests/test_weekly_scorecard.py` (add `"created"` to `_CONTACT_DATE_COLS`; add `"EM": "EMX"` to `_run`'s asset map; add one test)

- [ ] **Step 1: Update the shared test helpers**

In `dashboard/tests/test_weekly_scorecard.py`, add `"created"` to `_CONTACT_DATE_COLS`:

```python
_CONTACT_DATE_COLS = [
    "typeform_submission_date", "created",
    "webinar_registration_date", "webinar_completed_date",
    "pt_webinar_registration_date", "pt_webinar_completed_date",
]
```

and add the EMX asset mapping in `_run` (so EMX-group fixtures work):

```python
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro", "EM": "EMX"},
```

- [ ] **Step 2: Write the failing test**

Append:

```python
def test_optins_are_all_leads_new_leads_are_netnew():
    contacts = _contacts([
        # submitted in week, created earlier -> All Lead (opt-in) but NOT new
        {"hs_id": "1", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-01-01T00:00:00Z", "email": "a@x.com"},
        # submitted + created in week -> opt-in AND new
        {"hs_id": "2", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-10T10:00:00Z",
         "created": "2026-06-10T09:00:00Z", "email": "b@x.com"},
        # EMX, submitted + created in week -> opt-in AND new
        {"hs_id": "3", "typeform_asset_download": "EM",
         "typeform_submission_date": "2026-06-11T10:00:00Z",
         "created": "2026-06-11T09:00:00Z", "email": "c@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 3   # all 3 submitted in week
    assert r.loc["chiro_new_leads", "w0"] == 2            # only #2 and #3 are net-new
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_optins_are_all_leads_new_leads_are_netnew -q`
Expected: FAIL (opt-ins computes 0 — currently FB leads; new_leads computes 3 — currently submit-only).

- [ ] **Step 4: Add the `_created` date series**

In `reconcile.py`, in the `if not contacts.empty:` block that sets `_submit_date` (currently lines ~2016-2021), add the `_created` line right after `_submit_date`:

```python
    if not contacts.empty:
        contacts["_submit_date"] = _to_date_series("typeform_submission_date")
        contacts["_created"] = _to_date_series("created")
        contacts["_webinar_reg"] = _to_date_series("webinar_registration_date")
        contacts["_webinar_done"] = _to_date_series("webinar_completed_date")
        contacts["_pt_webinar_reg"] = _to_date_series("pt_webinar_registration_date")
        contacts["_pt_webinar_done"] = _to_date_series("pt_webinar_completed_date")
```

- [ ] **Step 5: Add the `_contacts_in_group_new` helper**

In `reconcile.py`, immediately AFTER `_contacts_in_group_with_submit` (ends ~line 2066, `return int(mask.sum())`), add:

```python
    def _contacts_in_group_new(group: str, start: date, end: date) -> int:
        """Net-new leads: group contacts whose typeform submission AND HubSpot
        createdate both fall in the week (mirrors daily_va_summary New Leads)."""
        if contacts.empty:
            return 0

        def _in(col: str):
            return contacts[col].apply(
                lambda d: d is not None and isinstance(d, date) and start <= d <= end
            )

        mask = (contacts["group"] == group) & _in("_submit_date") & _in("_created")
        return int(mask.sum())
```

- [ ] **Step 6: Change the two branches**

Replace the `chiro_lead_magnet_optins` and `chiro_new_leads` branches:

```python
            elif metric_id == "chiro_lead_magnet_optins":
                weekly_values.append(
                    _contacts_in_group_with_submit("Chiro", ws, we)
                    + _contacts_in_group_with_submit("EMX", ws, we)
                )
            elif metric_id == "chiro_new_leads":
                weekly_values.append(
                    _contacts_in_group_new("Chiro", ws, we)
                    + _contacts_in_group_new("EMX", ws, we)
                )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS. (The existing `test_weekly_metrics_basic_shape` still expects `chiro_new_leads w1 == 1`: its lone contact has submit + created both in week 1, so it stays net-new.)

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): Opt-Ins = All Leads, New Leads = net-new (createdate)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Gap 3 — Webinar Registrations / Completions filtered to Chiro/EMX

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_contacts_in_groups_property`; change `webinar_registrations` + `webinar_completions` branches)
- Test: `dashboard/tests/test_weekly_scorecard.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_webinar_rows_filter_to_chiro_emx():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "CH",
         "webinar_registration_date": "2026-06-09T10:00:00Z",
         "webinar_completed_date": "2026-06-10T10:00:00Z", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "EM",
         "webinar_registration_date": "2026-06-10T10:00:00Z", "email": "b@x.com"},
        # TheraRay contact with a webinar date -> excluded from the generic rows
        {"hs_id": "3", "typeform_asset_download": "TR",
         "webinar_registration_date": "2026-06-11T10:00:00Z", "email": "c@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["webinar_registrations", "w0"] == 2   # Chiro + EMX only; TheraRay excluded
    assert r.loc["webinar_completions", "w0"] == 1     # only #1 completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_webinar_rows_filter_to_chiro_emx -q`
Expected: FAIL (`webinar_registrations` == 3 — currently counts all contacts incl. TheraRay).

- [ ] **Step 3: Add the `_contacts_in_groups_property` helper**

In `reconcile.py`, immediately AFTER `_contacts_property_in_window` (ends ~line 2076), add:

```python
    def _contacts_in_groups_property(groups: set[str], prop_col: str,
                                     start: date, end: date) -> int:
        """Count contacts whose group is in `groups` AND whose date property
        falls in the week. Used for marketing-filtered webinar rows."""
        if contacts.empty or prop_col not in contacts.columns:
            return 0
        in_window = contacts[prop_col].apply(
            lambda d: d is not None and isinstance(d, date) and start <= d <= end
        )
        mask = contacts["group"].isin(groups) & in_window
        return int(mask.sum())
```

- [ ] **Step 4: Change the two branches**

Replace the `webinar_registrations` and `webinar_completions` branches:

```python
            elif metric_id == "webinar_registrations":
                weekly_values.append(
                    _contacts_in_groups_property({"Chiro", "EMX"}, "_webinar_reg", ws, we))
            elif metric_id == "webinar_completions":
                weekly_values.append(
                    _contacts_in_groups_property({"Chiro", "EMX"}, "_webinar_done", ws, we))
```

(Leave `pt_webinar_registrations` / `pt_webinar_completions` unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS. (Existing `test_weekly_metrics_basic_shape` still expects `webinar_registrations w1 == 1`: its contact is group Chiro with the date in week 1.)

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): webinar rows filtered to Chiro/EMX marketing contacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Gap 4 — Cold-outreach call rows

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `marketing_ids`; add `_meetings_count_cold`; add 4 labels; add 4 branches)
- Modify: `dashboard/config.py` (add 4 goals)
- Test: `dashboard/tests/test_weekly_scorecard.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_cold_outreach_call_rows_split_non_marketing():
    # Contact "1" is a marketing lead (in the contacts frame); contact "999" is not.
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "CH", "email": "a@x.com"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETED", "start_time": "2026-06-09T15:00:00Z"},   # marketing
        {"meeting_id": "m2", "contact_id": "999", "activity_type": "15 min call",
         "outcome": "COMPLETED", "start_time": "2026-06-10T15:00:00Z"},   # cold
        {"meeting_id": "m3", "contact_id": "999", "activity_type": "Strategy Call",
         "outcome": "SCHEDULED", "start_time": "2026-06-11T15:00:00Z"},   # cold, not completed
    ])
    r = _run(contacts, meetings=meetings)
    assert r.loc["fifteen_min_scheduled", "w0"] == 2          # all calls counted
    assert r.loc["fifteen_min_scheduled_cold", "w0"] == 1     # only contact 999
    assert r.loc["fifteen_min_completed_cold", "w0"] == 1     # m2 completed
    assert r.loc["strategy_calls_total_cold", "w0"] == 1      # m3
    assert r.loc["strategy_calls_completed_cold", "w0"] == 0  # m3 not completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_cold_outreach_call_rows_split_non_marketing -q`
Expected: FAIL (cold metric_ids missing → KeyError on `.loc`).

- [ ] **Step 3: Add `marketing_ids` near the top of `weekly_metrics`**

In `reconcile.py`, right AFTER the `if not contacts.empty:` date-series block (after the `_pt_webinar_done` line), add:

```python
    marketing_ids = set(contacts["hs_id"].astype(str)) \
        if not contacts.empty and "hs_id" in contacts.columns else set()
```

- [ ] **Step 4: Add the `_meetings_count_cold` helper**

In `reconcile.py`, immediately AFTER `_meetings_count_groups` (ends ~line 2128), add:

```python
    def _meetings_count_cold(token: str, start: date, end: date,
                             *, completed_only: bool = False) -> int:
        """Calls of `token` type in window whose contact is NOT a marketing
        lead (not in the loaded contacts frame) — i.e. cold outreach."""
        if meetings.empty:
            return 0
        _type_mask = discovery_mask(m_types) if token == "15 min" \
            else m_types.str.contains(token, na=False)
        mask = (
            _type_mask
            & m_start.between(start, end)
            & ~meetings["contact_id"].astype(str).isin(marketing_ids)
        )
        if completed_only:
            mask = mask & m_outcomes.str.startswith("COMPLETE")
        return int(mask.sum())
```

- [ ] **Step 5: Add the 4 labels under their parents in `_METRIC_LABELS`**

Insert each cold label directly after its parent:

```python
    "fifteen_min_scheduled": "15 Min Calls Scheduled",
    "fifteen_min_scheduled_cold": "15 Min Scheduled (Cold Outreach)",
    "fifteen_min_completed": "15 Min Calls Completed",
    "fifteen_min_completed_cold": "15 Min Completed (Cold Outreach)",
```

and (further down, around the strategy rows):

```python
    "strategy_calls_total": "Strategy Calls - Total",
    "strategy_calls_total_cold": "Strategy Total (Cold Outreach)",
    "strategy_calls_completed": "Strategy Calls - Completed",
    "strategy_calls_completed_cold": "Strategy Completed (Cold Outreach)",
```

- [ ] **Step 6: Add the 4 branches**

After the existing `fifteen_min_completed` / `strategy_calls_*` branches, add (placement does not affect correctness — each must exist):

```python
            elif metric_id == "fifteen_min_scheduled_cold":
                weekly_values.append(_meetings_count_cold("15 min", ws, we))
            elif metric_id == "fifteen_min_completed_cold":
                weekly_values.append(_meetings_count_cold("15 min", ws, we, completed_only=True))
            elif metric_id == "strategy_calls_total_cold":
                weekly_values.append(_meetings_count_cold("strategy", ws, we))
            elif metric_id == "strategy_calls_completed_cold":
                weekly_values.append(_meetings_count_cold("strategy", ws, we, completed_only=True))
```

- [ ] **Step 7: Add the 4 goals in `config.METRICS_GOALS`**

```python
    "fifteen_min_scheduled_cold": 0,
    "fifteen_min_completed_cold": 0,
    "strategy_calls_total_cold": 0,
    "strategy_calls_completed_cold": 0,
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/config.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): cold-outreach 15-min/strategy call rows

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Render — count all in-window meetings

**Files:**
- Modify: `dashboard/sections/metrics.py` (import `load_meetings_in_window`; swap the meetings load)

No unit test (Streamlit render). Verified by `ast.parse` + the full suite + the Task 6 live probe.

- [ ] **Step 1: Add the import**

In `metrics.py`, the import block at the top (currently imports `load_meetings_for_contacts`, `load_contacts_by_ids` from `dashboard.data.hubspot_loader`) — add `load_meetings_in_window` to that same `from dashboard.data.hubspot_loader import (...)` block.

- [ ] **Step 2: Swap the meetings load**

Replace the meetings load block (currently ~lines 330-335):

```python
    try:
        meetings = load_meetings_for_contacts(contacts["hs_id"].tolist(),
                                              data_floor_days_back=floor_days) \
            if not contacts.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])
```

with (counts ALL in-window calls, not just marketing-contact calls — so 15-Min/Strategy totals are complete and the cold-outreach split works):

```python
    try:
        meetings = load_meetings_in_window(overall_start, overall_end)
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])
```

(`floor_days` may now be unused in this function — if a linter flags it, leave the `st.session_state.get(...)` line only if other code uses it; otherwise it is harmless. Do not remove unrelated lines.)

- [ ] **Step 3: Verify parse + symbols + suite**

Run:
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/sections/metrics.py', encoding='utf-8').read()); print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "from dashboard.data.hubspot_loader import load_meetings_in_window; print('import OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q
```
Expected: `ast OK`, `import OK`, suite green.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/sections/metrics.py
git commit -m "feat(metrics): weekly grid counts all in-window meetings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Verify vs Ninety, then push

Run by the ORCHESTRATOR (interactive — presents a diff to Kurt), not a fresh subagent.

- [ ] **Step 1: Recreate the verification probe** `_probe_weekly_verify.py` at repo root (same as the prior round, with the all-meetings loader):

```python
from datetime import date, timedelta
import dashboard.config as cfg
from dashboard.data.groups import merge_list_group
from dashboard.data.hubspot_loader import (
    load_marketing_contacts, load_contact_deals, load_closed_deals_in_window,
    load_meetings_in_window, load_contacts_by_ids, load_list_memberships,
)
from dashboard.data.hubspot_forms_loader import load_form_submissions
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.reconcile import weekly_metrics, _METRIC_LABELS


def week_ranges(n):
    monday = date(2026, 6, 17) - timedelta(days=date(2026, 6, 17).weekday())
    return [(monday - timedelta(weeks=n - 1 - i),
             monday - timedelta(weeks=n - 1 - i) + timedelta(days=6)) for i in range(n)]


ranges = week_ranges(cfg.METRICS_WEEKS_BACK)
start, end = ranges[0][0], ranges[-1][1]
fb = load_fb_insights.__wrapped__(start, end, time_increment_days=7)
contacts = load_marketing_contacts.__wrapped__(start, end)
asset_to_group = dict(cfg.ASSET_TO_GROUP)
for lid, label, grp in [(cfg.THERARAY_HUBSPOT_LIST_ID, "TheraRay (List)", "TheraRay"),
                        (cfg.NLAP_HUBSPOT_LIST_ID, "NLAP (List)", "NLAP")]:
    contacts = merge_list_group(
        contacts, list_id=lid, asset_label=label, group=grp, start=start, end=end,
        load_memberships=lambda x: load_list_memberships.__wrapped__(x),
        load_contacts=lambda ids: load_contacts_by_ids.__wrapped__(ids),
        asset_to_group=asset_to_group)
cds = load_contact_deals.__wrapped__(contacts["hs_id"].tolist())
deals = load_closed_deals_in_window.__wrapped__(
    start, end, closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
    no_closedate_stages=tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE))
meetings = load_meetings_in_window.__wrapped__(start, end)
bofu = load_form_submissions.__wrapped__(cfg.BOFU_FORM_IDS, start, end)
df = weekly_metrics(
    fb=fb, contacts=contacts, meetings=meetings, contact_deals=cds, deals=deals,
    bofu_submissions=bofu, week_ranges=ranges, asset_to_group=asset_to_group,
    stages_closed_won=cfg.STAGES_CLOSED_WON,
    new_customer_stages=cfg.NEW_CUSTOMER_STAGES, goals=cfg.METRICS_GOALS)
hdr = "  ".join(ws.strftime("%m/%d") for ws, _ in ranges)
print(f"{'metric':<38}{hdr}")
for _, row in df.iterrows():
    label = _METRIC_LABELS[row["metric_id"]][:36].ljust(38)
    cells = "  ".join(f"{row[f'w{i}']:>6.1f}" if isinstance(row[f'w{i}'], float)
                      else f"{int(row[f'w{i}']):>6d}" for i in range(len(ranges)))
    print(label + cells)
```

- [ ] **Step 2: Run it**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python _probe_weekly_verify.py 2>&1 | grep -v "No runtime found"`

- [ ] **Step 3: Diff vs the Ninety screenshot (orchestrator + Kurt)**

Confirm: Chiro Ad Spend now matches Ninety on the 5 confirmed weeks (report clicks); Lead Magnet Opt-Ins matches Ninety; New Leads lands near Ninety's lower numbers; webinar reads higher than Ninety by design (= Chiro/EMX property count); 15-Min/Strategy totals rose toward Ninety; cold rows non-zero where cold outreach occurred. Present the table; do NOT push until Kurt has seen it.

- [ ] **Step 4: Clean up + push**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
rm -f _probe_weekly_verify.py
git push origin feature/cmo-dashboard
```

- [ ] **Step 5: Live confirm** after deploy (~1-2 min): the 4 cold rows render under their parents, the chiro/webinar/lead rows reflect the new definitions.

---

## Self-Review

**Spec coverage:**
- Gap 1 (ad spend/clicks/cpc all groups + relabel) → Task 1. ✓
- Gap 2 (Opt-Ins = All Leads, New Leads = net-new, `_created`) → Task 2. ✓
- Gap 3 (webinar Chiro/EMX via property) → Task 3. ✓
- Gap 4 (all calls + 4 cold rows) → Task 4 (logic) + Task 5 (render loads all meetings). ✓
- Verification vs Ninety → Task 6. ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; commands have expected output. ✓

**Type/name consistency:** helper names `_contacts_in_group_new`, `_contacts_in_groups_property`, `_meetings_count_cold`, `marketing_ids`, and the 4 cold metric_ids are identical across registry, branches, goals, and tests. `_created` parse added before any branch uses it. The render's `load_meetings_in_window(overall_start, overall_end)` matches the loader signature `(start, end)`; `overall_start`/`overall_end` are defined above the meetings load. ✓
