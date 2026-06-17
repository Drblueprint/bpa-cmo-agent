# Weekly Metrics Definition Gaps — Design

Date: 2026-06-17
Origin: follow-up to the scorecard alignment (`2026-06-17-weekly-metrics-scorecard-alignment`). The live verification diff against the Ninety scorecard surfaced four definition mismatches on EXISTING weekly rows. Kurt gave direction on each; this spec resolves all four.

## Goal

Make four existing Weekly Metrics rows compute what Ninety (and Dr. Gumm) actually mean, and surface cold-outreach calls separately so the call totals are trustworthy and not confused with marketing-sourced calls.

## Context

All changes are in the pure `weekly_metrics()` aggregator (`dashboard/data/reconcile.py`), its `_METRIC_LABELS` registry, `config.METRICS_GOALS`, and the METRICS render (`dashboard/sections/metrics.py`). Weeks are Mon-Sun, 8 back. Group tagging uses `contacts["group"]` from `asset_to_group`; FB rows carry a `group` column. The scorecard-alignment work already merges TheraRay/NLAP list members into `contacts` before the weekly call.

## Gap 1 — Chiro Ad Spend / Link Clicks / CPC = all paid groups

Today `chiro_ad_spend` / `chiro_link_clicks` / `chiro_cpc` sum **Chiro + EMX** only. Ninety's "Chiro" total is **all FB ad spend = Chiro + EMX + TheraRay + NLAP**. Evidence: adding TheraRay made 5 of 7 weeks match Ninety EXACTLY on spend (1 Jun 9363=9363, 11 May 7361=7361, 4 May 7612=7612, 18 May 8494=8494, 25 May ~7212); the 8-14 Jun gap closes once NLAP spend (June onward) is included.

- `chiro_ad_spend` = `_fb_sum` over {Chiro, EMX, TheraRay, NLAP} `spend`.
- `chiro_link_clicks` = `_fb_clicks` over the same four groups.
- `chiro_cpc` = (sum spend) / (sum clicks) over the same four.
- Relabel the three rows from "(incl. EMX)" to "(incl. EMX + DTI)" so the scope is honest.
- Verification will confirm clicks. If clicks still trail Ninety after adding groups, the residual is likely `inline_link_clicks` vs total `clicks`; flag it (do NOT silently switch — that is a separate decision).

## Gap 2 — Lead Magnet Opt-Ins vs New Leads (All-vs-New convention)

Ninety follows the same All-Leads / New-Leads split as the daily VA summary. The dashboard currently has them mis-sourced.

- `chiro_lead_magnet_optins` → **All Leads** = Chiro/EMX contacts with `typeform_submission_date` in the week (today it wrongly uses FB `fb_leads`). Reuse the existing `_contacts_in_group_with_submit` for Chiro + EMX. Matched Ninety exactly (8 Jun 26=26).
- `chiro_new_leads` → **New Leads** = the subset of All Leads whose contact `createdate` is ALSO in the week (net-new to HubSpot), mirroring `daily_va_summary` ([[BPA Daily VA Summary Format]]). New helper `_contacts_in_group_new(group, start, end)` = group AND `_submit_date` in week AND `_created` in week. `weekly_metrics` must parse a `_created` date series from the contacts `created` column (same pattern as `_submit_date`).

## Gap 3 — Webinar Registrations / Completions = the HubSpot property, marketing-filtered

Kurt confirmed the source is the `webinar_registration_date` / `webinar_completed_date` HubSpot properties (the ones the dashboard already reads), filtered to marketing (Chiro/EMX) contacts per his "Chiro/marketing only" decision.

- `webinar_registrations` = contacts with `group` in {Chiro, EMX} AND `_webinar_reg` in week (today counts ALL contacts in the frame).
- `webinar_completions` = same with `_webinar_done`.
- New helper `_contacts_in_groups_property(groups: set[str], prop_col: str, start, end)`.
- `pt_webinar_registrations` / `pt_webinar_completions` are unchanged (separate rows).

**Accepted divergence from Ninety:** this property captures more registrations than the VA manually logged into Ninety, so the dashboard will read HIGHER (8 Jun 8 vs Ninety 2). The HubSpot property is the canonical source — the dashboard is correct and Ninety was under-logged. This is intentional, not a bug.

## Gap 4 — Include all calls; split out cold outreach

Today the weekly call rows only count meetings for marketing-list contacts (the render loads meetings via `load_meetings_for_contacts(marketing ids)`), so calls with non-marketing contacts (cold outreach, referrals not in the frame) are missed, undercounting vs Ninety.

- **Render change:** load all in-window meetings via `load_meetings_in_window(overall_start, overall_end)` instead of `load_meetings_for_contacts(...)`. `meetings` is only consumed by `weekly_metrics` in this render, so this is safe.
- `fifteen_min_scheduled` / `fifteen_min_completed` / `strategy_calls_total` / `strategy_calls_completed` now count ALL such meetings in the window (no branch change — they count whatever frame is passed).
- **Cold-outreach split** (shown in the grid): add 4 rows counting the subset whose meeting `contact_id` is NOT a marketing contact:
  - `fifteen_min_scheduled_cold` "15 Min Scheduled (Cold Outreach)"
  - `fifteen_min_completed_cold` "15 Min Completed (Cold Outreach)"
  - `strategy_calls_total_cold` "Strategy Total (Cold Outreach)"
  - `strategy_calls_completed_cold` "Strategy Completed (Cold Outreach)"
  - Goals 0. New helper `_meetings_count_cold(token, start, end, *, completed_only=False)` = type + window + `contact_id NOT in marketing_ids`, where `marketing_ids = set(contacts["hs_id"].astype(str))` inside `weekly_metrics`. A meeting with a blank/unknown contact counts as cold.
- DTI / TheraRay / PT group-filtered rows are unaffected (they filter to group contacts that are in the frame; counting works against the all-meetings frame too).
- Place each cold row directly under its parent row in `_METRIC_LABELS` so the split reads naturally.

## Components / data flow

1. `metrics.py` render: swap the meetings loader to `load_meetings_in_window`. No other render change (TheraRay/NLAP merge already in place from the prior work).
2. `reconcile.py weekly_metrics`: parse `_created`; add helpers `_contacts_in_group_new`, `_contacts_in_groups_property`, `_meetings_count_cold`; change the Gap-1/2/3 branch bodies; add the 4 cold branches; compute `marketing_ids`.
3. `_METRIC_LABELS`: relabel 3 chiro rows; add 4 cold labels (under their parents).
4. `config.METRICS_GOALS`: add 4 cold goals (0). Existing goals unchanged.

## Error handling / edge cases

- Empty frames → 0 (helpers guard `.empty`, mirroring existing helpers).
- Multi-contact meetings already produce one row per contact in both loaders; counts treat each row — pre-existing behavior, unchanged.
- A meeting whose `contact_id` is blank → counted as cold (unknown = not marketing).
- `_created` / `_webinar_reg` columns: parsed via the existing `_to_date_series` (tolerant of a missing source column).

## Verification

After implementation, re-run the weekly verification probe (compute `weekly_metrics` for the screenshot weeks) and diff vs Ninety:
- Gap 1: Chiro Ad Spend should now match Ninety on the 5 confirmed weeks; report clicks.
- Gap 2: Lead Magnet Opt-Ins should match Ninety (All Leads); New Leads should land near Ninety's lower net-new numbers.
- Gap 3: webinar will read higher than Ninety by design — confirm it equals the Chiro/EMX property count.
- Gap 4: 15-Min and Strategy totals should rise toward Ninety; cold rows should be non-zero where cold outreach happened.
Present the diff to Kurt before pushing.

## Testing

`weekly_metrics` is pure → TDD unit tests in `dashboard/tests/test_weekly_scorecard.py`:
- Gap 1: FB fixture with Chiro+EMX+TheraRay+NLAP rows; assert ad spend / clicks sum all four; CPC = total/total.
- Gap 2: contacts with submit-in-week (counts as opt-in) vs submit+created-in-week (counts as new lead); a returning submitter (submit in week, created earlier) counts as opt-in but NOT new.
- Gap 3: webinar reg/comp counts only Chiro/EMX group contacts; a TheraRay/PT contact with a webinar date is excluded from the generic rows.
- Gap 4: a strategy/15-min meeting whose contact is a marketing lead is NOT in the cold row; one whose contact is unknown/non-marketing IS; totals include both.

## Out of scope

- Changing the held/completed outcome rule (verified correct: `startswith("COMPLETE")`).
- Switching clicks from `inline_link_clicks` to total `clicks` (only if verification shows it is needed — separate decision).
- Re-labeling cold outreach inside the SALES/EXECUTIVE meeting-detail tables (Kurt chose the in-grid split; detail-table labeling is a separate ask if wanted).
- Trying to force the webinar rows to match Ninety's under-logged manual numbers.
