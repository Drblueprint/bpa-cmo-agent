# Weekly Metrics Scorecard Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 5 missing Ninety-scorecard rows to the dashboard's Weekly Metrics grid (superset), wire the TheraRay/NLAP list merge into the weekly render, then verify every cell against the live scorecard.

**Architecture:** `weekly_metrics()` in `dashboard/data/reconcile.py` is a pure aggregator driven by a `_METRIC_LABELS` registry; each metric_id has a branch in a per-week loop. We add 5 metric_ids (labels + goals + branches), one helper for DTI group calls, one helper for DIRECT-BOFU. The `metrics.py` render merges TheraRay (list 6280) and NLAP (list 7086) members into `contacts` (via the existing `merge_list_group`) BEFORE meetings load, so those contacts are group-tagged and their meetings are fetched.

**Tech Stack:** Python, pandas, Streamlit. Tests via `python -m pytest dashboard/tests -q` (run through the Bash tool — the context-mode python is a Windows stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-06-17-weekly-metrics-scorecard-alignment-design.md`.

**Conventions:** PURE rollups (config injected, never imported). No em dashes / AI-style punctuation in any user-facing label. Stage only the files each task names (the repo has unrelated pre-existing modified/untracked files — leave them). End every commit message with the trailer:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

## Task 1: Metric registry — labels + goals (5 new rows, relabel, de-em-dash)

**Files:**
- Modify: `dashboard/data/reconcile.py` (`_METRIC_LABELS`, ~1926-1954)
- Modify: `dashboard/config.py` (`METRICS_GOALS`, ~449-477)
- Test: `dashboard/tests/test_weekly_scorecard.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_weekly_scorecard.py`:

```python
from dashboard.data.reconcile import _METRIC_LABELS
from dashboard.config import METRICS_GOALS


def test_scorecard_labels_present_and_clean():
    new = [
        "theraray_submissions", "nlap_submissions",
        "dti_15min_scheduled", "dti_discovery_completed",
        "bofu_submissions_direct",
    ]
    for mid in new:
        assert mid in _METRIC_LABELS, f"missing label for {mid}"
        assert mid in METRICS_GOALS, f"missing goal for {mid}"
    # No em dashes anywhere in user-facing labels.
    for label in _METRIC_LABELS.values():
        assert "—" not in label, f"em dash in label: {label!r}"
    # Registry and goals keys stay aligned.
    assert set(_METRIC_LABELS) == set(METRICS_GOALS)
    # Specific goals from the Ninety scorecard.
    assert METRICS_GOALS["nlap_submissions"] == 15
    assert METRICS_GOALS["dti_15min_scheduled"] == 2
    assert METRICS_GOALS["dti_discovery_completed"] == 5
    # Relabel: the FB TheraRay row is disambiguated.
    assert _METRIC_LABELS["theraray_leads"] == "TheraRay - FB Leads"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py -q`
Expected: FAIL (KeyError / assertion — new ids absent, em dashes present).

- [ ] **Step 3: Replace `_METRIC_LABELS` in `reconcile.py`**

Replace the entire `_METRIC_LABELS` dict (reconcile.py ~1926-1954) with this — note plain hyphens throughout, the relabeled `theraray_leads`, and the 5 new rows placed in scorecard-adjacent positions:

```python
_METRIC_LABELS: dict[str, str] = {
    "chiro_ad_spend": "Chiro - Ad Spend (incl. EMX)",
    "chiro_link_clicks": "Chiro - Link Clicks (incl. EMX)",
    "chiro_cpc": "Chiro - Cost-Per-Click (incl. EMX)",
    "chiro_lead_magnet_optins": "Chiro - Lead Magnet Opt-Ins (incl. EMX)",
    "chiro_new_leads": "Chiro - New Leads (incl. EMX)",
    "theraray_submissions": "DTI (TheraRay Leads)",
    "nlap_submissions": "DTI (NLAP Leads)",
    "pt_ad_spend": "PT - Ad Spend",
    "pt_link_clicks": "PT - Link Clicks",
    "pt_cpc": "PT - Cost-Per-Click",
    "pt_lead_magnet_optins": "PT - Lead Magnet Opt-Ins",
    "pt_new_leads": "PT - New Leads",
    "theraray_ad_spend": "TheraRay - Ad Spend",
    "theraray_leads": "TheraRay - FB Leads",
    "theraray_15min_scheduled": "TheraRay - 15 Min Call Scheduled",
    "emx_ad_spend": "EMX - Ad Spend",
    "emx_leads": "EMX - Leads",
    "webinar_registrations": "Webinar Registrations",
    "webinar_completions": "Webinar Completions",
    "pt_webinar_registrations": "PT Webinar Registrations",
    "pt_webinar_completions": "PT Webinar Completions",
    "bofu_submissions_direct": "BOFU Submissions (Direct)",
    "bofu_submissions_total": "BOFU Submissions (Total)",
    "fifteen_min_scheduled": "15 Min Calls Scheduled",
    "fifteen_min_completed": "15 Min Calls Completed",
    "dti_15min_scheduled": "DTI 15 Min Call Scheduled",
    "dti_discovery_completed": "DTI Discovery Calls Completed",
    "pt_fifteen_min_scheduled": "PT 15 Min Calls Scheduled",
    "pt_fifteen_min_completed": "PT 15 Min Calls Completed",
    "strategy_calls_total": "Strategy Calls - Total",
    "strategy_calls_completed": "Strategy Calls - Completed",
    "new_total_customers": "NEW Total Customers",
}
```

- [ ] **Step 4: Add the 5 new goals in `config.py`**

In `METRICS_GOALS` (config.py ~449-477), add these entries (the existing goals already match the scorecard — do NOT change them). Insert the new keys anywhere in the dict:

```python
    "theraray_submissions": 0,
    "nlap_submissions": 15,
    "dti_15min_scheduled": 2,
    "dti_discovery_completed": 5,
    "bofu_submissions_direct": 0,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/config.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): scorecard metric registry + goals; plain-hyphen labels

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Note: after this task the 5 new rows render as 0 (no compute branch yet — they hit the loop's `else: append(0)`). Tasks 2-4 add the compute.

---

## Task 2: DTI discovery-call rows (TheraRay + NLAP combined)

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_meetings_count_groups` near `_meetings_count_group` ~2095; add 2 loop branches ~2214)
- Test: `dashboard/tests/test_weekly_scorecard.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
from datetime import date
import pandas as pd
from dashboard.data.reconcile import weekly_metrics

# Contacts fixture MUST carry all 5 date columns weekly_metrics parses, or it
# raises on the non-empty path. None is fine where unused.
_CONTACT_DATE_COLS = [
    "typeform_submission_date", "webinar_registration_date",
    "webinar_completed_date", "pt_webinar_registration_date",
    "pt_webinar_completed_date",
]


def _contacts(rows):
    df = pd.DataFrame(rows)
    for c in (["hs_id", "typeform_asset_download", "email"] + _CONTACT_DATE_COLS):
        if c not in df.columns:
            df[c] = None
    return df


def _ms(iso):
    return int(pd.Timestamp(iso).timestamp() * 1000)


WEEK = (date(2026, 6, 8), date(2026, 6, 14))


def _run(contacts, *, meetings=None, bofu=None):
    return weekly_metrics(
        fb=pd.DataFrame(),
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


def test_dti_calls_combine_theraray_and_nlap_only():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "TR", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "NL", "email": "b@x.com"},
        {"hs_id": "3", "typeform_asset_download": "CH", "email": "c@x.com"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-06-09T15:00:00Z"},
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "15 min call",
         "outcome": "SCHEDULED", "start_time": "2026-06-10T15:00:00Z"},
        {"meeting_id": "m3", "contact_id": "3", "activity_type": "15 min call",
         "outcome": "COMPLETED", "start_time": "2026-06-11T15:00:00Z"},
        # DTI Intro Call activity type must NOT count (Kurt: 15-min only).
        {"meeting_id": "m4", "contact_id": "1", "activity_type": "DTI Intro Call",
         "outcome": "COMPLETED", "start_time": "2026-06-09T16:00:00Z"},
    ])
    r = _run(contacts, meetings=meetings)
    assert r.loc["dti_15min_scheduled", "w0"] == 2     # TR + NL 15-min; Chiro excluded; intro excluded
    assert r.loc["dti_discovery_completed", "w0"] == 1  # only TR held (COMPLETE*)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_dti_calls_combine_theraray_and_nlap_only -q`
Expected: FAIL (`dti_15min_scheduled` computes 0 via the `else` branch).

- [ ] **Step 3: Add the `_meetings_count_groups` helper**

In `reconcile.py`, immediately AFTER the `_meetings_count_group` function (ends ~2114, `return int(mask.sum())`), add:

```python
    def _meetings_count_groups(groups: set[str], start: date, end: date,
                               *, completed_only: bool = False) -> int:
        """Discovery (15-min / protocol-mapping) meetings booked in window for
        contacts whose group is in `groups`. Used for the combined DTI funnel."""
        if meetings.empty or contacts.empty:
            return 0
        group_contact_ids = set(
            contacts.loc[contacts["group"].isin(groups), "hs_id"].astype(str)
        )
        if not group_contact_ids:
            return 0
        mask = (
            discovery_mask(m_types)
            & m_start.between(start, end)
            & meetings["contact_id"].astype(str).isin(group_contact_ids)
        )
        if completed_only:
            mask = mask & m_outcomes.str.startswith("COMPLETE")
        return int(mask.sum())
```

- [ ] **Step 4: Add the two loop branches**

In the per-week loop, AFTER the `theraray_15min_scheduled` branch (reconcile.py ~2213-2214), add:

```python
            elif metric_id == "dti_15min_scheduled":
                weekly_values.append(
                    _meetings_count_groups({"TheraRay", "NLAP"}, ws, we))
            elif metric_id == "dti_discovery_completed":
                weekly_values.append(
                    _meetings_count_groups({"TheraRay", "NLAP"}, ws, we,
                                           completed_only=True))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): DTI discovery-call rows (TheraRay + NLAP combined)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: TheraRay + NLAP submission rows (list-based)

**Files:**
- Modify: `dashboard/data/reconcile.py` (add 2 loop branches ~2218)
- Test: `dashboard/tests/test_weekly_scorecard.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
def test_theraray_nlap_submissions_by_group_and_date():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "TR",
         "typeform_submission_date": "2026-06-09T10:00:00Z", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "NL",
         "typeform_submission_date": "2026-06-10T10:00:00Z", "email": "b@x.com"},
        # NLAP contact submitted OUTSIDE the week -> not counted.
        {"hs_id": "3", "typeform_asset_download": "NL",
         "typeform_submission_date": "2026-05-01T10:00:00Z", "email": "c@x.com"},
        # Chiro contact -> not a DTI submission.
        {"hs_id": "4", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-09T10:00:00Z", "email": "d@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["theraray_submissions", "w0"] == 1
    assert r.loc["nlap_submissions", "w0"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_theraray_nlap_submissions_by_group_and_date -q`
Expected: FAIL (both compute 0 via `else`).

- [ ] **Step 3: Add the two loop branches**

In the per-week loop, AFTER the new `dti_discovery_completed` branch (from Task 2), add:

```python
            elif metric_id == "theraray_submissions":
                weekly_values.append(
                    _contacts_in_group_with_submit("TheraRay", ws, we))
            elif metric_id == "nlap_submissions":
                weekly_values.append(
                    _contacts_in_group_with_submit("NLAP", ws, we))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): DTI TheraRay/NLAP list-submission rows

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: BOFU Submissions (Direct) — skipped-webinar rule

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_bofu_direct_in_week` after `_bofu_in_week` ~2163; add 1 loop branch ~2228)
- Test: `dashboard/tests/test_weekly_scorecard.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_weekly_scorecard.py`:

```python
def test_bofu_direct_excludes_webinar_registrants():
    contacts = _contacts([
        # Registered for a webinar -> their BOFU is NOT direct.
        {"hs_id": "1", "typeform_asset_download": "CH", "email": "webinar@x.com",
         "webinar_registration_date": "2026-06-01T10:00:00Z"},
        # Registered for PT webinar -> also NOT direct.
        {"hs_id": "2", "typeform_asset_download": "CH", "email": "ptweb@x.com",
         "pt_webinar_registration_date": "2026-06-02T10:00:00Z"},
    ])
    bofu = pd.DataFrame([
        {"form_id": "f", "submission_id": "s1", "submitted_at": _ms("2026-06-10T12:00:00Z"),
         "email": "webinar@x.com"},   # has webinar -> not direct
        {"form_id": "f", "submission_id": "s2", "submitted_at": _ms("2026-06-10T12:00:00Z"),
         "email": "ptweb@x.com"},     # has PT webinar -> not direct
        {"form_id": "f", "submission_id": "s3", "submitted_at": _ms("2026-06-11T12:00:00Z"),
         "email": "direct@x.com"},    # no webinar record -> DIRECT
    ])
    r = _run(contacts, bofu=bofu)
    assert r.loc["bofu_submissions_total", "w0"] == 3
    assert r.loc["bofu_submissions_direct", "w0"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py::test_bofu_direct_excludes_webinar_registrants -q`
Expected: FAIL (`bofu_submissions_direct` is 0).

- [ ] **Step 3: Add the `_bofu_direct_in_week` helper**

In `reconcile.py`, immediately AFTER `_bofu_in_week` (ends ~2163), add:

```python
    def _bofu_direct_in_week(start: date, end: date) -> int:
        """BOFU submissions in window whose email matches NO contact carrying a
        webinar registration (the lead reached BOFU without the webinar funnel).
        Unknown emails count as Direct (no webinar on record)."""
        if bofu_submissions.empty:
            return 0
        in_week = bofu_submissions["submitted_at"].apply(
            lambda x: _ts_ms_in_window(x, start, end)
        )
        if not bool(in_week.any()):
            return 0
        webinar_emails: set[str] = set()
        if not contacts.empty and "email" in contacts.columns:
            reg = contacts["_webinar_reg"].apply(lambda d: d is not None) \
                | contacts["_pt_webinar_reg"].apply(lambda d: d is not None)
            webinar_emails = set(
                contacts.loc[reg, "email"].fillna("").astype(str).str.lower()
            )
            webinar_emails.discard("")
        sub_emails = bofu_submissions.loc[in_week, "email"].fillna("").astype(str).str.lower()
        direct = sub_emails.apply(lambda e: e == "" or e not in webinar_emails)
        return int(direct.sum())
```

- [ ] **Step 4: Add the loop branch**

In the per-week loop, immediately BEFORE the `bofu_submissions_total` branch (reconcile.py ~2227), add:

```python
            elif metric_id == "bofu_submissions_direct":
                weekly_values.append(_bofu_direct_in_week(ws, we))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_weekly_scorecard.py -q`
Expected: PASS.

- [ ] **Step 6: Run the FULL suite (no regressions)**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (prior count + new tests).

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_weekly_scorecard.py
git commit -m "feat(metrics): BOFU Submissions (Direct) skipped-webinar row

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Wire TheraRay/NLAP list merge into the weekly render

**Files:**
- Modify: `dashboard/sections/metrics.py` (insert merge after contacts load ~291; change `asset_to_group=` arg in the `weekly_metrics(...)` call ~345)

No unit test (Streamlit render). Verified by `ast.parse` + the Task 6 live probe, which runs the full merged path against real data.

- [ ] **Step 1: Insert the list merge before downstream loads**

In `metrics.py`, the contacts load ends ~291 (`contacts = pd.DataFrame()` in the except). Immediately AFTER that `try/except` block and BEFORE the `contact_deals` load (~293), insert:

```python
    # Merge TheraRay (6280) + NLAP (7086) list members into the weekly contacts
    # frame so they are group-tagged (DTI submissions + DTI calls) and their
    # meetings get fetched below. asset_to_group is a local copy so we register
    # the list asset labels without mutating the module-level config dict.
    from dashboard.data.groups import merge_list_group
    from dashboard.data.hubspot_loader import load_list_memberships
    asset_to_group = dict(cfg.ASSET_TO_GROUP)
    for _lid, _label, _grp in [
        (cfg.THERARAY_HUBSPOT_LIST_ID, "TheraRay (List)", "TheraRay"),
        (cfg.NLAP_HUBSPOT_LIST_ID, "NLAP (List)", "NLAP"),
    ]:
        try:
            contacts = merge_list_group(
                contacts,
                list_id=_lid, asset_label=_label, group=_grp,
                start=overall_start, end=overall_end,
                load_memberships=load_list_memberships,
                load_contacts=load_contacts_by_ids,
                asset_to_group=asset_to_group,
            )
        except Exception as e:
            st.warning(f"{_grp} list merge failed: {e}")
```

- [ ] **Step 2: Use the merged `asset_to_group` in the weekly_metrics call**

In the `weekly_metrics(...)` call (~341-348), change the argument:

```python
        asset_to_group=cfg.ASSET_TO_GROUP,
```

to:

```python
        asset_to_group=asset_to_group,
```

(Leave every other argument unchanged.)

- [ ] **Step 3: Verify the module parses and imports resolve**

Run:
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/sections/metrics.py', encoding='utf-8').read()); print('ast OK')"
```
Expected: `ast OK`.

Also confirm the symbols exist (no import error):
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "from dashboard.data.groups import merge_list_group; from dashboard.data.hubspot_loader import load_list_memberships, load_contacts_by_ids; import dashboard.config as c; print(c.THERARAY_HUBSPOT_LIST_ID, c.NLAP_HUBSPOT_LIST_ID)"
```
Expected: prints `6280 7086`.

- [ ] **Step 4: Confirm `load_contacts_by_ids` is already imported in metrics.py**

It is imported near the top (`from dashboard.data.hubspot_loader import (... load_contacts_by_ids ...)`). If a fresh read shows it is NOT imported, add it to that import block. Do not duplicate.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/sections/metrics.py
git commit -m "feat(metrics): merge TheraRay/NLAP list members into weekly render

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Verify against the Ninety scorecard, then push

This task is run by the ORCHESTRATOR (interactive — presents a diff to Kurt), not a fresh subagent.

- [ ] **Step 1: Write the verification probe**

Create `_probe_weekly_verify.py` at repo root:

```python
"""Compute the live weekly grid (with the TheraRay/NLAP merge) so it can be
diffed against the Ninety scorecard screenshot. Run: python _probe_weekly_verify.py
"""
from datetime import date, timedelta

import dashboard.config as cfg
from dashboard.data.groups import merge_list_group
from dashboard.data.hubspot_loader import (
    load_marketing_contacts, load_contact_deals, load_closed_deals_in_window,
    load_meetings_for_contacts, load_contacts_by_ids, load_list_memberships,
)
from dashboard.data.hubspot_forms_loader import load_form_submissions
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.reconcile import weekly_metrics, _METRIC_LABELS


def week_ranges(n):
    today = date(2026, 6, 17)
    monday = today - timedelta(days=today.weekday())
    out = []
    for i in range(n):
        ws = monday - timedelta(weeks=(n - 1 - i))
        out.append((ws, ws + timedelta(days=6)))
    return out  # oldest first


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
meetings = load_meetings_for_contacts.__wrapped__(contacts["hs_id"].tolist(),
                                                  data_floor_days_back=180)
bofu = load_form_submissions.__wrapped__(cfg.BOFU_FORM_IDS, start, end)

df = weekly_metrics(
    fb=fb, contacts=contacts, meetings=meetings, contact_deals=cds, deals=deals,
    bofu_submissions=bofu, week_ranges=ranges, asset_to_group=asset_to_group,
    stages_closed_won=cfg.STAGES_CLOSED_WON,
    new_customer_stages=cfg.NEW_CUSTOMER_STAGES, goals=cfg.METRICS_GOALS)

hdr = "  ".join(f"{ws.strftime('%m/%d')}" for ws, _ in ranges)
print(f"metric{' '*30}{hdr}")
for _, row in df.iterrows():
    label = _METRIC_LABELS[row["metric_id"]][:34].ljust(34)
    vals = "  ".join(f"{row[f'w{i}']:>6.0f}" if isinstance(row[f'w{i}'], (int, float))
                     else str(row[f'w{i}']) for i in range(len(ranges)))
    print(f"{label}{vals}")
```

- [ ] **Step 2: Run it and capture the grid**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python _probe_weekly_verify.py 2>&1 | grep -v "No runtime found"`
Expected: a printed grid, one row per metric, columns = the 8 weeks (oldest -> newest).

- [ ] **Step 3: Diff vs the Ninety screenshot (orchestrator + Kurt)**

For the weeks the screenshot and the grid share (the 7 fully-entered weeks 27 Apr - 14 Jun), compare each scorecard row. Build a match/mismatch table. For each mismatch, decide whether it is:
- a Ninety manual-entry error (dashboard is right), or
- a dashboard definition gap (fix it). The two most likely definition gaps to scrutinize: **Chiro Lead Magnet Opt-Ins** (FB `fb_leads` vs typeform submissions) and the **DIRECT-BOFU** rule. If a gap is found, fix the definition (with a test), re-run, re-diff.

Present the table to Kurt. Do NOT push until Kurt has seen the verification result.

- [ ] **Step 4: Clean up the probe and push**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
rm -f _probe_weekly_verify.py _probe_outcomes_held.py
git push origin feature/cmo-dashboard
```

- [ ] **Step 5: Live confirm**

After deploy (~1-2 min), open the METRICS tab and confirm the 5 new rows render with the right labels/goals and sensible weekly values; screenshot for Kurt.

---

## Self-Review

**Spec coverage:**
- 5 new rows (theraray_submissions, nlap_submissions, dti_15min_scheduled, dti_discovery_completed, bofu_submissions_direct) → Tasks 1-4. ✓
- Goals adopted → Task 1 (existing already match; only 5 new added). ✓
- Label cleanup (theraray_leads relabel + de-em-dash) → Task 1. ✓
- Held = COMPLETE* verified, no change → documented in spec; tests assert COMPLETE* held in Task 2. ✓
- DTI = 15-min for TheraRay+NLAP contacts only (intro types excluded) → Task 2 (test asserts DTI Intro Call excluded). ✓
- DIRECT-BOFU skipped-webinar rule → Task 4. ✓
- Render merge so groups/meetings resolve → Task 5. ✓
- Verification probe vs screenshot → Task 6. ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; commands have expected output. ✓

**Type/name consistency:** `_meetings_count_groups(groups: set, start, end, *, completed_only)`, `_bofu_direct_in_week(start, end)`, `_contacts_in_group_with_submit(group, start, end)` (existing), metric_ids identical across registry/branches/tests, group labels "TheraRay"/"NLAP" match `merge_list_group` calls and `asset_to_group` values. ✓
