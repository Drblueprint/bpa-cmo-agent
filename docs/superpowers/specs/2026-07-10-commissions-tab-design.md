# COMMISSIONS Tab — Design

Date: 2026-07-10
Origin: Kurt wants a new COMMISSIONS tab so Garrett and Callum can review each SDR / BDS / SME's monthly commissions (and a flat "Gerri" line). Money-critical: numbers feed payroll.

## Goal

A fourth dashboard tab, COMMISSIONS, with a month picker, showing per-rep monthly commission breakdowns for SDRs, BDSs, SMEs, and Gerri — each commission event priced per the locked matrix below, attributable straight into payroll.

## Locked commission matrix

Tiers (by deal stage): **Full close / "Primary 1"** = dealstage `24094605` or `closedwon`; **90-Day** = `1123458844`; **DIY** = `1163151789`.

**SDR** — warm vs cold (warm = the lead's contact has a non-empty `typeform` / marketing typeform; cold = none). Attributed to the lead's `sdr_owner`:
| Event | Warm | Cold |
|---|---|---|
| 15-min complete (held) | $20 | $100 |
| Strategy complete (held) | $100 | $100 |
| Full close (Primary-1) | $200 | $400 |
| 90-day close | $50 | $100 |
| 90-day → Primary-1 conversion bonus | +$150 | +$300 |

**BDS** — flat, closes only, attributed to `bds`: Full **$300**, 90-day **$50**, conversion bonus **+$250**.

**SME** — flat for ALL groups (no group split), closes only, attributed to `sme`: Full **$2,000**, 90-day **$500**, conversion bonus **+$1,500**.

**Gerri** — flat **$25 × every closed-won deal** in the month (Primary-1, 90-day, AND DIY).

**DIY closes**: $0 to SDR/BDS/SME (not commissionable). Gerri's $25 still applies.

Warm/cold applies to SDR ONLY. BDS/SME/Gerri are flat. 15-min/strategy completions pay SDR only (BDS/SME earn nothing on calls).

## Conversion semantics (no double-pay)

A deal's lifetime pays the full-close amount exactly once, split across the month(s) it happens:
- **Direct full close** (in Primary-1, NO prior 90-day entry): pays the full amount in the month it entered Primary-1.
- **90-day close** (entered 90-Day): pays the 90-day base in the month it entered 90-Day — whether or not it later converts.
- **Conversion** (now in Primary-1 WITH a prior 90-day entry): pays only the **bonus** (full − 90-day base) in the month it entered Primary-1. It does NOT also pay a fresh full close (the 90-day base was already paid earlier).

So: 90-day base (month it entered 90-Day) + conversion bonus (month it entered Primary-1) = the full amount, spread across the two months.

## Monthly attribution dates (which month an event counts in)

- 15-min / strategy complete: the meeting's `start_time` month (held = `outcome` upper startswith "COMPLETE").
- Full close (direct): month it entered Primary-1 = `hs_v2_date_entered_24094605` if present, else `closedate`.
- 90-day close: month it entered 90-Day = `hs_v2_date_entered_1123458844` (falls back to `stage_entry_date`/`createdate`).
- Conversion bonus: month it entered Primary-1 = `hs_v2_date_entered_24094605`.

## What gets built

1. **`config.py` `COMMISSION_RATES`** — a new structured constant encoding the whole matrix (SDR warm/cold per event; BDS/SME/Gerri amounts; tier stage-id sets). Kept SEPARATE from the existing CAC constants (`SDR_CLOSE_COMMISSION`, `SME_CLOSE_COMMISSION`, `BDS_CLOSE_COMMISSION`, `FLAT_CLOSE_COMMISSION`) so the executive CAC number is not disturbed.
2. **Loader change** (`hubspot_loader.py`): add `hs_v2_date_entered_24094605` (Primary-1) and `hs_v2_date_entered_1123458844` (90-Day) to the fetched deal `properties` in `load_closed_deals_in_window` (and `load_deals_in_window`), surfaced as `entered_primary1` + `entered_90day` columns. Additive.
3. **`build_closed_deals_table`**: add `dealstage`, `entered_primary1`, `entered_90day` to the output (values already on the input `deal` rows) so the tab can tier deals + detect conversions.
4. **SDR held-meeting counts by `sdr_owner`** (new helper): count held 15-min + held strategy meetings grouped by the lead's `sdr_owner`, split warm/cold by the contact's typeform, bucketed by meeting month. (Existing rollups only key held meetings to `bds`/`sme`.)
5. **Pure `compute_monthly_commissions(...)`** (reconcile.py): inputs = closed-deals table (with stage/entry-date columns), held-meeting-by-SDR data, the month `(start,end)`, and `COMMISSION_RATES`. Returns per-role, per-rep rows: SDR (15-min, strategy, full, 90-day, conversion, total, warm/cold split), BDS (full, 90-day, conversion, total), SME (same), Gerri (count × $25). Pure + fully TDD-able.
6. **`sections/commissions.py` `render_commissions(start, end)`** + a 4th `st.tabs` entry in `app.py`. A month picker (default = current month) drives it; loads that month's data over a broad-enough range to catch conversions of deals that entered 90-Day earlier; renders SDR / BDS / SME / Gerri tables with per-rep component columns + a monthly total, names via `cfg.resolve_owner`.

## Data flow

month picker -> load closed-won deals (broad range, with stage-entry dates) + held meetings + contacts -> `build_closed_deals_table` (+ dealstage/entry dates) + SDR-held-by-owner counts -> `compute_monthly_commissions(month)` -> per-rep tables. Held meetings drive SDR call commissions; the deals table drives all close/90-day/conversion commissions; Gerri = $25 × month's closed-won count.

## Error handling / edge cases

- Deal in Primary-1 with a prior 90-day entry whose 90-day entry was in a DIFFERENT month: the 90-day base counted in that earlier month, the bonus in the Primary-1 month — never both in the same rep's month total for the same deal.
- Missing `hs_v2_date_entered_*` (e.g., legacy `closedwon` pipeline deals with no v2 stamp): fall back to `closedate` for the full-close month; if a Primary-1 deal has no 90-day stamp, treat as a direct full close (no bonus).
- Unmapped owner id -> `cfg.resolve_owner` shows "(unassigned)"/"(unknown)"; still summed so nothing is silently dropped (surface it, don't hide).
- A close with no `sdr_owner` -> no SDR commission for it (only BDS/SME/Gerri as applicable), matching today's engine.
- DIY closes excluded from SDR/BDS/SME; included in Gerri's count.
- Warm/cold uses the same `typeform`-non-empty signal as the existing engine.

## Testing

`compute_monthly_commissions`, the SDR-held-by-owner helper, and the tier/conversion logic are pure -> TDD in `dashboard/tests/test_commissions.py` (extend the existing file). Cases: each SDR warm + cold event at the right rate; BDS/SME flat closes; a direct full close (full amount, no bonus); a 90-day close (base only); a 90-day → Primary-1 conversion across two months (base in month A, bonus in month B, never double); DIY (SDR/BDS/SME $0, Gerri $25); a deal with no sdr_owner; warm vs cold splitting on typeform. Loader change verified by a smoke probe (both entry-date columns present).

## Out of scope

- Aligning the executive-tab CAC (which still uses the old group-based SME + flat amounts) to the new flat SME commission — flag to Kurt as a follow-up; NOT changed here.
- Base salaries / payroll draws (`SDR_PAYROLL_MONTHLY` etc. stay None); this tab is commissions only.
- Editing/paying commissions from the dashboard (read-only review).
- Trending commissions over time (month picker is point-in-time; a trend view could be a later add).
