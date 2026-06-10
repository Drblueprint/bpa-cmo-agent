# NLAP Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NLAP as a standalone marketing group - spend from Facebook via the `__NLAP__` campaign token, leads from HubSpot list 7086 - mirroring TheraRay everywhere groups appear.

**Architecture:** Refactor the inline TheraRay list-merge in `executive.py` into a pure, tested `merge_list_group` helper in `data/groups.py`, then call it for both TheraRay and NLAP. Add NLAP to the config group-enumeration points and to the Metrics daily summary. NLAP is lead-gen only ($0 revenue), so no deal/tier/economics wiring.

**Tech Stack:** Python 3, pandas, pytest, Streamlit.

**Spec:** `docs/superpowers/specs/2026-06-10-nlap-group-design.md`

---

### Task 1: Config - `__NLAP__` campaign token + list ID

**Files:**
- Modify: `dashboard/config.py` (`CAMPAIGN_GROUPS` ~line 126-129; `THERARAY_HUBSPOT_LIST_ID` ~line 417)
- Test: `dashboard/tests/test_groups.py` (new)

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_groups.py`:

```python
from dashboard.data.groups import match_group


def test_match_group_nlap():
    assert match_group("DS | __NLAP__ Funnel Setup | CBO | USA | CA") == "NLAP"


def test_match_group_existing_unaffected():
    assert match_group("DS | __Theraray__ Funnel Setup | CBO | USA") == "TheraRay"
    assert match_group("DS | __Chiro__ Mixed Funnel Setup | CBO") == "Chiro"
    assert match_group("DS | EMX 2026 Kansas City Mixed Funnel Setup") == "EMX"
    assert match_group("DS | __NLAP__ but also __Chiro__") == "NLAP" or \
           match_group("DS | __NLAP__ but also __Chiro__") == "Chiro"
```

(The last assertion just documents that NLAP+Chiro co-occurrence resolves to one of them deterministically; NLAP campaigns in practice contain only `__NLAP__`.)

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_groups.py::test_match_group_nlap -q`
Expected: FAIL (`match_group(...) == None`, not "NLAP").

- [ ] **Step 3: Add the NLAP regex to CAMPAIGN_GROUPS**

In `dashboard/config.py`, the current block is:

```python
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",         re.compile(r"__EMX__|\bEMX\b", re.IGNORECASE)),
    ("Chiro",       re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery", re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",    re.compile(r"__Theraray__", re.IGNORECASE)),
]
```

Add the NLAP entry (append at the end - `__NLAP__` cannot collide with the other tokens, so order is irrelevant):

```python
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",         re.compile(r"__EMX__|\bEMX\b", re.IGNORECASE)),
    ("Chiro",       re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery", re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",    re.compile(r"__Theraray__", re.IGNORECASE)),
    ("NLAP",        re.compile(r"__NLAP__", re.IGNORECASE)),
]
```

- [ ] **Step 4: Add the NLAP list-ID constant**

Find `THERARAY_HUBSPOT_LIST_ID: str = "6280"` (grep: `THERARAY_HUBSPOT_LIST_ID`). Add directly below it:

```python
NLAP_HUBSPOT_LIST_ID: str = "7086"  # HubSpot list of NLAP opt-ins (FB lead source)
```

- [ ] **Step 5: Run it, confirm it passes**

Run: `python -m pytest dashboard/tests/test_groups.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/config.py dashboard/tests/test_groups.py
git commit -m "feat: add NLAP campaign token + HubSpot list id"
```

---

### Task 2: `merge_list_group` helper

Extract the TheraRay list-merge logic (currently inline in `executive.py:116-157`) into a pure, testable helper. Loaders are dependency-injected so the helper has no Streamlit/HubSpot dependency.

**Files:**
- Modify: `dashboard/data/groups.py`
- Test: `dashboard/tests/test_groups.py`

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_groups.py`:

```python
import pandas as pd
from datetime import date
from dashboard.data.groups import merge_list_group


def _fake_loaders(memberships_df, contacts_df):
    return (lambda _list_id: memberships_df,
            lambda ids: contacts_df[contacts_df["hs_id"].astype(str).isin([str(i) for i in ids])].copy())


def test_merge_list_group_tags_and_routes():
    memberships = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},  # in window
        {"contact_id": "2", "membership_timestamp": "2026-01-01T00:00:00Z"},  # out of window
    ])
    list_contacts = pd.DataFrame([
        {"hs_id": "1", "email": "a@x.com", "name": "A"},
        {"hs_id": "2", "email": "b@x.com", "name": "B"},
    ])
    existing = pd.DataFrame([{"hs_id": "9", "email": "z@x.com", "name": "Z",
                              "typeform_asset_download": "Top 10 typeform"}])
    a2g = {}
    load_m, load_c = _fake_loaders(memberships, list_contacts)
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group=a2g,
    )
    # only contact 1 (in window) merged + tagged; contact 9 preserved
    assert set(out["hs_id"].astype(str)) == {"1", "9"}
    row1 = out[out["hs_id"].astype(str) == "1"].iloc[0]
    assert row1["typeform_asset_download"] == "NLAP FB Lead"
    assert a2g["NLAP FB Lead"] == "NLAP"


def test_merge_list_group_dedup_keeps_tag():
    """A member already in contacts (untagged) gets the list tag after merge."""
    memberships = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},
    ])
    list_contacts = pd.DataFrame([{"hs_id": "1", "email": "a@x.com", "name": "A"}])
    existing = pd.DataFrame([{"hs_id": "1", "email": "a@x.com", "name": "A",
                              "typeform_asset_download": ""}])
    load_m, load_c = _fake_loaders(memberships, list_contacts)
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group={},
    )
    assert len(out) == 1
    assert out.iloc[0]["typeform_asset_download"] == "NLAP FB Lead"


def test_merge_list_group_no_window_members_noop():
    memberships = pd.DataFrame([
        {"contact_id": "2", "membership_timestamp": "2026-01-01T00:00:00Z"},
    ])
    existing = pd.DataFrame([{"hs_id": "9", "email": "z@x.com",
                              "typeform_asset_download": "Top 10 typeform"}])
    load_m, load_c = _fake_loaders(memberships, pd.DataFrame(columns=["hs_id", "email"]))
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group={},
    )
    assert out.equals(existing)
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_groups.py -q`
Expected: FAIL (`ImportError: cannot import name 'merge_list_group'`).

- [ ] **Step 3: Implement the helper**

Add to `dashboard/data/groups.py` (add `import pandas as pd` at top):

```python
def merge_list_group(
    contacts,
    *,
    list_id,
    asset_label,
    group,
    start,
    end,
    load_memberships,
    load_contacts,
    excluded_emails=frozenset(),
    asset_to_group=None,
):
    """Merge a HubSpot list's in-window members into `contacts`.

    Mirrors the original TheraRay merge: filter `load_memberships(list_id)` to
    membership_timestamp in [start, end], load those contacts via
    `load_contacts(ids)`, drop `excluded_emails`, tag
    typeform_asset_download=asset_label + typeform_submission_date=membership ts,
    register asset_to_group[asset_label]=group (if a dict is passed), concat the
    list rows FIRST then drop_duplicates(subset="hs_id", keep="first") so the tag
    survives, and force-tag the asset on all list-member ids.

    load_memberships(list_id) -> df[contact_id, membership_timestamp].
    load_contacts(list[str])  -> contacts df with hs_id + email columns.
    Returns the merged contacts df (unchanged if no in-window members).
    """
    memberships = load_memberships(list_id)
    if memberships is None or memberships.empty:
        return contacts
    mt = pd.to_datetime(memberships["membership_timestamp"], utc=True, errors="coerce")
    start_ts = pd.Timestamp(year=start.year, month=start.month, day=start.day, tz="UTC")
    end_ts = pd.Timestamp(year=end.year, month=end.month, day=end.day, tz="UTC") + pd.Timedelta(days=1)
    in_window = memberships[(mt >= start_ts) & (mt < end_ts)]
    window_ids = in_window["contact_id"].tolist()
    if not window_ids:
        return contacts
    new_rows = load_contacts(window_ids)
    if new_rows is None or new_rows.empty:
        return contacts
    if excluded_emails:
        new_rows = new_rows[
            ~new_rows["email"].fillna("").str.lower().isin(excluded_emails)
        ].copy()
    if new_rows.empty:
        return contacts
    ts_map = dict(zip(in_window["contact_id"].astype(str),
                      in_window["membership_timestamp"]))
    new_rows = new_rows.copy()
    new_rows["typeform_asset_download"] = asset_label
    new_rows["typeform_submission_date"] = new_rows["hs_id"].astype(str).map(ts_map)
    if asset_to_group is not None:
        asset_to_group[asset_label] = group
    if contacts is None or contacts.empty:
        merged = new_rows
    else:
        merged = pd.concat([new_rows, contacts], ignore_index=True) \
            .drop_duplicates(subset="hs_id", keep="first").reset_index(drop=True)
    _ids = set(new_rows["hs_id"].astype(str))
    _mask = merged["hs_id"].astype(str).isin(_ids)
    merged.loc[_mask, "typeform_asset_download"] = asset_label
    return merged
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `python -m pytest dashboard/tests/test_groups.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add dashboard/data/groups.py dashboard/tests/test_groups.py
git commit -m "feat: add reusable merge_list_group helper"
```

---

### Task 3: Use the helper in executive.py for TheraRay + NLAP

Replace the inline TheraRay merge block with a loop over both list-groups using `merge_list_group`, then refresh contact_deals/meetings once. Add NLAP to the `preferred` groups list.

**Files:**
- Modify: `dashboard/sections/executive.py` (TheraRay merge block ~lines 116-157; `preferred` list ~line 304)

- [ ] **Step 1: Confirm current code**

Run: `grep -n "Merge TheraRay\|load_list_memberships\|preferred = \[\|load_contacts_by_ids\|load_contact_deals\|load_meetings_for_contacts" dashboard/sections/executive.py`
Read the merge block (the `# Merge TheraRay contacts ...` try/except) and confirm the loader names. `load_contacts_by_ids` is imported locally in the closed-deal block above; `load_list_memberships`, `load_contact_deals`, `load_meetings_for_contacts` are module-level imports used by the current block.

- [ ] **Step 2: Replace the TheraRay block**

Replace the entire `# Merge TheraRay contacts (HubSpot list 6280 ...)` try/except (currently ~lines 116-157) with:

```python
    # Merge list-based groups (TheraRay, NLAP): opt-ins captured via a HubSpot
    # list, not a typeform. Spend for these groups comes from FB by campaign
    # name; leads come from the list (FB lead counts are unreliable).
    from dashboard.data.groups import merge_list_group
    from dashboard.data.hubspot_loader import load_contacts_by_ids
    _list_groups = [
        (cfg.THERARAY_HUBSPOT_LIST_ID, "TheraRay FB Lead", "TheraRay"),
        (cfg.NLAP_HUBSPOT_LIST_ID, "NLAP FB Lead", "NLAP"),
    ]
    for _lid, _label, _grp in _list_groups:
        try:
            contacts = merge_list_group(
                contacts, list_id=_lid, asset_label=_label, group=_grp,
                start=start, end=end,
                load_memberships=load_list_memberships,
                load_contacts=load_contacts_by_ids,
                excluded_emails=cfg.MARKETING_EXCLUDED_EMAILS,
                asset_to_group=cfg.ASSET_TO_GROUP,
            )
        except Exception as e:
            st.warning(f"{_grp} merge failed: {e}")
    # Refresh meetings + contact_deals to cover the expanded contact set.
    if not contacts.empty:
        try:
            contact_deals = load_contact_deals(contacts["hs_id"].tolist())
            meetings = load_meetings_for_contacts(
                contacts["hs_id"].tolist(), data_floor_days_back=floor_days)
        except Exception as e:
            st.warning(f"Expanded contact reload failed: {e}")
```

Note: this preserves the original behavior (TheraRay tagged + merged, contact_deals/meetings refreshed for the expanded set) and adds NLAP. If `contact_deals`/`meetings`/`floor_days` are not already defined before this block, confirm by reading upward - they are referenced by the original block at lines 154-155, so they are in scope.

- [ ] **Step 3: Add NLAP to the preferred groups list**

Find `preferred = ["Chiro", "EMX", "PT Recovery", "TheraRay"]` (grep: `preferred = [`). Change to:

```python
        preferred = ["Chiro", "EMX", "PT Recovery", "TheraRay", "NLAP"]
```

- [ ] **Step 4: Compile + full suite**

Run: `python -m py_compile dashboard/sections/executive.py && python -m pytest dashboard/tests -q`
Expected: compile OK, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/sections/executive.py
git commit -m "feat: executive uses merge_list_group for TheraRay + NLAP"
```

---

### Task 4: NLAP in the Metrics daily VA summary

Add an NLAP block to `daily_va_summary` (parallel to TheraRay) and wire `metrics.py` to load list 7086 and render NLAP spend / leads / CPL.

**Files:**
- Modify: `dashboard/data/reconcile.py` (`daily_va_summary` ~lines 1616-1701)
- Modify: `dashboard/sections/metrics.py` (loader ~line 106; calls ~line 111-120; cards ~line 146-170; text ~line 194-211)
- Test: `dashboard/tests/test_reconcile.py`

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_reconcile.py` (it already imports pandas as pd and uses `from datetime import date` patterns - match the file's existing import style; if `daily_va_summary` isn't imported there, import it inline):

```python
def test_daily_va_summary_nlap_block():
    from datetime import date as _date
    from dashboard.data.reconcile import daily_va_summary
    fb = pd.DataFrame([
        {"group": "NLAP", "spend": 300.0, "date_start": "2026-06-03"},
        {"group": "Chiro", "spend": 100.0, "date_start": "2026-06-03"},
    ])
    nlap_mem = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},  # in
        {"contact_id": "2", "membership_timestamp": "2026-06-05T00:00:00Z"},  # in
        {"contact_id": "3", "membership_timestamp": "2026-01-01T00:00:00Z"},  # out
    ])
    out = daily_va_summary(
        fb=fb, contacts=pd.DataFrame(),
        theraray_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        nlap_memberships=nlap_mem,
        start=_date(2026, 6, 1), end=_date(2026, 6, 30),
        asset_to_group={"Top 10 typeform": "Chiro"},
    )
    assert out["nlap_ad_spend"] == 300.0
    assert out["nlap_submissions"] == 2
    assert out["nlap_cpl"] == 150.0
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python -m pytest dashboard/tests/test_reconcile.py::test_daily_va_summary_nlap_block -q`
Expected: FAIL (`daily_va_summary() got an unexpected keyword argument 'nlap_memberships'`).

- [ ] **Step 3: Add the NLAP block to `daily_va_summary`**

In `dashboard/data/reconcile.py`, add the param to the signature (after `theraray_memberships`):

```python
    theraray_memberships: pd.DataFrame,
    nlap_memberships: pd.DataFrame,
```

In the FB-spend block, add NLAP spend next to `theraray_spend` (inside the `if not fb.empty ...` branch, and `0.0` in the else):

```python
        nlap_spend = float(
            fb.loc[in_window & (fb["group"] == "NLAP"), "spend"].sum()
        )
```
(else branch: `nlap_spend = 0.0`)

After the TheraRay submissions block, add the NLAP submissions block:

```python
    # --- NLAP submissions: list memberships in window ---
    if not nlap_memberships.empty \
            and "membership_timestamp" in nlap_memberships.columns:
        nlap_ts = pd.to_datetime(
            nlap_memberships["membership_timestamp"], utc=True, errors="coerce"
        ).dt.date
        nlap_submissions = int(nlap_ts.between(start, end).sum())
    else:
        nlap_submissions = 0
```

Add to the returned dict (after the theraray_* keys):

```python
        "nlap_submissions": nlap_submissions,
        "nlap_ad_spend": nlap_spend,
        "nlap_cpl": (nlap_spend / nlap_submissions) if nlap_submissions else None,
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `python -m pytest dashboard/tests/test_reconcile.py::test_daily_va_summary_nlap_block -q`
Expected: PASS

- [ ] **Step 5: Wire metrics.py - load list + pass to both calls**

In `dashboard/sections/metrics.py`, after the `theraray = load_list_memberships(...)` try/except (~line 106-109), add:

```python
    try:
        nlap = load_list_memberships(cfg.NLAP_HUBSPOT_LIST_ID)
    except Exception as e:
        st.warning(f"NLAP list memberships unavailable: {e}")
        nlap = pd.DataFrame(columns=["contact_id", "membership_timestamp"])
```

Add `nlap_memberships=nlap,` to BOTH `daily_va_summary(...)` calls (the `mtd` and `yday` calls).

- [ ] **Step 6: Render NLAP cards (MTD + Yesterday columns)**

In the MTD column, after the TheraRay `h.metric("Cost / Submission", ...)` block (~line 151-152), add:

```python
        st.markdown("**NLAP**")
        i, j = st.columns(2)
        i.metric("Submissions", mtd["nlap_submissions"])
        j.metric("Ad Spend", _money(mtd["nlap_ad_spend"]))
        k, _ = st.columns(2)
        k.metric("Cost / Submission", _money_or_dash(mtd["nlap_cpl"]),
                 help="NLAP Ad Spend / Submissions.")
```

In the Yesterday column, after its TheraRay block (~line 170), add:

```python
        st.markdown("**NLAP**")
        i, j = st.columns(2)
        i.metric("Submissions", yday["nlap_submissions"])
        j.metric("Ad Spend", _money(yday["nlap_ad_spend"]))
        k, _ = st.columns(2)
        k.metric("Cost / Submission", _money_or_dash(yday["nlap_cpl"]))
```

- [ ] **Step 7: Add NLAP to the copy-paste text block**

In the `text = (...)` f-string, after the TheraRay "Cost per Submission" lines (~line 206-211, before the closing `)`), append:

```python
        f"\nNLAP Submissions\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}      - "
        f"{mtd['nlap_submissions']} submissions\n"
        f"{yesterday.strftime('%b %d')}                    - "
        f"{yday['nlap_submissions']} submission\n\n"
        f"AD Spent\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}    - "
        f"${mtd['nlap_ad_spend']:,.2f}\n"
        f"{yesterday.strftime('%b %d')}                 - "
        f"${yday['nlap_ad_spend']:,.2f}\n\n"
        f"Cost per Submission\n"
        f"MTD {month_start.strftime('%b %d')} - "
        f"{today.strftime('%b %d')}    - "
        f"{_fmt_cpl(mtd['nlap_cpl'])}\n"
        f"{yesterday.strftime('%b %d')}                 - "
        f"{_fmt_cpl(yday['nlap_cpl'])}\n"
```

- [ ] **Step 8: Check other `daily_va_summary` callers**

Run: `grep -rn "daily_va_summary(" dashboard/ --include=*.py`
Every caller must now pass `nlap_memberships=`. If any caller other than metrics.py exists (e.g. a report script), add `nlap_memberships=<list or empty df>` there too. (The signature change makes it required; a missing arg is a TypeError caught at runtime.)

- [ ] **Step 9: Compile + full suite**

Run: `python -m py_compile dashboard/sections/metrics.py dashboard/data/reconcile.py && python -m pytest dashboard/tests -q`
Expected: compile OK, all tests pass (56 prior + 4 new from Tasks 1-4 = 60; exact count may differ - the key is all green).

- [ ] **Step 10: Commit**

```bash
git add dashboard/data/reconcile.py dashboard/sections/metrics.py dashboard/tests/test_reconcile.py
git commit -m "feat: NLAP spend/leads/CPL in Metrics daily summary"
```

---

### Task 5: Verify + push

- [ ] **Step 1: Full suite** - `python -m pytest dashboard/tests -q` (all green).
- [ ] **Step 2: Smoke probe** (delete after): load `match_group` on a real `__NLAP__` campaign, `load_list_memberships(cfg.NLAP_HUBSPOT_LIST_ID)` to confirm list 7086 returns members, and `merge_list_group` on a tiny fixture. Confirm no crash and NLAP members get tagged.
- [ ] **Step 3: Push** - `git push origin feature/cmo-dashboard`.

---

## Self-Review notes

- `merge_list_group` is pure (loaders injected) and unit-tested; the executive refactor preserves TheraRay behavior and adds NLAP with one extra tuple.
- NLAP leads come from list 7086 (membership timestamp), spend from FB `__NLAP__` campaigns - matching the spec.
- NLAP economics intentionally untouched (lead-gen only, $0). No `_group_from_tier` / analytics-source / GROUP_DEFAULT_DEAL_AMOUNT changes.
- Group breakdown / Cost-per-Stage / group filter / Sales Asset Performance pick up NLAP for free once it is a tagged group with FB spend (no code change needed there).
- Risk: if `contact_deals`/`meetings`/`floor_days` are NOT defined before the executive merge block, Step 2's refresh would NameError - the implementer confirms scope in Task 3 Step 1 (they are referenced by the original block, so they exist).
