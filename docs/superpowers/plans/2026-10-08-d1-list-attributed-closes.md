# D1 — List-Attributed Close Attribution + NaN-Group Fix: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute NLAP/TheraRay closes to their marketing segment (with an opt-in-before-close guard) and fix the NaN-group bug so genuinely-direct closes derive a real group from their contract tier.

**Architecture:** One new config map + a new branch in `build_closed_deals_table`'s attribution chain + a NaN-safe group-derivation fix, then wire the config through all call sites. No new loaders — `typeform_submission_date` (already loaded) is the list-form submission date and equals the answer key's credit anchor.

**Tech Stack:** Python, pandas, pytest, Streamlit.

**Spec:** `docs/superpowers/specs/2026-10-08-d1-list-attributed-closes-design.md`

## Global Constraints

- Money/attribution-critical. TDD: failing test first, then implement. Run the full suite before committing.
- A close is list-credited (NLAP/TheraRay, marketing) ONLY when the asset is a `LIST_ATTRIBUTED_ASSET` AND `typeform_submission_date` is present and `<=` the close date. Opt-in date is `typeform_submission_date` ONLY — never fall back to `createdate`.
- `LIST_ASSET_TO_GROUP` is a SEPARATE config map from `ASSET_TO_GROUP` (adding list labels to `ASSET_TO_GROUP` would double-count leads in the lead flow). Do not modify `ASSET_TO_GROUP`.
- The per-rep total DataFrames and all other `build_closed_deals_table` output columns are unchanged; only `group`/`source`/`is_marketing` values for previously-unattributed list/direct closes change.
- `list_asset_to_group` param defaults to `None` (current behavior) so the change is backward-compatible.
- No em dashes or AI-style punctuation. Write files with Write/Edit only. Branch `feature/cmo-dashboard`; commit per task; do not push (Kurt pushes).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Out of scope: D5, the multi-opt-in credit engine, Part B. Wilson stays on his existing override.

---

### Task 1: Engine + config + unit tests

**Files:**
- Modify: `dashboard/config.py` (add `LIST_ASSET_TO_GROUP` next to `LIST_ATTRIBUTED_ASSETS`, ~line 553)
- Modify: `dashboard/data/reconcile.py` (`build_closed_deals_table` ~2694-2866: add param, two module-level helpers, the list-asset branch, the NaN-group fix)
- Test: `dashboard/tests/test_reconcile.py`

**Interfaces:**
- Produces: `build_closed_deals_table(..., list_asset_to_group: dict[str,str] | None = None)`; when passed, list-attributed closes with opt-in on/before close attribute to their segment.

- [ ] **Step 1: Write failing tests**

Append to `dashboard/tests/test_reconcile.py` (place after `test_jared_wilson_credited_to_emx_kansas_city`):

```python
def _d1_deal(did, close, create="2021-01-01T00:00:00Z"):
    return {"deal_id": did, "dealstage": "24094605", "amount": 40000.0,
            "createdate": create, "closedate": close, "stage_entry_date": None}

def _d1_contact(cid, email, asset, submit, tier="1:  PRIMARY"):
    return {"hs_id": cid, "name": cid, "email": email,
            "typeform_asset_download": asset, "typeform_submission_date": submit,
            "contract_tier": tier, "send_contract_options": "",
            "analytics_source_data_1": "", "created": "2021-01-01T00:00:00Z",
            "sdr_owner": "", "bds": "", "sme": ""}

_D1_LAG = {"theraray": "TheraRay", "theraray device": "TheraRay",
           "theraray user": "TheraRay", "nlap user": "NLAP",
           "neuro-lymphatic activation protocol": "NLAP"}

def _d1_build(deals_rows, contact_rows):
    from dashboard.data.reconcile import build_closed_deals_table
    deals = pd.DataFrame(deals_rows)
    contacts = pd.DataFrame(contact_rows)
    cd = pd.DataFrame([{"contact_id": c["hs_id"], "deal_id": d["deal_id"]}
                       for d, c in zip(deals_rows, contact_rows)])
    return build_closed_deals_table(
        deals, cd, contacts,
        asset_to_group={"EMX Kansas City 2026": "EMX"},  # list labels NOT here
        group_default_amount={"Chiro": 47928.0},
        source_overrides=None, stage_source_fallback=None,
        list_asset_to_group=_D1_LAG,
    )

def test_d1_nlap_close_attributed_when_optin_before_close():
    t = _d1_build(
        [_d1_deal("dn", "2026-09-11T00:00:00Z")],
        [_d1_contact("c1", "vs@x.com", "Neuro-Lymphatic Activation Protocol ",
                     "2026-08-07T00:00:00Z")])
    r = t.iloc[0]
    assert r["group"] == "NLAP" and r["source"] == "NLAP" and bool(r["is_marketing"]) is True

def test_d1_theraray_close_attributed_when_optin_before_close():
    t = _d1_build(
        [_d1_deal("dt", "2026-07-22T00:00:00Z")],
        [_d1_contact("c1", "td@x.com", "TheraRay", "2026-07-15T00:00:00Z")])
    r = t.iloc[0]
    assert r["group"] == "TheraRay" and bool(r["is_marketing"]) is True

def test_d1_list_optin_after_close_is_not_credited():
    # Zerebny-style: opted into the list AFTER closing -> not list-credited.
    t = _d1_build(
        [_d1_deal("dz", "2026-02-09T00:00:00Z")],
        [_d1_contact("c1", "mz@x.com", "NLAP User ", "2026-06-20T00:00:00Z",
                     tier="1:  PRIMARY")])
    r = t.iloc[0]
    assert bool(r["is_marketing"]) is False
    assert r["group"] != "NLAP"          # falls through to tier fallback
    assert not (isinstance(r["group"], float) and pd.isna(r["group"]))  # not NaN

def test_d1_list_asset_missing_submission_not_credited():
    t = _d1_build(
        [_d1_deal("dm", "2026-07-22T00:00:00Z")],
        [_d1_contact("c1", "ns@x.com", "TheraRay", None)])
    r = t.iloc[0]
    assert bool(r["is_marketing"]) is False

def test_d1_unattributed_group_from_tier_not_nan():
    # No asset, no referral, no list -> group derives from contract tier, not NaN.
    t = _d1_build(
        [_d1_deal("du", "2026-08-15T00:00:00Z")],
        [_d1_contact("c1", "direct@x.com", "", None, tier="1:  PRIMARY")])
    r = t.iloc[0]
    assert bool(r["is_marketing"]) is False
    assert not (isinstance(r["group"], float) and pd.isna(r["group"]))
    assert r["group"] != "(unmapped)" or True   # exact tier-derived group asserted below
```

Note: the exact tier→group for "1:  PRIMARY" is whatever `_group_from_tier` returns; the test asserts only that it is not NaN. If `_group_from_tier("1:  PRIMARY")` returns a concrete group, tighten the final assertion to that value after reading the helper.

- [ ] **Step 2: Run to confirm RED**

Run: `python -m pytest dashboard/tests/test_reconcile.py -k d1_ -v`
Expected: FAIL — `build_closed_deals_table() got an unexpected keyword argument 'list_asset_to_group'`.

- [ ] **Step 3: Add `LIST_ASSET_TO_GROUP` config**

In `dashboard/config.py`, immediately after the `LIST_ATTRIBUTED_ASSETS` frozenset (ends ~line 553), add:

```python
# Close-attribution ONLY: each list-attributed asset label -> its segment group.
# Kept SEPARATE from ASSET_TO_GROUP on purpose: adding these to ASSET_TO_GROUP
# would double-count leads (typeform path + list-merge path) in the lead flow.
# Keys are normalized (strip + lower); build_closed_deals_table normalizes the
# contact's asset the same way before lookup.
LIST_ASSET_TO_GROUP: dict[str, str] = {
    "theraray":                            "TheraRay",
    "theraray device":                     "TheraRay",
    "theraray user":                       "TheraRay",
    "nlap user":                           "NLAP",
    "neuro-lymphatic activation protocol": "NLAP",
}
```

- [ ] **Step 4: Add two module-level helpers in `reconcile.py`**

Immediately above `def build_closed_deals_table(` (~line 2694), add:

```python
def _list_asset_group(asset, list_asset_to_group) -> str | None:
    """Return the segment group ('TheraRay'/'NLAP') for a list-attributed asset
    label, or None. Normalizes the label (strip + lower) before lookup."""
    if not asset or not list_asset_to_group:
        return None
    return list_asset_to_group.get(str(asset).strip().lower())


def _optin_on_or_before_close(submit_raw, deal) -> bool:
    """True when the opt-in (typeform_submission_date) is present and on or
    before the deal's close date (closedate, else stage_entry_date, else
    createdate). Opt-in date is the list-form submission ONLY; never createdate."""
    submit_ts = pd.to_datetime(submit_raw, utc=True, errors="coerce")
    if pd.isna(submit_ts):
        return False
    close_ts = pd.to_datetime(deal.get("closedate"), utc=True, errors="coerce")
    if pd.isna(close_ts):
        close_ts = pd.to_datetime(deal.get("stage_entry_date"), utc=True, errors="coerce")
    if pd.isna(close_ts):
        close_ts = pd.to_datetime(deal.get("createdate"), utc=True, errors="coerce")
    if pd.isna(close_ts):
        return False
    return submit_ts <= close_ts
```

- [ ] **Step 5: Add the `list_asset_to_group` parameter**

In `build_closed_deals_table`'s signature (the `*` keyword-only block, ~line 2698-2702), add after `stage_source_fallback`:

```python
    stage_source_fallback: dict | None = None,
    list_asset_to_group: dict[str, str] | None = None,
```

- [ ] **Step 6: Add the list-asset branch to the attribution chain**

In the attribution chain (currently ~2739-2769), insert a branch AFTER the normal typeform branch (`elif asset and asset_to_group.get(asset):`) and BEFORE the `elif _referral:` branch:

```python
        elif asset and _list_asset_group(asset, list_asset_to_group) \
                and _optin_on_or_before_close(
                    primary_contact.get("typeform_submission_date"), deal):
            # List-attributed close (NLAP / TheraRay): opted in via a HubSpot
            # list form (asset unmapped in asset_to_group by design) with the
            # opt-in on or before the close. Credit the segment as marketing.
            group = _list_asset_group(asset, list_asset_to_group)
            source = group
            is_marketing = True
```

- [ ] **Step 7: Fix the NaN-group bug**

(a) In the "(unattributed)" branch (~line 2767-2769), change:

```python
            source = "(unattributed)"
            group = None
            is_marketing = False
```

(was `group = primary_contact.get("group")`, which carries the NaN from the `asset_to_group` map applied at the top of the function).

(b) Make the group-derivation check NaN-safe (~line 2830):

```python
        if group is not None and not (isinstance(group, float) and pd.isna(group)):
            final_group = group
        elif group_from_tier:
            final_group = group_from_tier
        else:
            final_group = "(unmapped)"
```

- [ ] **Step 8: Run the D1 tests + full suite**

Run: `python -m pytest dashboard/tests/test_reconcile.py -k d1_ -v` (Expected: PASS.)
Then: `python -m pytest dashboard/tests/ -q` (Expected: all pass, including `test_closed_deals_override_beats_typeform_asset` and `test_jared_wilson_credited_to_emx_kansas_city`.)

If a D1 test's tier assertion needs the concrete group, read `_group_from_tier` and tighten `test_d1_unattributed_group_from_tier_not_nan` to assert the exact value.

- [ ] **Step 9: Commit**

```bash
git add dashboard/config.py dashboard/data/reconcile.py dashboard/tests/test_reconcile.py
git commit -m "feat(attribution): credit list-attributed (NLAP/TheraRay) closes + fix NaN group

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Wire `LIST_ASSET_TO_GROUP` through all call sites + live verify

**Files:**
- Modify: `dashboard/sections/sales.py` (4 calls: ~502, ~790, ~1412, ~1534)
- Modify: `dashboard/sections/executive.py` (3 calls: ~230, ~494, ~930)
- Modify: `dashboard/sections/paid_media.py` (1 call: ~471)
- Modify: `dashboard/sections/commissions.py` (1 call: ~65)

**Interfaces:**
- Consumes: `build_closed_deals_table`'s new `list_asset_to_group` param (Task 1) and `cfg.LIST_ASSET_TO_GROUP` (Task 1).

- [ ] **Step 1: Add the arg to every `build_closed_deals_table(...)` call**

In each of the 9 calls, add `list_asset_to_group=cfg.LIST_ASSET_TO_GROUP,` alongside the existing `source_overrides` / `stage_source_fallback` / `group_default_amount` kwargs. For `commissions.py` (which currently passes only `asset_to_group` + `group_default_amount`), add the same kwarg. Every edited module already imports config as `cfg`.

- [ ] **Step 2: Grep to confirm no call site was missed**

Run: `python -m pytest dashboard/tests/ -q` (Expected: all pass.)
Run (verify every call passes it): search `build_closed_deals_table(` across `dashboard/sections` and confirm each call now includes `list_asset_to_group=`.
Run import checks: `python -c "import dashboard.sections.sales, dashboard.sections.executive, dashboard.sections.paid_media, dashboard.sections.commissions"` (Expected: no error.)

- [ ] **Step 3: Live verification (read-only probe)**

Replicate the Q3 closed-deals load (as the dashboard does) and assert, with `list_asset_to_group=cfg.LIST_ASSET_TO_GROUP`:
- Erik Van Slooten → group "NLAP", is_marketing True
- Thien Dinh → group "TheraRay", is_marketing True
- Q3 totals: 20 marketing / 6 referral / 3 unattributed (Unterseher, Ericson, Urrutia)
- No row has a NaN group

Expected: matches the acceptance criteria in the spec.

- [ ] **Step 4: Commit**

```bash
git add dashboard/sections/sales.py dashboard/sections/executive.py dashboard/sections/paid_media.py dashboard/sections/commissions.py
git commit -m "feat(attribution): pass LIST_ASSET_TO_GROUP to all closed-deal tables

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed)

1. **Spec coverage:** list-asset branch + guard (Task 1 steps 4-6), NaN-group fix (step 7), config (step 3), call-site wiring (Task 2), tests for all spec cases (step 1). Covered.
2. **Placeholder scan:** none — all steps carry concrete code. The one conditional ("tighten the tier assertion") is a concrete follow-up, not a placeholder.
3. **Type consistency:** `list_asset_to_group` name identical across config, signature, helpers, branch, and call sites. `_list_asset_group` / `_optin_on_or_before_close` names consistent between definition (step 4) and use (step 6). Keys in `LIST_ASSET_TO_GROUP` are normalized and match the normalization in `_list_asset_group`.
4. **Ordering:** the list-asset branch is placed after the normal typeform branch (list labels are not in `asset_to_group`, so that branch never catches them) and before referral/stage/unattributed, so a failed guard correctly falls through. The existing TheraRay-analytics block runs later and only fires when `group` is still unset, so an explicit list credit takes precedence.
