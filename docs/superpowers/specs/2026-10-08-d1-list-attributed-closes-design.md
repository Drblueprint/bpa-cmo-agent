# D1 — List-Attributed Close Attribution + NaN-Group Fix

**Date:** 2026-10-08
**Author:** Kurt + Claude
**Status:** Approved for planning (pending Kurt's spec review)
**Related:** `project_bpa_attribution_defects_oct2026.md` (defect D1 + NaN-group); Part A. D5 and the multi-opt-in credit engine remain OUT of scope / on hold. Wilson already fixed via `CONTACT_SOURCE_OVERRIDES` (commit 1cf6f87).

## Problem

Closed deals whose contact opted in through a HubSpot list group (NLAP, TheraRay) carry a `typeform_asset_download` that is in `LIST_ATTRIBUTED_ASSETS` — labels left unmapped in `ASSET_TO_GROUP` by design, because in the LEAD flow those groups attribute via list membership, not the typeform map. In `build_closed_deals_table` the attribution chain only maps assets through `ASSET_TO_GROUP`, so these closes fall through to "(unattributed)" and get a `NaN` group. Two bugs compound:

1. **List closes unattributed.** Live Q3: Erik Van Slooten (NLAP) and Thien Dinh (TheraRay) classify as "(unattributed)" instead of their marketing segment. (Jared Wilson was the third; already corrected via an override.)
2. **NaN group blocks the tier fallback.** The "(unattributed)" branch sets `group = primary_contact.get("group")`, which is `NaN`. The later group-derivation check `if group:` treats `NaN` as truthy, so `group_from_tier` (the contract-tier fallback) never runs, and genuinely-direct closes carry a `NaN` group instead of a real revenue bucket.

## Grounding (verified live, 2026-10-08)

- Van Slooten: `typeform_asset_download = "Neuro-Lymphatic Activation Protocol "`, `typeform_submission_date = 2026-08-07`, close 2026-09-11. Answer-key credit anchor = 2026-08-07 (first Q3 list-form submission). Opt-in before close.
- Thien Dinh: `typeform_asset_download = "TheraRay"`, `typeform_submission_date = 2026-07-15`, close 2026-07-22. Answer-key anchor = 2026-07-15. Opt-in before close.
- So `typeform_submission_date` on these contacts equals the list-form submission date and equals the answer key's credit anchor. No new loader is needed; the attribution step uses data `build_closed_deals_table` already receives.
- Matt Zerebny (earlier cohort, not Q3): joined NLAP 2026-06-20 but closed 2026-02-09 — opt-in AFTER close. The before-close guard must exclude this case.

## Decisions (locked)

1. A close is credited to a list segment (NLAP / TheraRay) when the contact's `typeform_asset_download` is a `LIST_ATTRIBUTED_ASSET` **and** `typeform_submission_date` is present and ≤ the close date. Otherwise the close is NOT list-credited and falls through the rest of the chain.
2. The opt-in date for the guard is `typeform_submission_date` only. Do NOT fall back to `createdate` (these are returning contacts created years ago; createdate would pass the guard spuriously and credit a non-opt-in). A list asset with no `typeform_submission_date` falls through (not list-credited).
3. The NaN-group bug is fixed so an unattributed close derives its group from its contract tier (via the existing `_group_from_tier`) instead of `NaN`, while `is_marketing` stays `False`.
4. Multi-opt-in "most recent opt-in before the first closing-cycle meeting" resolution is NOT implemented here. The two Q3 cases each have a single list segment, and the single stamped `typeform_asset_download` already reflects the latest opt-in. The general multi-opt-in rule belongs with the stale-asset work (D2 / Part C).
5. D5 (window Closed Won / Close Rate) stays on hold.

## Architecture

### Change 1 — list-asset attribution branch (`dashboard/data/reconcile.py`, `build_closed_deals_table`)

Add a new config map in `dashboard/config.py` next to `LIST_ATTRIBUTED_ASSETS`:

```python
# Close-attribution ONLY: maps each list-attributed asset label to its segment
# group. Kept separate from ASSET_TO_GROUP on purpose — adding these to
# ASSET_TO_GROUP would double-count leads (typeform path + list-merge path) in
# the lead flow. Compared case-insensitively + whitespace-stripped.
LIST_ASSET_TO_GROUP: dict[str, str] = {
    "theraray": "TheraRay",
    "theraray device": "TheraRay",
    "theraray user": "TheraRay",
    "nlap user": "NLAP",
    "neuro-lymphatic activation protocol": "NLAP",
}
```

`build_closed_deals_table` gains a `list_asset_to_group: dict[str, str] | None = None` parameter (call sites pass `cfg.LIST_ASSET_TO_GROUP`). In the attribution chain, add a branch after the normal typeform-asset branch and before referral:

```python
elif asset and _list_group_for(asset, list_asset_to_group) and _optin_before_close:
    group = _list_group_for(asset, list_asset_to_group)   # "TheraRay" | "NLAP"
    source = group                                        # segment label as source
    is_marketing = True
```

where:
- `_list_group_for(asset, m)` normalizes `asset` (strip + lower) and returns `m.get(normalized)` or `None`.
- `_optin_before_close` is computed in this iteration: parse `typeform_submission_date` and the close date (closedate, else stage_entry_date, else createdate — the same close basis the cycle-days block already uses), and is `True` only when submission is present (not NaT) and `<= close`.

The existing TheraRay-analytics-signal block (`analytics_source_data_1` contains "theraray") stays; it already guards on `not (asset and asset_to_group.get(asset))`, which remains true for list assets, so order it so an explicit list-asset credit takes precedence (list-asset branch sets `group`/`is_marketing` first; the analytics block only fires when `group` is still unset).

### Change 2 — NaN-group fix (`build_closed_deals_table`)

- In the "(unattributed)" branch, set `group = None` instead of `group = primary_contact.get("group")`.
- Harden the group-derivation check so `NaN` is treated as unset: `if group and not (isinstance(group, float) and pd.isna(group)):` → use it; `elif group_from_tier:` → tier; else `"(unmapped)"`. (Defense in depth in case any other branch leaves a NaN group.)

Net: a genuinely-direct close (no asset, no referral, no list, no stage fallback) gets its group from its contract tier and `is_marketing=False`, instead of `NaN`.

## Testing (TDD, `dashboard/tests/`)

- **Van Slooten case:** NLAP asset, submission 8/7, close 9/11 → `group == "NLAP"`, `is_marketing True`, `source == "NLAP"`.
- **Thien Dinh case:** TheraRay asset, submission 7/15, close 7/22 → `group == "TheraRay"`, `is_marketing True`.
- **Before-close guard (Zerebny-style):** NLAP asset, submission 6/20, close 2/09 → NOT list-credited (`is_marketing False`); group from tier.
- **Missing submission date:** list asset, `typeform_submission_date` None → NOT list-credited; falls through.
- **NaN-group fix:** unattributed close (no asset/referral/list) with `contract_tier` that derives Chiro → `group == "Chiro"` (not NaN), `is_marketing False`.
- **Regressions stay green:** `test_closed_deals_override_beats_typeform_asset`, `test_jared_wilson_credited_to_emx_kansas_city`, existing `build_closed_deals_table` tests.
- All `build_closed_deals_table` call sites updated to pass `list_asset_to_group=cfg.LIST_ASSET_TO_GROUP` (sales.py x4, executive.py x3, paid_media.py x1, commissions.py x1). The new param defaults to `None` (current behavior) so any missed call site is safe, but all are updated.

## Acceptance (live, Q3 2026)

- Van Slooten → NLAP (marketing); Thien Dinh → TheraRay (marketing).
- Q3 close attribution: **20 marketing / 6 referral / 3 unattributed** (the three genuine direct bookings: Unterseher, Ericson, Urrutia), matching the answer key.
- No unattributed close carries a `NaN` group.
- Full test suite green.

## Out of scope

- D5 (window Closed Won / Close Rate) — on hold.
- Multi-opt-in "most recent before first call" credit resolution — D2 / Part C.
- Part B (leads from real submissions, MAP unstamped, loader past-window gap, glitch-customer exclusion).
