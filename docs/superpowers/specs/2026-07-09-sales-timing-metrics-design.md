# Sales Timing Metrics — Design

Date: 2026-07-09
Origin: Callum (Head of Sales) asked for two timing metrics each split into ALL vs PRIME:
- **Speed to Lead** — ALL (all hours/weekends) and PRIME (9-5 Mon-Fri CT only).
- **Avg Time to Close** — ALL (from HubSpot contact createdate) and PRIME (from first discovery-call booking).

First of a two-part effort; the sales **trend charts** are a separate follow-up spec (sequencing decided with Kurt: timing metrics first).

## Goal

Add four sales timing metrics to the SALES tab, point-in-time for the active window, so the sales manager can see responsiveness (Speed to Lead) and cycle length (Time to Close) under both a raw and a business-hours / qualified-anchor lens.

## Decisions (locked with Kurt/Callum)

- **Speed to Lead (All)** = current definition: elapsed minutes from lead-in (typeform_submission_date, createdate fallback) to the first outbound AirCall, raw clock time including nights/weekends.
- **Speed to Lead (Prime)** = same two anchors, but counting only business minutes inside **09:00-17:00 America/Chicago, Mon-Fri**. Weekends + after-hours excluded. Holidays are out of scope (not modeled).
- **Time to Close (All)** = median days from contact **createdate** -> deal close date, over closed-won deals in the window.
- **Time to Close (Prime)** = median days from the contact's **first discovery meeting's booked timestamp** (`hs_createdate` of the earliest 15-min/discovery meeting) -> close date. Verified: HubSpot meetings expose `hs_createdate` and it lands 0-7 days before the call `start_time`, so it is a real booking signal.
- **Average = median** (robust to outliers; the existing `sales_cycle_days` already uses median). Labeled "median" in the UI.
- Point-in-time for the active window now; trending these over time is the follow-up trends spec.

## Current state (verified)

- `compute_speed_to_lead` (reconcile.py:856): lead-in = `typeform_submission_date` (createdate fallback); first contact = earliest OUTBOUND AirCall to the contact's phone after lead-in; returns `speed_to_lead_minutes` (raw). This is the ALL definition — keep it and add PRIME alongside.
- `sales_cycle_days` in `build_closed_deals_table` (reconcile.py:~2522): currently typeform_submission -> close (median). This is NEITHER of Callum's two anchors; it will be superseded by the two new Time-to-Close metrics (createdate / first-discovery). Keep the column for now but the surfaced "Time to Close" metrics use the new definitions.
- Meetings loader (`load_meetings_in_window` / `load_meetings_for_contacts`, hubspot_loader.py) currently fetches `hs_meeting_start_time`, `hs_activity_type`, `hs_meeting_outcome`, `hs_meeting_title` — NOT the create timestamp. Must add `hs_createdate`.

## Components

1. **`business_minutes_between(start_ts, end_ts)` (new pure helper, reconcile.py).** Returns the number of minutes between two UTC instants that fall within 09:00-17:00 America/Chicago on Mon-Fri. Uses `zoneinfo.ZoneInfo("America/Chicago")` so DST is handled. Iterates day-by-day (or computes per-day overlap) clamping to the work window; skips Sat/Sun. Pure + fully unit-testable. This is the engine for Speed to Lead (Prime).

2. **`compute_speed_to_lead(...)` extended** to return BOTH `speed_to_lead_minutes` (All, unchanged) and `speed_to_lead_minutes_prime` (business minutes via the helper) in one pass — same lead-in and first-dial anchors, two elapsed measures.

3. **`sdr_call_activity` / `sales_sdr_rollup`** gain a `median_speed_to_lead_prime_min` alongside the existing `median_speed_to_lead_min`, so the Speed to Lead display shows All + Prime per SDR and team.

4. **`time_to_close(...)` (new pure function, reconcile.py).** Input: the window's closed-won deals joined to their primary contact + that contact's meetings. For each closed deal computes:
   - `days_all` = (close date - contact createdate).days
   - `days_prime` = (close date - earliest discovery-meeting `booked_at`).days (None if the contact has no discovery meeting on record)
   Returns median of each (team-level; optionally by group). Uses the same close-date resolution already in `build_closed_deals_table` (closedate -> stage_entry_date -> createdate fallback).

5. **Meetings loader** adds `hs_createdate` -> a `booked_at` column on the meetings frame (both `load_meetings_in_window` and `load_meetings_for_contacts`). This feeds Time to Close (Prime).

## Display (SALES tab)

- **Speed to Lead section** (sales.py ~557): show median **Speed to Lead (All)** and **(Prime)** — team summary + per-SDR (two columns in the existing per-SDR table). Caption notes Prime = 9-5 Mon-Fri CT business time.
- **Time to Close**: a compact metric row in / next to the "Closed Deals — Year to Date" section showing median **Time to Close (All)** (createdate->close) and **(Prime)** (first discovery booking->close), team-level. Caption defines each anchor and notes "median".

## Error handling / edge cases

- Lead-in or first-dial missing -> speed is NaN (excluded from median), as today.
- Prime speed where lead-in and first-dial are both outside business hours with none between (e.g., booked Sat, called Sun) -> 0 business minutes; keep as 0 (responded within the same non-business span). Document this in the caption.
- Time to Close (Prime) where the closed contact has no discovery meeting -> excluded from the Prime median (counted in All only). Surface the n for each median so a small Prime-n is visible.
- DST boundary days handled by `zoneinfo` (compute per-day in local time).
- Negative deltas (close before anchor, data anomaly) -> excluded from the median.

## Testing

Pure functions -> TDD in `dashboard/tests/`:
- `business_minutes_between`: within-day span; span crossing 5pm and next 9am (one evening + next morning excluded); Fri 4pm -> Mon 10am = 60 + 60 = 120 min; weekend-only span = 0; a full business day = 480; DST-transition week.
- `compute_speed_to_lead`: a fixture where All and Prime differ (lead-in Fri 16:00 CT, first dial Mon 10:00 CT -> All large, Prime = 120 min); missing dial -> NaN both.
- `time_to_close`: deals with known createdate/close and first-discovery `booked_at`; assert median days_all and days_prime; a deal with no discovery meeting -> in All median, excluded from Prime; negative delta excluded.
- Loader change verified by a probe/smoke (booked_at present, before start_time).

## Out of scope

- Trending these metrics over time (the follow-up trends-charts spec; Kurt sequenced timing metrics first).
- Holiday calendars for Prime business hours (weekdays + hours only).
- Reworking the legacy `sales_cycle_days` column (left as-is; the surfaced Time-to-Close uses the new definitions).
