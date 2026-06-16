# Plan B — Appointment-Outcome Funnel (Callum)

Spec: `docs/superpowers/specs/2026-06-16-callum-sales-reporting-review.md` (item A5/A6,
decision D3). Follows Plan A (`2026-06-16-callum-plan-a-rep-sales.md`, shipped `eb367f6`).

## Goal

Give Callum a per-stage, per-rep outcome funnel so he can find bottlenecks by person
and by stage. For **SME (strategy) calls first**, then mirror onto **discovery (BDS)**:

```
Scheduled -> No-Show -> Cancelled (by BPA / by Prospect) -> Rescheduled -> Showed -> Sales
```

with Show %, No-Show %, Cancel % per **team** (TOTAL row) and per **individual rep**.

## Locked decisions (already agreed)

- **D3:** SME strategy outcome funnel first, then discovery.
- Cancel by-whom split shown where populated (**strategy** populates `CANCELLED - BY BPA`
  / `CANCELLED - BY PROSPECT`); discovery shows a **single Cancelled** (its by-whom split
  is sparse — mostly generic `CANCELED`).
- Money/Sales unchanged from Plan A: `deal.amount` via `rep_sales_rollup` (do NOT touch).

## Confirmed `hs_meeting_outcome` values (probe)

Upper-cased, stripped:
- `NO_SHOW` -> No-Show
- `CANCELLED - BY BPA` -> Cancel (BPA)  [starts with `CANCEL`, contains `BPA`]
- `CANCELLED - BY PROSPECT` -> Cancel (Prospect)  [starts with `CANCEL`, contains `PROSPECT`]
- `CANCELED` (generic/legacy) -> counted in total cancels only (drives Cancel %)
- `RESCHEDULED`, `RESCHEDULED - HAS BOFU`, `RESCHEDULED - NO BOFU` -> Rescheduled
- `COMPLETE*` -> Showed (held)

Note: both BPA and PROSPECT cancels start with `CANCEL`, so a single
`startswith("CANCEL")` captures **all** cancels; we split that bucket for the two
displayed columns and use the total for Cancel %.

## Pattern to mirror

The BDS Discovery funnel already does exactly this shape: `sales_bds_rollup` takes a
windowed all-outcomes frame `meetings_all` (= `meetings_win_all` in `sales.py`) for the
funnel-entry columns (`appointments`/`canceled`/`rescheduled`) and the cleaned `meetings`
for `shows`/conversions. Plan B extends that pattern to the strategy/SME side and adds a
`no_show` column to both.

`meetings_win_all` is already built at `sales.py:241` and already passed to
`sales_bds_rollup` at `sales.py:983`. SME just needs the same frame passed in.

---

## Task 1 — `sales_sme_rollup`: add `meetings_all` + outcome columns (TDD)

File: `dashboard/data/reconcile.py` (`sales_sme_rollup`, ~line 1286).

**Signature:** add keyword param `meetings_all: pd.DataFrame | None = None` after
`stages_strategy_dq`.

**New funnel-entry sets** (mirror the BDS block at `reconcile.py:1239-1256`), computed from
the all-outcomes **strategy** frame when `meetings_all` is provided, else fall back to the
cleaned booked set so existing callers are unchanged:

```python
sched_strat_ids: set = set()
no_show_ids: set = set()
canceled_ids: set = set()          # ALL cancels -> drives cancel_rate
canceled_bpa_ids: set = set()
canceled_prospect_ids: set = set()
rescheduled_ids: set = set()
if meetings_all is not None and not meetings_all.empty:
    types_a = meetings_all["activity_type"].fillna("").astype(str).str.lower()
    strat_a = meetings_all[types_a.str.contains("strategy", na=False)]
    if not strat_a.empty:
        sched_strat_ids = set(strat_a["contact_id"].astype(str))
        out_a = strat_a["outcome"].fillna("").astype(str).str.upper().str.strip()
        norm = out_a.str.replace("-", " ", regex=False).str.replace("_", " ", regex=False)
        no_show_ids = set(strat_a.loc[norm.str.startswith("NO SHOW"), "contact_id"].astype(str))
        is_cancel = out_a.str.startswith("CANCEL")
        canceled_ids = set(strat_a.loc[is_cancel, "contact_id"].astype(str))
        canceled_bpa_ids = set(strat_a.loc[is_cancel & out_a.str.contains("BPA"), "contact_id"].astype(str))
        canceled_prospect_ids = set(strat_a.loc[is_cancel & out_a.str.contains("PROSPECT"), "contact_id"].astype(str))
        rescheduled_ids = set(strat_a.loc[out_a.str.startswith("RESCHEDULED"), "contact_id"].astype(str))
else:
    sched_strat_ids = booked_strat_ids   # cleaned booked = best available fallback
```

**Row loop** — add per group (`cids`):
```python
sched   = len(cids & sched_strat_ids)
no_show = len(cids & no_show_ids)
c_bpa   = len(cids & canceled_bpa_ids)
c_pro   = len(cids & canceled_prospect_ids)
c_all   = len(cids & canceled_ids)
resched = len(cids & rescheduled_ids)
```

**New columns** (append to `cols` so existing positions are unchanged):
`scheduled`, `no_show`, `canceled_bpa`, `canceled_prospect`, `canceled`,
`rescheduled`, `no_show_rate`, `cancel_rate`, `reschedule_rate`.

Rates: `no_show_rate=_safe_div(no_show, sched)`, `cancel_rate=_safe_div(c_all, sched)`,
`reschedule_rate=_safe_div(resched, sched)`.

**Redefine `show_rate`** to `_safe_div(showed, sched)`. When `meetings_all is None`,
`sched == booked_strat_ids == appointments`, so this is identical to today (backward
compatible — existing tests that omit `meetings_all` keep passing).

**Tests** (`dashboard/tests/test_sales_rollups.py`):
- New: with a `meetings_all` strategy frame containing one of each outcome, assert
  `scheduled` counts all (incl. dead), `no_show`/`canceled_bpa`/`canceled_prospect`/
  `rescheduled` land in the right rep, `canceled` = total cancels, `cancel_rate` uses the
  total, `show_rate = showed/scheduled`.
- New: a generic `CANCELED` (no BPA/Prospect) counts in `canceled`/`cancel_rate` but not
  in the two split columns.
- Backward-compat: existing call without `meetings_all` -> `scheduled == appointments`,
  `show_rate` unchanged, new count columns all 0.
- Update any existing assertion that pins the exact `cols` list / column set.

Commit: `feat(sales): SME strategy outcome funnel in sales_sme_rollup`.

---

## Task 2 — `sales_bds_rollup`: add `no_show` (TDD)

File: `dashboard/data/reconcile.py` (`sales_bds_rollup`, ~line 1242 block).

In the `meetings_all` discovery block (`fifteen_a`), add:
```python
norm_a = out_a.str.replace("-", " ", regex=False).str.replace("_", " ", regex=False)
no_show_ids = set(fifteen_a.loc[norm_a.str.startswith("NO SHOW"), "contact_id"].astype(str))
```
Add columns `no_show` and `no_show_rate = _safe_div(no_show, appointments)`. Keep the
single `canceled` column (no BPA/Prospect split for discovery, per D3).

Tests: no_show counted from `meetings_all`; `no_show_rate = no_show/appointments`;
backward-compat (no `meetings_all` -> `no_show == 0`). Update exact-column assertions.

Commit: `feat(sales): No-Show column in sales_bds_rollup discovery funnel`.

---

## Task 3 — Render SME Performance funnel (Sales tab)

File: `dashboard/sections/sales.py` (~1116-1180).

- Pass `meetings_all=meetings_win_all` to `sales_sme_rollup`.
- Keep the Plan A block intact: `sales`/`revenue` from `rep_sales_rollup(_win_closed, by="sme")`,
  `(unassigned)` dropped, per-rep `close_rate = sales/showed` recompute.
- `team_total_row`:
  - `sum_cols=["scheduled","no_show","canceled_bpa","canceled_prospect","rescheduled","showed","canceled","sales","revenue"]`
    (include `canceled` so the TOTAL Cancel % is right; it is NOT displayed).
  - `rate_cols={"show_rate":("showed","scheduled"), "no_show_rate":("no_show","scheduled"),
    "cancel_rate":("canceled","scheduled"), "close_rate":("sales","showed")}`.
- `_fmt_pct` on show_rate, no_show_rate, cancel_rate, close_rate; `_fmt_money` on revenue.
- **Drop the DQ / DQ % columns from the SME display** (replaced by the funnel; rollup still
  computes `disqualified`, just not shown here).
- Final display + rename (this exact order):

| SME | Strategy Scheduled | No-Show | Cancel (BPA) | Cancel (Prospect) | Rescheduled | Showed | Show % | No-Show % | Cancel % | Sales | Revenue | Close % |

  rename map keys: `sme_id, scheduled, no_show, canceled_bpa, canceled_prospect,
  rescheduled, showed, show_rate, no_show_rate, cancel_rate, sales, revenue, close_rate`.
- Caption: append a sentence — "Cancel % counts every cancellation; the BPA / Prospect
  columns show those with a recorded source." (no em dashes — use ` - ` / parens).

Spec + code-quality review (read the code, do not trust the report) before commit. Watch
for: hoisting/scope (`_win_closed` already hoisted in Plan A — keep it that way), Styler
row styling must stay `.apply(axis=1)`.

Commit: `feat(sales): SME Performance outcome funnel columns + rates`.

---

## Task 4 — Render BDS Performance No-Show (Sales tab)

File: `dashboard/sections/sales.py` (~988-1032).

- `team_total_row`: add `no_show` to `sum_cols`; add `"no_show_rate":("no_show","appointments")`
  to `rate_cols`.
- `_fmt_pct` on `no_show_rate`.
- Add to rename map: `no_show -> "No-Show"`, `no_show_rate -> "No-Show %"`.
- Add an explicit final column order (BDS block has none today) so No-Show sits after
  Disco Scheduled and No-Show % after Show %:

| BDS | Disco Scheduled | No-Show | Canceled | Rescheduled | Discovery Show | SME Booked | Disqualified | Show % | No-Show % | Booking % | DQ % | Sales Influenced |

Spec + code-quality review before commit.

Commit: `feat(sales): No-Show column in BDS Performance funnel`.

---

## Task 5 — Verify + ship

- `python -m pytest dashboard/tests -q` (all green; was 77 + new Plan B tests).
- Live verify on Streamlit (deploy lag ~1-2 min): screenshot SALES tab, confirm SME funnel
  columns render, TEAM TOTAL row math (Show %/No-Show %/Cancel % from summed cols), BDS
  No-Show column. Sanity-check a rep against HubSpot if a number looks off.
- Push `feature/cmo-dashboard`.

## Out of scope (note, do not build)

- Executive-tab mirror of the SME/BDS outcome funnel (optional follow-up; Sales tab is
  where Callum's per-rep accountability view lives). Do not add unless asked.
- Meeting-level (vs contact-level) counting. Stay contact-set based to match the existing
  BDS funnel and `showed`/`appointments` semantics.
