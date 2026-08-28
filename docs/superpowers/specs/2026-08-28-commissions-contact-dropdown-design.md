# COMMISSIONS Contact Drill-Down — Design Spec

**Date:** 2026-08-28
**Author:** Kurt + Claude
**Status:** Approved for planning

## Problem

The COMMISSIONS tab shows each SDR / BDS / SME's monthly commission as aggregate
dollar amounts per component. Garrett and Callum need to see WHICH contacts drove
each rep's payout, with clickable HubSpot links, to review and audit commissions.

## Decisions (locked)

1. **Layout:** one `st.expander` per role section (SDR / BDS / SME), placed under
   that role's existing summary table. Each expander holds a detail table:
   **Rep | Contact | Event | Amount | Open (HubSpot link)**, sorted by Rep then
   Amount (descending). Every row is a single commission line-item (one contact,
   one event).
2. **Scope:** full reconciliation. Each rep's detail rows sum to that rep's total
   in the summary table above. Events per role:
   - SDR: 15-min Call, Strategy Call, Full Close, 90-Day, Conversion
   - BDS: Full Close, 90-Day, Conversion
   - SME: Full Close, 90-Day, Conversion
   - Gerri stays a single `st.metric` (flat $25/close, not a rep breakout) — no
     dropdown.
3. **Drift-proofing:** the detail is emitted from the SAME code path that computes
   the totals, so totals equal the sum of the detail rows by construction (not
   merely by a test). No parallel/duplicated commission logic.

## Architecture

### A. New pure helper `sdr_completion_contacts` (reconcile.py)

```
sdr_completion_contacts(meetings, contacts, start, end) -> pd.DataFrame
```
One row per held 15-min or strategy call in `[start, end]`, columns:
`sdr_owner, contact_id, contact_name, event, temp`
- `event`: "disco" (15-min) | "strategy"
- `temp`: "warm" (contact has a non-empty `typeform_asset_download`) | "cold"
- Held = meeting `outcome` starts with "COMPLETE"; month = meeting `start_time`;
  owner = the contact's `sdr_owner`; rows with an empty `sdr_owner` are dropped
  (same filters the current aggregate uses).
- `contact_name` comes from the contacts frame's `name` column
  (`load_contacts_by_ids` output).

Reimplement the existing `sdr_completions_by_owner` as a thin aggregation
(`groupby`) over `sdr_completion_contacts` so its return value and its test are
unchanged, and there is one source of truth for which calls count. Only
`commissions.py` and the commission tests call `sdr_completions_by_owner`.

### B. `compute_monthly_commissions` also returns `detail` (reconcile.py)

Signature change: the second parameter changes from the aggregate
`sdr_completions: dict` to the per-contact `sdr_call_contacts: pd.DataFrame`
(the `sdr_completion_contacts` output). Return value gains a `detail` key:

```
{"sdr": df, "bds": df, "sme": df, "gerri": {count,total}, "detail": detail_df}
```
`detail_df` columns: `role, rep_id, contact_id, contact_name, event, amount`
where `role` in {"sdr","bds","sme"} and `event` in
{"disco","strategy","full","ninety","conversion"}.

The per-rep total DataFrames (`sdr`/`bds`/`sme`) and the `gerri` dict are
UNCHANGED mathematically. As each amount is accumulated:
- Deal loop (full / 90-day / conversion for SDR, BDS, SME): append a detail row
  using the closed-deals row's `hs_id` (contact_id) and `contact_name`.
- SDR call loop (disco / strategy): iterate the `sdr_call_contacts` rows and, for
  each, add to the SDR total AND append a detail row with that contact's id/name.

Because the detail row is appended right where the total is incremented, for any
role+rep, `sum(detail.amount) == that rep's summary total` by construction.

Only emit a detail row when the rep id is non-empty (mirrors the existing
`_add` guard). Gerri produces no detail rows.

### C. Render (commissions.py)

After each role's summary table (`_show(...)`), render:
```
with st.expander(f"{role} commission detail"):
    <filtered detail table, or a caption if empty>
```
The detail table:
- Filter `res["detail"]` to `role == <this role>`.
- `Rep` = `cfg.resolve_owner(rep_id)`, drop rows where Rep == "(unassigned)".
- `Contact` = `contact_name`.
- `Event` = friendly label via a map:
  disco -> "15-min Call", strategy -> "Strategy Call", full -> "Full Close",
  ninety -> "90-Day", conversion -> "Conversion".
- `Amount` = `_MONEY(amount)`.
- `Open` = `cfg.hubspot_contact_url(contact_id)`, rendered with
  `st.column_config.LinkColumn("Open", display_text="HubSpot ↗")` (the pattern
  used throughout the SALES tab).
- Sort by Rep, then amount descending.
- Empty role detail -> `st.caption("No {role} commission detail this month.")`.

The `compute_monthly_commissions` call site in `render_commissions` changes to
pass `sdr_completion_contacts(...)` instead of `sdr_completions_by_owner(...)`.

## Testing (TDD)

- `sdr_completion_contacts`: one warm 15-min + one cold strategy + one not-held
  (ignored) -> assert exact per-contact rows (owner, contact_id, contact_name,
  event, temp). Assert `sdr_completions_by_owner` still returns the identical
  aggregate over the same fixture (regression).
- `compute_monthly_commissions` detail:
  - A direct full close (warm) + a 90-day->conversion (split months) + SDR calls
    -> assert `detail` contains the expected rows with correct
    (role, rep_id, contact_id, event, amount).
  - **Reconciliation:** for each role and rep present, assert
    `detail[detail.role==r & detail.rep_id==rep].amount.sum()` equals that rep's
    `total` in the corresponding summary DataFrame.
  - DIY close -> no detail rows (Gerri only).
- Render: not unit-tested (Streamlit); verified live.

## Out of scope

- Gerri drill-down (single metric, no rep breakout).
- Any change to the commission rates, stages, or the no-double-pay conversion
  logic (unchanged).
- Per-rep expanders or a rep-selector (layout is per-role expander, decided).
