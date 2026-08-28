# MAP Group Reporting — Design Spec

**Date:** 2026-08-28
**Author:** Kurt + Claude
**Status:** Approved for planning

## Problem

MAP (the "Movement Activation Protocol" Facebook offer, campaigns named "MAP
Protocol") is wired into the data-mapping layer but never reached the display or
reporting layer. As a result MAP leads and MAP ad spend are invisible in the
main dashboard tabs and the reports.

What already works (no change needed):
- FB spend: `fb_loader.load_fb_insights` tags each campaign via
  `groups.match_group`, and the MAP pattern (`\bMAP Protocol\b`) is registered in
  `config.CAMPAIGN_GROUP_PATTERNS`. MAP campaign spend is already grouped as
  "MAP" at the data layer.
- Leads: `config.ASSET_TO_GROUP` maps the typeform asset
  `"Movement Activation Protocol "` (trailing space intentional) to "MAP".

What is missing: every surface that hardcodes the group set omits MAP —
`executive.py` `preferred` list, the `metrics.py` daily-summary blocks, and the
`reconcile.weekly_metrics` metric registry.

MAP is **asset-based** (typeform asset + FB campaign), like Chiro / EMX / PGW.
It is NOT list-based like TheraRay / NLAP, so it needs no HubSpot-list loader.

## Decisions (locked)

1. **Surfaces:** all four — EXECUTIVE tab, METRICS tab, Daily VA Summary, Weekly
   Metrics scorecard.
2. **Rollup:** MAP is a **standalone** group everywhere (its own row/block). Its
   lead counts are NOT folded into Chiro's lead/opt-in rows.
3. **Combined ad-spend line:** MAP spend IS included in the weekly scorecard's
   combined `chiro_ad_spend` line — and, for internal consistency, also in the
   sibling `chiro_link_clicks` and `chiro_cpc` aggregates (so CPC = spend ÷
   clicks over the same group set). This mirrors how TheraRay / NLAP / Workshop
   spend already roll into that combined line despite being standalone groups.
4. **Goals:** MAP weekly goals default to 0 for now (Kurt can supply targets
   later).
5. **SALES tab:** unchanged. It is per-rep sales detail, not group marketing
   spend, so MAP does not belong there.

## Changes by unit

### A. `dashboard/data/reconcile.py` — `daily_va_summary`

Add three return keys, computed from the `contacts` and `fb` frames already
passed in (no new parameter, no new loader):

- `map_submissions` — count of contacts whose `typeform_asset_download` maps to
  group "MAP" and whose `typeform_submission_date` falls in `[start, end]`.
  (Same "All Leads" signal the Chiro block uses, scoped to the MAP group.)
- `map_ad_spend` — sum of FB `spend` rows where `group == "MAP"` and
  `date_start` in `[start, end]`.
- `map_cpl` — `map_ad_spend / map_submissions` if submissions else `None`.

MAP is standalone: the existing `chiro_mask` stays `["Chiro", "EMX"]` and MUST
NOT include MAP.

### B. `dashboard/data/reconcile.py` — `weekly_metrics` + `_METRIC_LABELS`

Add two metric rows to `_METRIC_LABELS` (placed after the EMX / PGW rows so the
chiro-side groups stay together):

- `"map_ad_spend": "MAP - Ad Spend"` → `_fb_sum("MAP", "spend", ws, we)`
- `"map_leads": "MAP - Leads"` → `_contacts_in_group_with_submit("MAP", ws, we)`

Include MAP in the three combined chiro-side aggregates:

- `chiro_ad_spend`: add `+ _fb_sum("MAP", "spend", ws, we)`
- `chiro_link_clicks`: add `+ _fb_clicks("MAP", ws, we)`
- `chiro_cpc`: add MAP to BOTH the spend numerator and the clicks denominator.

Update those three labels to append " + MAP", e.g.
`"Chiro - Ad Spend (incl. EMX + DTI + Workshop + MAP)"`.

### C. `dashboard/sections/executive.py`

Add `"MAP"` to the `preferred` group list (line ~338):
`["Chiro", "EMX", "Practice Growth Workshop", "PT Recovery", "TheraRay", "NLAP", "MAP"]`.
The "Breakdown by group" and "Conversions by group" tables are data-driven via
`group_marketing_metrics` (groups derived from the FB + contacts data), so MAP's
spend + leads row surfaces automatically once it is in the ordering list.

### D. `dashboard/sections/metrics.py`

- `_render_daily_summary`: add a **MAP** block (Submissions / Ad Spend / Cost per
  Submission) to both the MTD card column and the Yesterday card column, placed
  after the NLAP block, using `mtd["map_submissions"]`, `mtd["map_ad_spend"]`,
  `mtd["map_cpl"]` (and the `yday` equivalents). Mirror the TheraRay / NLAP card
  layout exactly.
- Copy-pastable text block: append a MAP section after NLAP, matching the
  existing "Submissions / AD Spent / Cost per Submission" text format.
- `_money_metric_ids()`: add `"map_ad_spend"` so the weekly-scorecard row formats
  as whole dollars.

## Testing (TDD)

Write failing tests first, then implement.

- `test_daily_summary.py`: MAP fixture (a MAP-asset contact submitting in window
  + a MAP FB spend row) → assert `map_submissions`, `map_ad_spend`, `map_cpl`.
  Assert MAP does NOT leak into `chiro_all_leads` / `chiro_spend`.
- `test_weekly_scorecard.py`: fixture with a MAP spend + MAP submission row →
  assert `map_ad_spend` and `map_leads` rows exist with correct values; assert
  the combined `chiro_ad_spend` now includes the MAP spend; assert `chiro_cpc`
  denominator includes MAP clicks.
- Existing tests stay green: their fixtures carry no MAP data, so the combined
  totals (e.g. `chiro_ad_spend == 200.0`) do not move. Update any test that
  asserts the exact `chiro_ad_spend` / `chiro_link_clicks` / `chiro_cpc` label
  text to the new "+ MAP" label.

## Out of scope

- MAP revenue / CAC modeling (MAP closes, if any, already flow through
  `deal.amount`; not part of this leads+spend request).
- MAP weekly goal targets (deferred; default 0).
- SALES tab.
