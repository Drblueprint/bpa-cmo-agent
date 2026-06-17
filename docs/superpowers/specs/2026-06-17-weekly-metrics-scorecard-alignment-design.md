# Weekly Metrics Scorecard Alignment — Design

Date: 2026-06-17
Origin: Kurt wants the dashboard's METRICS-tab "Weekly Metrics" grid to replicate
the external Ninety.io EOS scorecard "Marketing - Weekly Update" as closely as
possible, after first verifying the numbers are accurate.

## Goal

Make the dashboard's existing Weekly Metrics grid a trustworthy, complete mirror of
the Ninety scorecard so it can cross-check (and eventually replace) the manually
entered Ninety numbers. Add the scorecard rows that are missing, adopt the
scorecard's goal thresholds, and verify every cell against the live screenshot.

## Decision: Superset (not 1:1 replace)

Kurt chose **superset**: keep the dashboard's current ~27-row grid (which includes PT
Recovery and EMX-split rows the scorecard does not show), and ADD the missing
scorecard metrics + adopt the scorecard goals. Every scorecard metric will be present;
the grid stays a superset.

## Current state (verified by exploration)

- Renderer: `dashboard/sections/metrics.py` `render_metrics()`.
- Backing function: `weekly_metrics(fb, contacts, meetings, contact_deals, deals,
  bofu_submissions, week_ranges, asset_to_group, stages_closed_won,
  new_customer_stages, goals) -> pd.DataFrame` in `dashboard/data/reconcile.py`
  (pure function; returns metric_id, metric_label, goal, sum, w0..wN oldest-first).
- Labels map: `_METRIC_LABELS` (reconcile.py ~1926). Goals: `config.METRICS_GOALS`.
- Weeks: Mon-Sun, 8 weeks back (`cfg.METRICS_WEEKS_BACK`, `_week_ranges()` in metrics.py).
  Matches the Ninety scorecard's Mon-Sun week-ending columns. No change needed.
- BOFU loader: `load_form_submissions(BOFU_FORM_IDS, start, end)` from
  `dashboard/data/hubspot_forms_loader.py`, columns `[form_id, submission_id,
  submitted_at, email]`. `BOFU_FORM_IDS` = the two Master Booking Forms (config.py:428).
- Held/completed counting everywhere uses `outcome.upper().startswith("COMPLETE")`.

## Verified data semantics

### Held / completed outcomes (Kurt flagged this)

Probe of every `hs_meeting_outcome` value Mar 1 - Jun 17 2026 (`_probe_outcomes_held.py`):
a held call appears as one of SEVEN strings — `COMPLETED`, `COMPLETE - QUALIFIED`,
`COMPLETE - FUTURE`, `COMPLETE - DISQUALIFIED`, `COMPLETE - SEND CONTRACT`,
`COMPLETED - SEND CONTRACT`, `COMPLETED - DISQUALIFIED`. ALL start with `COMPLETE`.
No held outcome lacks the `COMPLETE` prefix. The existing `startswith("COMPLETE")`
predicate therefore already captures every held call (including disqualified-but-held,
which counts as completed because the prospect showed). **Decision: held = any
`COMPLETE*`. No code change to outcome detection; this is documented as verified.**

### DTI discovery calls = standard discovery matcher, DTI contacts only

The probe also showed DTI/device intro calls logged under their own activity types
(`DTI Intro Call`, `TheraRay Intro Call`, `HydroWave Intro Call`,
`Device Profit Map Discovery Call`). **Decision (Kurt): the DTI 15-min rows use the
standard discovery matcher only (`"15 min"` / `"protocol mapping"` via
`discovery_mask`), filtered to TheraRay OR NLAP group contacts. The intro/device
activity types are NOT counted.**

## New rows (added to weekly_metrics, _METRIC_LABELS, METRICS_GOALS)

| metric_id | Label | Definition | Goal |
|---|---|---|---|
| `theraray_submissions` | DTI (TheraRay Leads) | contacts in TheraRay group (HubSpot list 6280) whose submission/membership date falls in the week | ≥ 0 |
| `nlap_submissions` | DTI (NLAP Leads) | contacts in NLAP group (HubSpot list 7086) whose submission/membership date falls in the week | ≥ 15 |
| `dti_15min_scheduled` | DTI 15 Min Call Scheduled | discovery meetings (`discovery_mask`) booked in the week for contacts whose group is TheraRay OR NLAP | ≥ 2 |
| `dti_discovery_completed` | DTI Discovery Calls Completed | the `dti_15min_scheduled` subset with a `COMPLETE*` outcome | ≥ 5 |
| `bofu_submissions_direct` | BOFU Submissions (DIRECT) | BOFU submissions in the week whose `email` matches NO contact carrying a webinar registration (`webinar_registration_date` or `pt_webinar_registration_date`); i.e. the lead skipped the webinar funnel | ≥ 0 |

### Goals adopted on existing rows (to match Ninety)

- `webinar_registrations` ≥ 12, `webinar_completions` ≥ 8
- `fifteen_min_scheduled` ≥ 30, `fifteen_min_completed` ≥ 20
- `strategy_calls_total` ≥ 15, `strategy_calls_completed` ≥ 10
- `new_total_customers` ≥ 5
- Chiro rows, `bofu_submissions_total`, ad-spend/clicks/CPC rows stay ≥ 0.

### Label cleanup

Existing FB-based `theraray_leads` row → relabel to "TheraRay - FB Leads" so it is not
confused with the new list-based "DTI (TheraRay Leads)" row. (Superset keeps both: one
is FB-reported leads, one is HubSpot list submissions.)

## Components / data flow

1. **`metrics.py` render** — before calling `weekly_metrics`, merge TheraRay (6280) and
   NLAP (7086) list memberships into the `contacts` frame via the existing
   `merge_list_group()` so those contacts carry the TheraRay/NLAP `group` tag and a
   submission date. (Confirm whether the render already merges these; add if missing.)
   This is what makes both the submission counts and the DTI call group-filter work
   without new `weekly_metrics` params.
2. **`weekly_metrics()`** — add the 5 new metric_ids to the per-metric build loop:
   - `theraray_submissions` / `nlap_submissions`: count contacts with `group` ==
     TheraRay / NLAP and submission date in week (mirrors `chiro_new_leads` shape).
   - `dti_15min_scheduled` / `dti_discovery_completed`: a discovery-meeting count
     filtered to contacts whose `group` ∈ {TheraRay, NLAP}; completed variant adds the
     `COMPLETE*` outcome filter. Reuse / extend the existing group-aware meeting helper
     (`_meetings_count_group`) to accept the TheraRay+NLAP set and use `discovery_mask`.
   - `bofu_submissions_direct`: of the BOFU submissions in week, count those whose
     `email` is not in the set of contact emails that have any webinar registration.
3. **`_METRIC_LABELS`** — add the 5 labels; relabel `theraray_leads`.
4. **`config.METRICS_GOALS`** — add goals for the 5 new ids; update the existing-row
   goals listed above.

## Error handling / edge cases

- Empty frames (no BOFU submissions, no memberships, no meetings) → 0 for the week
  (existing helpers already guard `.empty`).
- A contact in both TheraRay and NLAP groups (unlikely) is counted once per DTI-call
  metric (set-based contact membership), avoiding double-count.
- BOFU submission email not matching any contact → treated as DIRECT (no webinar
  record). This is the intended "skipped the webinar" semantics; the verification probe
  will confirm the count matches Ninety and the rule is refined if not.
- Week bucketing and ordering unchanged (Mon-Sun, oldest-first) — already compatible.

## Verification (the explicit "verify this information" deliverable)

After implementation, run a probe that computes `weekly_metrics()` for the weeks shown
in the screenshot and diffs every cell against the transcribed Ninety values. Output a
per-metric match/mismatch table. Where a mismatch reveals a definition gap (notably the
Chiro "Lead Magnet Opt-Ins" source — FB leads vs typeform submissions — and the exact
DIRECT-BOFU rule), refine the dashboard definition to match reality and report what
Ninety had wrong vs what the dashboard computes. Present results to Kurt before final push.

## Testing

`weekly_metrics()` is pure → each new row gets TDD unit tests with synthetic frames
(mirroring `dashboard/tests/test_reconcile.py` / `test_daily_summary.py`):
- TheraRay/NLAP submission counts by week from group + submission date.
- DTI 15-min scheduled/completed: TheraRay+NLAP contacts only; completed filters
  `COMPLETE*`; non-DTI contacts excluded; intro/device activity types excluded.
- BOFU DIRECT: submission with webinar-registered email excluded; submission with
  no-webinar email or unknown email counted; TOTAL unchanged.
- Goal values surface correctly for new + updated rows.

## Out of scope

- Reshaping the grid to 1:1 with Ninety (superset chosen).
- Counting intro/device activity types as DTI discovery calls (Kurt: only 15-min).
- Any change to held/completed outcome detection (verified already correct).
- A separate scorecard view or any new tab.
