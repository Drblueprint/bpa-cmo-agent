# Sales Tab Redesign - Design Spec

Date: 2026-06-09
Status: Approved (pending spec review)
Author: Kurt + Claude

## Purpose

Rework the Sales tab so Dr. Gumm can read team performance at a glance and so
the money numbers are correct. Two problems drive this:

1. **Revenue and cash collected are wrong.** They are built on HubSpot's deal
   `amount` field, which is a flat **$40,000 placeholder** on 51 of 57
   closed-won deals YTD. It has no relationship to the actual contract tier.
2. **The tab is hard to skim.** Per-rep tables with no team rollup, a per-lead
   marketing table he does not use, raw stage IDs, and rates that can exceed
   100%.

## Money model (the core fix)

Delete all use of deal `amount`. Derive every money figure from
`contract_tier` (a HubSpot contact property) instead.

### Pricing (source of truth: Kurt, 2026-06-09)

- **Full / Top tier:** $1,997/mo on a 2-year (24mo) contract = **$47,928** TCV.
- **90-Day:** **$5,991** collected up front (the full 90-day program price).
  If they continue, they move to Full.
- **DIY:** **$997/mo**, month-to-month, no fixed term. Tier is updated when a
  doctor leaves the program.
- **PT Recovery = 0.5 x Chiro** for every tier:
  - PT Full: $998.50/mo x 24 = **$23,964** TCV
  - PT 90-Day: **$2,995.50**
  - PT DIY: **$498.50/mo**
- **Basic / "BASIC - NOT CERTIFIED":** excluded from money for now. Listed in
  the roster dropdown only.

### Two distinct money metrics

- **Booked revenue (contract value at close, TCV):**
  - Full = $47,928 (Chiro) / $23,964 (PT)
  - 90-Day = $5,991 / $2,995.50
  - DIY = no TCV (month-to-month). DIY contributes to cash collected and MRR,
    not booked revenue.
- **Est. cash collected (accrued month-by-month):**
  - 90-Day = full one-time amount at close
  - Full = monthly rate x months since close, capped at 24 months
  - DIY = monthly rate x months since close (no cap; only while still active)
  - Always surfaced with the label **"Est. cash collected"** - it is a model,
    not actual billing data.

### contract_tier string mapping

Observed YTD values (match by normalized substring, tiers are messy):

| contract_tier string | Plan | Group |
|---|---|---|
| `1:  PRIMARY` | Full | Chiro |
| `PT - Primary` | Full | PT Recovery |
| `90-DAY - C` | 90-Day | Chiro (PT variant -> PT) |
| `DIY - C` | DIY | Chiro (PT variant -> PT) |
| `BASIC - NOT CERTIFIED` | Basic | excluded |

Implementation: a `TIER_MONEY` config table in `config.py` keyed by a
normalized plan + group, returning `{group, monthly, term_months, one_time,
booked_tcv, is_full, counts_as_money}`. A reconcile helper
`deal_money(tier, closedate, today)` returns `{booked_revenue,
est_cash_collected, monthly, plan, group, is_full}`.

### Upsell handling

When a contact's `contract_tier` flips to PRIMARY while their closed-won deal
still sits in a DIY or 90-Day stage (`1163151789` DIY, `1123458844` 90-Day),
the contact has upgraded to Full.

Detection signal: `tier == PRIMARY` AND `dealstage in {DIY, 90-Day stages}`.

Counting rule (avoids double-count): it is **one deal record** with the tier
flipped, not a second deal. So:
- `# Sales` counts it once.
- Booked revenue and cash use the **current** tier (Full = $47,928 / monthly),
  NOT prior-tier + Full stacked.
- The upsell is surfaced separately as an **"Upsells" count / flag** (e.g. in
  the roster or a small KPI) so Dr. Gumm can see upgrades happened without
  inflating revenue.

Note: Kurt mentioned a "$20k mid-tier upsell." The current data shows no
distinct mid-tier plan (only DIY -> 90-Day -> Full), so the mid-tier concept is
deferred until/if such a plan exists in HubSpot.

### Known data limitations (noted, not blockers)

- **No payment data in HubSpot.** Cash collected is modeled from tier + close
  date. A future pass can swap it for actual collected cash via the connected
  QuickBooks (QBO) integration.
- **No churn date.** When a DIY tier flips away from DIY, we cannot know the
  exact stop date. Cash is counted only for doctors whose tier still indicates
  the active plan; once flipped, accrual stops at "now".
- **No tier-change history in the contact snapshot.** Upsell detection relies
  on the stage-vs-tier mismatch above. A heavier HubSpot property-history pull
  could date the upsell precisely later.

## Tab layout (top -> bottom)

All sections except Upcoming Calls, the Roster, and Closed Deals YTD are bound
to the dashboard date window (MTD by default), filtered by the correct date
field per metric (closedate for money, start_time for meetings, etc.).

### 1. Team Summary (metric cards)

`st.metric` cards: **# Sales**, **Booked Revenue**, **Est. Cash Collected**,
**Avg Time to Close**, **Median Sales Cycle**. Avg deal size is dropped (Kurt:
"less relevant"). Window-bound by closedate.

Coverage note: the other top-level metrics Kurt mentioned (calls booked, show
rate, close rate, total dials) live in the section total rows below, not here,
to avoid duplication.

### 2. SDR Performance

Per-rep table PLUS a **bold "Team Total" row pinned at the top** of the table:
total dials, total pickups, total contacts, talk time, appointments booked,
booking %, speed to lead. Rate cells in the total row are computed from summed
numerators / denominators, not averaged.

### 3. BDS Performance

Per-rep table + pinned **Team Total** row: appointments, shows, SME booked,
booking %, DQ %.

- **Remove `(unassigned)` rows.**
- **Fix the >100% rate bug.** A rate cannot exceed 100%. Root cause is the
  same class fixed on the Executive tab: the numerator set is not a subset of
  the denominator set (e.g. SME-booked counts contacts whose 15-min was never
  marked COMPLETE, so booking % = booked / shows blows past 100%). Fix by
  intersecting the numerator with the denominator (booked-and-showed /
  showed), mirroring `executive_kpis`.

### 4. SME Performance

Per-rep table + pinned **Team Total** row: appointments, shows, closed, first
close, show %, close %, revenue (booked, tier-derived).

- **Remove `(unassigned)` rows.**

### 5. Asset Performance (replaces Marketing Lead Detail)

Drop the per-lead Marketing Lead Detail table. New table, one row per asset
(`typeform_asset_download`): **leads, 15-min booked, strategy booked, closed,
revenue, close %** (close % = closed / leads). Sorted by revenue (then closes)
descending. Window-bound.

### 6. Upcoming Calls

Future-dated meetings (`start_time > now`): contact, owner, type (15-min /
strategy), date/time. Show **all** future calls, but **flag any booked more
than 14 days out in red** as a booking anomaly (reps should never book that far
ahead). Not window-bound (forward-looking). Needs a new loader for future
meetings.

### 7. DIY / 90-Day / Basic Roster (dropdown / expander)

Every doctor currently on a DIY, 90-Day, or Basic plan: name, tier, monthly
rate, months active (since close), running est. cash collected. This is the
"classify the total for those doctors on the DIY and 90-Day plan" request, with
Basic folded in. Current-state, not window-bound.

### 8. Closed Deals YTD

Kept as-is structurally, but the money columns (Deal $, totals) now use the
tier-derived booked revenue instead of the $40k placeholder.

## Components / units

- `config.py`: `TIER_MONEY` map + plan/group normalization for contract_tier.
- `reconcile.py`:
  - `deal_money(tier, closedate, today)` - per-deal booked + est cash.
  - Rewrite `windowed_sales_money` to use `deal_money` (drops amount).
  - Rewrite `build_closed_deals_table` deal_amount to tier-derived booked.
  - Add team-total computation to `sales_sdr_rollup` / `sales_bds_rollup` /
    `sales_sme_rollup` (or compute totals in the section and pin a row).
  - Fix BDS booking-rate numerator (intersection).
  - New `asset_performance_rollup(...)`.
  - New `plan_roster(...)` for DIY/90-Day/Basic.
- `hubspot_loader.py`: `load_upcoming_meetings(...)` for future calls. Ensure
  `contract_tier` is loaded for closed-deal contacts (already in closed-deals
  contacts? verify; add if missing).
- `sections/sales.py`: restructure render order; pinned total rows; drop
  Marketing Lead Detail; add Asset Performance, Upcoming Calls, Roster.

## Testing

- Unit tests in `dashboard/tests` for `deal_money` (each tier, PT halving,
  90-Day one-time, Full cap at 24mo, DIY accrual, upsell).
- Test team-total rows aggregate correctly (rates from summed num/denom).
- Test BDS booking % never exceeds 100%.
- Test asset_performance_rollup and plan_roster shapes.
- Keep existing 50 tests green.

## Out of scope (this pass)

- Actual cash from QuickBooks (future).
- Precise churn / upsell dating via HubSpot property history (future).
- Executive tab (Kurt may request separately).
