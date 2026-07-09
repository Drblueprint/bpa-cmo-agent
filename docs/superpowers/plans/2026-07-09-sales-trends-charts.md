# Sales Trends Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Sales Trends" section to the SALES tab with a dedicated date range + weekly/monthly toggle + rep filter, showing 4 Plotly trend charts (funnel volume, conversion rates, SDR call activity, sales & revenue) each backed by a data table.

**Architecture:** A pure `_period_ranges()` buckets the chosen range (weekly Mon-Sun or monthly). A pure `sales_trends()` counts each sales-process event by its own date per bucket (throughput view, NOT a cohort funnel) with an optional SDR-owner rep filter, returning a tidy time-series DataFrame. The render loads its own frames for the trends range (cached loaders), builds ranges, calls `sales_trends`, and draws 4 Plotly charts + tables.

**Tech Stack:** Python, pandas, Plotly (already a dep, `plotly>=5.24.1`), Streamlit. Tests: `python -m pytest dashboard/tests -q` via the Bash tool (context-mode python is a stub). Repo: `C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent`, branch `feature/cmo-dashboard`. Spec: `docs/superpowers/specs/2026-07-09-sales-trends-charts-design.md`.

**Conventions:** PURE rollups in reconcile.py (config injected, never imported). No em dashes in user-facing copy. Stage ONLY the files each task names (repo has unrelated pre-existing modified/untracked files; leave them). End every commit with:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Frame column reference (already loaded shapes): contacts have `hs_id, typeform_submission_date, sdr_owner, phone, mobilephone`; meetings have `contact_id, activity_type, outcome, start_time`; deals have `deal_id, dealstage, amount, closedate, stage_entry_date, createdate`; calls have `started_at_utc, answered_at_utc, duration, direction, user_id, phone_normalized`. Held = `outcome.upper().startswith("COMPLETE")`. Discovery meetings via `discovery_mask(types)`. Strategy meetings via `types.str.contains("strategy")`.

---

## Task 1: `_period_ranges` — weekly / monthly bucket builder

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `_period_ranges` near the other date helpers, e.g. after `_ts_ms_in_window`/`_date_in_window` around line 1975)
- Test: `dashboard/tests/test_sales_trends.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/test_sales_trends.py`:

```python
from datetime import date
from dashboard.data.reconcile import _period_ranges


def test_period_ranges_weekly():
    # Wed 2026-06-03 .. Tue 2026-06-16 -> 3 Mon-Sun weeks covering the span
    r = _period_ranges(date(2026, 6, 3), date(2026, 6, 16), "weekly")
    assert [(s, e) for _, s, e in r] == [
        (date(2026, 6, 1), date(2026, 6, 7)),
        (date(2026, 6, 8), date(2026, 6, 14)),
        (date(2026, 6, 15), date(2026, 6, 21)),
    ]


def test_period_ranges_monthly():
    r = _period_ranges(date(2026, 4, 15), date(2026, 6, 10), "monthly")
    assert [(s, e) for _, s, e in r] == [
        (date(2026, 4, 1), date(2026, 4, 30)),
        (date(2026, 5, 1), date(2026, 5, 31)),
        (date(2026, 6, 1), date(2026, 6, 30)),
    ]


def test_period_ranges_shorter_than_one_bucket():
    r = _period_ranges(date(2026, 6, 2), date(2026, 6, 4), "weekly")
    assert len(r) == 1
    assert (r[0][1], r[0][2]) == (date(2026, 6, 1), date(2026, 6, 7))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_sales_trends.py -q`
Expected: FAIL (import error — `_period_ranges` not defined).

- [ ] **Step 3: Implement `_period_ranges`**

Add to `reconcile.py` (the module already imports `date, datetime, timedelta, timezone`):

```python
def _period_ranges(start: date, end: date, granularity: str) -> list[tuple[str, date, date]]:
    """Ordered (label, bucket_start, bucket_end) buckets spanning [start, end].

    granularity: "weekly" (Mon-Sun weeks) or "monthly" (calendar months).
    Oldest first. A window shorter than one bucket yields a single bucket.
    """
    out: list[tuple[str, date, date]] = []
    if granularity == "monthly":
        cur = start.replace(day=1)
        while cur <= end:
            nxt = (cur.replace(year=cur.year + 1, month=1, day=1)
                   if cur.month == 12 else cur.replace(month=cur.month + 1, day=1))
            out.append((cur.strftime("%b %Y"), cur, nxt - timedelta(days=1)))
            cur = nxt
    else:  # weekly (default)
        cur = start - timedelta(days=start.weekday())  # Monday of start's week
        while cur <= end:
            out.append((cur.strftime("%b %d"), cur, cur + timedelta(days=6)))
            cur = cur + timedelta(days=7)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_sales_trends.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_sales_trends.py
git commit -m "feat(sales): weekly/monthly period-range builder for trends

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `sales_trends` — per-bucket throughput time series

**Files:**
- Modify: `dashboard/data/reconcile.py` (add `sales_trends` after `_period_ranges`)
- Test: `dashboard/tests/test_sales_trends.py` (append)

Semantics: each metric counts events by their OWN date within the bucket (throughput), independent of when the lead entered. Rep filter (`rep_owner_id`) restricts to that SDR's pipeline: leads/meetings/closes for contacts whose `sdr_owner == rep_owner_id`, and dials for AirCall users mapped to that owner. Team (rep_owner_id=None) = everyone.

- [ ] **Step 1: Write the failing test**

Append to `dashboard/tests/test_sales_trends.py`:

```python
import pandas as pd
from dashboard.data.reconcile import sales_trends

WK = _period_ranges(date(2026, 6, 1), date(2026, 6, 14), "weekly")  # 2 weeks


def _dt(s):  # helper: ISO string
    return s


def test_sales_trends_counts_by_event_date_and_rates():
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_submission_date": "2026-06-02T10:00:00Z", "sdr_owner": "A"},
        {"hs_id": "2", "typeform_submission_date": "2026-06-09T10:00:00Z", "sdr_owner": "B"},
    ])
    meetings = pd.DataFrame([
        # week 1: one discovery booked + held
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "COMPLETE - QUALIFIED",
         "start_time": "2026-06-03T15:00:00Z"},
        # week 2: one discovery booked, NOT held; one strategy booked+held
        {"contact_id": "2", "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-06-10T15:00:00Z"},
        {"contact_id": "2", "activity_type": "Strategy Call", "outcome": "COMPLETED",
         "start_time": "2026-06-11T15:00:00Z"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "won", "amount": 5000.0,
         "closedate": "2026-06-12T00:00:00Z", "stage_entry_date": None, "createdate": None},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "2", "deal_id": "d1"}])
    calls = pd.DataFrame([
        {"started_at_utc": int(pd.Timestamp("2026-06-03T16:00:00Z").timestamp()),
         "answered_at_utc": int(pd.Timestamp("2026-06-03T16:00:05Z").timestamp()),
         "duration": 60, "direction": "outbound", "user_id": "ac_A", "phone_normalized": ""},
        {"started_at_utc": int(pd.Timestamp("2026-06-03T17:00:00Z").timestamp()),
         "answered_at_utc": None, "duration": 0, "direction": "outbound",
         "user_id": "ac_A", "phone_normalized": ""},
    ])
    df = sales_trends(
        contacts=contacts, meetings=meetings, deals=deals, contact_deals=contact_deals,
        calls=calls, period_ranges=WK, rep_owner_id=None,
        stages_closed_won={"won"}, aircall_to_sdr_owner={"ac_A": "A"},
        connect_duration_sec=10,
    ).set_index("period_start")

    w1, w2 = date(2026, 6, 1), date(2026, 6, 8)
    assert df.loc[w1, "leads"] == 1
    assert df.loc[w1, "disco_booked"] == 1
    assert df.loc[w1, "disco_held"] == 1
    assert df.loc[w1, "dials"] == 2
    assert df.loc[w1, "connects"] == 1          # 1 answered + duration>=10
    assert abs(df.loc[w1, "connect_rate"] - 0.5) < 1e-9
    assert df.loc[w2, "leads"] == 1
    assert df.loc[w2, "disco_booked"] == 1
    assert df.loc[w2, "disco_held"] == 0
    assert df.loc[w2, "strat_booked"] == 1
    assert df.loc[w2, "strat_held"] == 1
    assert df.loc[w2, "closed"] == 1
    assert df.loc[w2, "revenue"] == 5000.0
    # rates: week 2 show_rate = held/booked = 0/1 = 0.0; week 1 = 1/1 = 1.0
    assert df.loc[w1, "show_rate"] == 1.0
    assert df.loc[w2, "show_rate"] == 0.0


def test_sales_trends_rep_filter_isolates_owner():
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_submission_date": "2026-06-02T10:00:00Z", "sdr_owner": "A"},
        {"hs_id": "2", "typeform_submission_date": "2026-06-03T10:00:00Z", "sdr_owner": "B"},
    ])
    empty_m = pd.DataFrame(columns=["contact_id", "activity_type", "outcome", "start_time"])
    empty_d = pd.DataFrame(columns=["deal_id", "dealstage", "amount", "closedate",
                                    "stage_entry_date", "createdate"])
    df = sales_trends(
        contacts=contacts, meetings=empty_m, deals=empty_d,
        contact_deals=pd.DataFrame(columns=["contact_id", "deal_id"]),
        calls=pd.DataFrame(columns=["started_at_utc", "answered_at_utc", "duration",
                                    "direction", "user_id", "phone_normalized"]),
        period_ranges=_period_ranges(date(2026, 6, 1), date(2026, 6, 7), "weekly"),
        rep_owner_id="A", stages_closed_won={"won"}, aircall_to_sdr_owner={},
        connect_duration_sec=10,
    ).set_index("period_start")
    assert df.loc[date(2026, 6, 1), "leads"] == 1  # only owner A's lead
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_sales_trends.py -q`
Expected: FAIL (`sales_trends` not defined).

- [ ] **Step 3: Implement `sales_trends`**

Add to `reconcile.py` after `_period_ranges`:

```python
def sales_trends(
    *,
    contacts: pd.DataFrame,
    meetings: pd.DataFrame,
    deals: pd.DataFrame,
    contact_deals: pd.DataFrame,
    calls: pd.DataFrame,
    period_ranges: list[tuple[str, date, date]],
    rep_owner_id: str | None,
    stages_closed_won,
    aircall_to_sdr_owner: dict[str, str],
    connect_duration_sec: int,
) -> pd.DataFrame:
    """Per-bucket sales throughput time series (events counted by their own date).

    Columns: period_label, period_start, leads, disco_booked, disco_held,
    strat_booked, strat_held, closed, revenue, dials, connects, connect_rate,
    show_rate, book_rate, close_rate. Rates are None when the denominator is 0.
    rep_owner_id: restrict to that SDR's pipeline (contacts.sdr_owner) + their
    AirCall dials; None = whole team.
    """
    cols = ["period_label", "period_start", "leads", "disco_booked", "disco_held",
            "strat_booked", "strat_held", "closed", "revenue", "dials", "connects",
            "connect_rate", "show_rate", "book_rate", "close_rate"]

    # --- Contacts scope (rep filter) + date parsing ---
    c = contacts.copy()
    if rep_owner_id is not None and not c.empty:
        c = c[c["sdr_owner"].astype(str) == str(rep_owner_id)]
    c_ids = set(c["hs_id"].astype(str)) if not c.empty else set()
    c_submit = (pd.to_datetime(c["typeform_submission_date"], utc=True, errors="coerce").dt.date
                if not c.empty else pd.Series(dtype=object))

    # --- Meetings scope to in-scope contacts + parse ---
    if not meetings.empty:
        m = meetings.copy()
        if rep_owner_id is not None:
            m = m[m["contact_id"].astype(str).isin(c_ids)]
        m_types = m["activity_type"].fillna("").astype(str).str.lower()
        m_out = m["outcome"].fillna("").astype(str).str.upper()
        m_start = pd.to_datetime(m["start_time"], utc=True, errors="coerce").dt.date
        m_disco = discovery_mask(m_types)
        m_strat = m_types.str.contains("strategy", na=False)
        m_held = m_out.str.startswith("COMPLETE")
    else:
        m = meetings
        m_start = pd.Series(dtype=object)
        m_disco = m_strat = m_held = pd.Series(dtype=bool)

    # --- Deals scope (closed-won, rep filter via contact_deals) + close date ---
    won = set(stages_closed_won)
    if not deals.empty:
        d = deals.copy()
        d_close = pd.to_datetime(
            d["closedate"].fillna(d.get("stage_entry_date")).fillna(d.get("createdate")),
            utc=True, errors="coerce").dt.date
        d_won = d["dealstage"].isin(won)
        if rep_owner_id is not None:
            rep_deal_ids = set(contact_deals[
                contact_deals["contact_id"].astype(str).isin(c_ids)]["deal_id"]) \
                if not contact_deals.empty else set()
            d_won = d_won & d["deal_id"].isin(rep_deal_ids)
    else:
        d = deals
        d_close = pd.Series(dtype=object)
        d_won = pd.Series(dtype=bool)

    # --- Calls scope (outbound; rep filter via aircall->owner) + start date ---
    if not calls.empty:
        cl = calls[calls["direction"] == "outbound"].copy()
        if rep_owner_id is not None:
            owned_users = {u for u, o in aircall_to_sdr_owner.items()
                           if str(o) == str(rep_owner_id)}
            cl = cl[cl["user_id"].astype(str).isin(owned_users)]
        cl_start = cl["started_at_utc"].apply(
            lambda x: datetime.fromtimestamp(int(x), tz=timezone.utc).date()
            if pd.notna(x) else None)
        cl_answered = cl["answered_at_utc"].notna() & (
            cl["duration"].fillna(0).astype(float) >= connect_duration_sec)
    else:
        cl = calls
        cl_start = pd.Series(dtype=object)
        cl_answered = pd.Series(dtype=bool)

    def _in(series, bs, be):
        return series.apply(lambda x: x is not None and bs <= x <= be)

    rows = []
    for label, bs, be in period_ranges:
        leads = int(_in(c_submit, bs, be).sum()) if not c.empty else 0
        if not m.empty:
            in_wk = _in(m_start, bs, be)
            disco_booked = int((m_disco & in_wk).sum())
            disco_held = int((m_disco & in_wk & m_held).sum())
            strat_booked = int((m_strat & in_wk).sum())
            strat_held = int((m_strat & in_wk & m_held).sum())
        else:
            disco_booked = disco_held = strat_booked = strat_held = 0
        if not d.empty:
            won_wk = d_won & _in(d_close, bs, be)
            closed = int(won_wk.sum())
            revenue = float(d.loc[won_wk, "amount"].fillna(0).astype(float).sum())
        else:
            closed, revenue = 0, 0.0
        if not cl.empty:
            call_wk = _in(cl_start, bs, be)
            dials = int(call_wk.sum())
            connects = int((call_wk & cl_answered).sum())
        else:
            dials = connects = 0
        rows.append({
            "period_label": label, "period_start": bs,
            "leads": leads, "disco_booked": disco_booked, "disco_held": disco_held,
            "strat_booked": strat_booked, "strat_held": strat_held,
            "closed": closed, "revenue": revenue,
            "dials": dials, "connects": connects,
            "connect_rate": _safe_div(connects, dials),
            "show_rate": _safe_div(disco_held, disco_booked),
            "book_rate": _safe_div(strat_booked, disco_held),
            "close_rate": _safe_div(closed, strat_held),
        })
    return pd.DataFrame(rows, columns=cols)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests/test_sales_trends.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite (no regressions)**

Run: `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q`
Expected: PASS (prior count + new).

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/data/reconcile.py dashboard/tests/test_sales_trends.py
git commit -m "feat(sales): sales_trends per-bucket throughput time series

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Render the Sales Trends section (controls + 4 Plotly charts)

**Files:**
- Modify: `dashboard/sections/sales.py` (imports; insert the section after SME Performance, before Asset Performance ~line 1259)

No unit test (Streamlit render); verified by `ast.parse` + full suite + Task 4 live screenshot.

- [ ] **Step 1: Add imports** at the top of `sales.py`

```python
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from datetime import date, timedelta
from dashboard.data.reconcile import sales_trends, _period_ranges
from dashboard.data.hubspot_loader import load_meetings_in_window
```
(Only add names not already imported — check the existing import block first; `date`/`timedelta` and some loaders are already imported.)

- [ ] **Step 2: Insert the section** immediately before the `Asset Performance` subheader (~line 1259)

```python
    # ===================== Sales Trends =====================
    st.subheader("Sales Trends")
    st.caption("Trends over a range you choose here (independent of the view above). "
               "Pick weekly or monthly buckets and optionally focus one rep.")
    _t_today = date.today()
    tc1, tc2, tc3 = st.columns([2, 1, 1])
    with tc1:
        _range = st.date_input(
            "Trends date range",
            value=(_t_today - timedelta(days=90), _t_today),
            key="sales_trends_range",
        )
    with tc2:
        gran = st.radio("Buckets", ["Weekly", "Monthly"], index=0,
                        horizontal=True, key="sales_trends_gran")
    # st.date_input with a tuple value returns a (start, end) tuple; mid-edit it
    # can briefly return a single date -> treat as "not ready".
    if isinstance(_range, (tuple, list)) and len(_range) == 2:
        tr_start, tr_end = _range
    else:
        tr_start = tr_end = None
    if tr_start is None or tr_end is None or tr_start > tr_end:
        st.info("Pick a start and end date for the trends.")
    else:
        # Load frames for the trends range (own load; cached loaders)
        try:
            tr_contacts = load_marketing_contacts(tr_start, tr_end)
        except Exception as e:
            st.warning(f"Trends: contacts unavailable: {e}")
            tr_contacts = pd.DataFrame()
        tr_ids = tr_contacts["hs_id"].tolist() if not tr_contacts.empty else []
        try:
            tr_cd = load_contact_deals(tr_ids) if tr_ids else pd.DataFrame(columns=["contact_id", "deal_id"])
        except Exception:
            tr_cd = pd.DataFrame(columns=["contact_id", "deal_id"])
        try:
            tr_deals = load_deals_in_window(tr_start, tr_end, data_floor_days_back=floor_days)
        except Exception:
            tr_deals = pd.DataFrame()
        try:
            tr_meetings = load_meetings_in_window(tr_start, tr_end)
        except Exception:
            tr_meetings = pd.DataFrame(columns=["meeting_id", "contact_id", "activity_type", "outcome", "start_time"])
        try:
            tr_calls = load_aircall_calls(tr_start, tr_end)
        except Exception:
            tr_calls = pd.DataFrame(columns=["started_at_utc", "answered_at_utc", "duration",
                                             "direction", "user_id", "phone_normalized"])
        # Rep filter dropdown from sdr_owners present in the range
        with tc3:
            _owner_ids = sorted(
                {str(x) for x in tr_contacts.get("sdr_owner", pd.Series(dtype=object)).dropna()
                 if str(x)}) if not tr_contacts.empty else []
            _labels = ["Team (all)"] + [cfg.resolve_owner(o) for o in _owner_ids]
            _pick = st.selectbox("Rep", _labels, index=0, key="sales_trends_rep")
        rep_owner = None
        if _pick != "Team (all)":
            rep_owner = next((o for o in _owner_ids if cfg.resolve_owner(o) == _pick), None)

        ranges = _period_ranges(tr_start, tr_end, gran.lower())
        if len(ranges) < 2:
            st.info("Range is shorter than one bucket. Widen the range (or switch to Weekly) for a trend.")
        trends = sales_trends(
            contacts=tr_contacts, meetings=tr_meetings, deals=tr_deals,
            contact_deals=tr_cd, calls=tr_calls, period_ranges=ranges,
            rep_owner_id=rep_owner, stages_closed_won=cfg.STAGES_CLOSED_WON,
            aircall_to_sdr_owner=cfg.AIRCALL_TO_SDR_OWNER,
            connect_duration_sec=cfg.AIRCALL_CONNECT_DURATION_SEC,
        )
        _x = trends["period_label"]

        # Chart 1: Funnel volume by stage
        vol = trends.rename(columns={
            "leads": "Leads", "disco_booked": "15-min Booked", "disco_held": "15-min Held",
            "strat_booked": "Strategy Booked", "strat_held": "Strategy Held", "closed": "Closed-Won"})
        vol_long = vol.melt(id_vars=["period_label"],
                            value_vars=["Leads", "15-min Booked", "15-min Held",
                                        "Strategy Booked", "Strategy Held", "Closed-Won"],
                            var_name="Stage", value_name="Count")
        fig1 = px.line(vol_long, x="period_label", y="Count", color="Stage", markers=True,
                       title="Funnel volume by stage")
        fig1.update_layout(xaxis_title="", legend_title="")
        st.plotly_chart(fig1, use_container_width=True)

        # Chart 2: Conversion rates
        rates = trends.assign(
            **{"Show %": trends["show_rate"] * 100,
               "Booking %": trends["book_rate"] * 100,
               "Close %": trends["close_rate"] * 100})
        rates_long = rates.melt(id_vars=["period_label"],
                                value_vars=["Show %", "Booking %", "Close %"],
                                var_name="Rate", value_name="Percent")
        fig2 = px.line(rates_long, x="period_label", y="Percent", color="Rate", markers=True,
                       title="Conversion rates")
        fig2.update_layout(xaxis_title="", legend_title="", yaxis_ticksuffix="%")
        st.plotly_chart(fig2, use_container_width=True)

        # Chart 3: SDR call activity (dials/connects left, connect % right)
        fig3 = make_subplots(specs=[[{"secondary_y": True}]])
        fig3.add_trace(go.Scatter(x=_x, y=trends["dials"], name="Dials", mode="lines+markers"), secondary_y=False)
        fig3.add_trace(go.Scatter(x=_x, y=trends["connects"], name="Connects", mode="lines+markers"), secondary_y=False)
        fig3.add_trace(go.Scatter(x=_x, y=trends["connect_rate"] * 100, name="Connect %",
                                  mode="lines+markers", line=dict(dash="dot")), secondary_y=True)
        fig3.update_layout(title="SDR call activity", xaxis_title="")
        fig3.update_yaxes(title_text="Calls", secondary_y=False)
        fig3.update_yaxes(title_text="Connect %", ticksuffix="%", secondary_y=True)
        st.plotly_chart(fig3, use_container_width=True)

        # Chart 4: Sales & revenue (count left, revenue right)
        fig4 = make_subplots(specs=[[{"secondary_y": True}]])
        fig4.add_trace(go.Scatter(x=_x, y=trends["closed"], name="Closed-Won", mode="lines+markers"), secondary_y=False)
        fig4.add_trace(go.Scatter(x=_x, y=trends["revenue"], name="Revenue", mode="lines+markers",
                                  line=dict(dash="dot")), secondary_y=True)
        fig4.update_layout(title="Sales & revenue", xaxis_title="")
        fig4.update_yaxes(title_text="Closed deals", secondary_y=False)
        fig4.update_yaxes(title_text="Revenue ($)", secondary_y=True)
        st.plotly_chart(fig4, use_container_width=True)

        with st.expander("Show trend data"):
            st.dataframe(trends, use_container_width=True, hide_index=True)
```

Note: `floor_days`, `pd`, `st`, `cfg`, `load_marketing_contacts`, `load_contact_deals`, `load_deals_in_window`, `load_aircall_calls` are already in scope in `render_sales` (used earlier in the function). Confirm each is imported/defined before relying on it; add any missing loader to the existing hubspot_loader import block.

- [ ] **Step 3: Verify parse + imports + suite**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import ast; ast.parse(open('dashboard/sections/sales.py', encoding='utf-8').read()); print('ast OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import plotly.express, plotly.graph_objects; from plotly.subplots import make_subplots; print('plotly OK')"
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -m pytest dashboard/tests -q
```
Expected: `ast OK`, `plotly OK`, suite green.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent"
git add dashboard/sections/sales.py
git commit -m "feat(sales): Sales Trends section - 4 Plotly charts + controls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Live verify + push

Orchestrator-run (interactive).

- [ ] **Step 1** Ensure `plotly` is installed locally (it is in requirements): `cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && python -c "import plotly; print(plotly.__version__)"`.
- [ ] **Step 2** Launch the app via the preview tooling (or confirm the deployed app after push) and screenshot the SALES tab Sales Trends section: confirm the 4 charts render, the Weekly/Monthly toggle re-buckets, the rep filter changes the lines, and the data table matches. Fix any render issue (re-run from Task 3 step 3).
- [ ] **Step 3** Push:
```bash
cd "C:/Users/kxbox/OneDrive/Desktop/bpa-cmo-agent" && git push origin feature/cmo-dashboard
```
- [ ] **Step 4** Report to Kurt with a screenshot; note the default range (last 90 days) and that trend numbers reconcile with the point-in-time tables for an overlapping window.

---

## Self-Review

**Spec coverage:**
- Dedicated date-range picker + own frame load → Task 3. ✓
- Weekly/Monthly toggle → Task 1 builder + Task 3 radio. ✓
- Rep filter (team default + single rep) → Task 2 `rep_owner_id` + Task 3 selectbox. ✓
- 4 charts (funnel volume, conversion rates, SDR activity dual-axis, sales & revenue dual-axis) → Task 3. ✓
- Data tables under charts → Task 3 expander. ✓
- Rate = None on zero denominator (gap, not 0) → `_safe_div` in Task 2. ✓
- Short-window note → Task 3. ✓
- Throughput-by-event-date semantics → Task 2. ✓

**Placeholder scan:** every code step is complete; commands have expected output. The one conditional ("confirm X already imported") is a guard against duplicate imports, not a placeholder — the code to add is fully specified.

**Type/name consistency:** `sales_trends` and `_period_ranges` signatures match between Task 1/2 definitions and the Task 3 call. Column names (`period_label, period_start, leads, disco_booked, disco_held, strat_booked, strat_held, closed, revenue, dials, connects, connect_rate, show_rate, book_rate, close_rate`) are identical across the function, tests, and the render's chart/table references. Config injected: `cfg.STAGES_CLOSED_WON`, `cfg.AIRCALL_TO_SDR_OWNER`, `cfg.AIRCALL_CONNECT_DURATION_SEC`. `_safe_div` and `discovery_mask` already exist in reconcile.py.

**Note for implementer:** `st.date_input` with a tuple `value` returns a tuple; mid-edit it can return a single date — the plan guards that. Verify `load_deals_in_window` and `load_aircall_calls` and `load_contact_deals` are imported in sales.py (they are used elsewhere in the file) before reuse.
