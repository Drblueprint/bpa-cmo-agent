"""SALES tab rendering."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.aircall_loader import load_aircall_calls
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
    load_meetings_for_contacts,
    load_closed_deals_ytd,
)
from dashboard.data.reconcile import (
    build_closed_deals_table,
    compute_speed_to_lead,
    pipeline_funnel,
    sales_bds_rollup,
    sales_sdr_rollup,
    sales_sme_rollup,
    windowed_sales_money,
)


def _fmt_money(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def _fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x):,}"


def _fmt_pct(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:.0f}%"


def _fmt_minutes(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:.0f}"


def _stage_groups() -> dict[str, set[str]]:
    return {
        "15min_booked":    cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
        "15min_held":      cfg.STAGES_15MIN_HELD,
        "strategy_booked": cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
        "strategy_held":   cfg.STAGES_STRATEGY_HELD,
        "closedwon":       cfg.STAGES_CLOSED_WON,
    }


def render_sales(start: date, end: date) -> None:
    floor_days = st.session_state.get("data_floor_days_back", 180)

    # ----- View selector: MTD (default) / YTD / Custom (header range) -----
    today = date.today()
    view = st.radio(
        "View",
        options=["Month to Date", "Year to Date", "Custom Range"],
        index=0,
        horizontal=True,
        key="sales_view_selector",
        help="MTD = 1st of this month through today. YTD = Jan 1 through "
             "today. Custom uses the dashboard date picker at the top.",
    )
    if view == "Month to Date":
        start = today.replace(day=1)
        end = today
    elif view == "Year to Date":
        start = today.replace(month=1, day=1)
        end = today
    st.caption(
        f"**Showing:** {view} · {start.strftime('%b %d, %Y')} → "
        f"{end.strftime('%b %d, %Y')}"
    )

    st.info(
        '**"Marketing-attributed"** below = HubSpot contact has '
        '`typeform_asset_download` populated.',
        icon="ℹ️",
    )

    try:
        marketing = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        marketing = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(marketing["hs_id"].tolist()) \
            if not marketing.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(start, end, data_floor_days_back=floor_days)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()
    try:
        aircall_calls = load_aircall_calls(start, end)
    except Exception as e:
        st.warning(f"AirCall unavailable: {e}")
        aircall_calls = pd.DataFrame(columns=[
            "call_id", "started_at_utc", "answered_at_utc", "duration",
            "direction", "status", "user_id", "user_name",
            "raw_digits", "phone_normalized",
        ])
    try:
        meetings = load_meetings_for_contacts(marketing["hs_id"].tolist(),
                                              data_floor_days_back=floor_days) \
            if not marketing.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])

    # Full-window contact attribution: pull every contact tied to a deal in
    # the window so marketing-attribution works across long sales cycles.
    # Without this, a contact who filled the typeform in March but had their
    # 15-min in May would NOT count as marketing (because load_marketing_contacts
    # filters by typeform_submission_date in window). The reverse lookup
    # (deal -> contacts) closes the gap.
    try:
        from dashboard.data.hubspot_loader import (
            load_contacts_by_ids, load_deal_contacts,
        )
        if not deals.empty:
            deal_contact_map = load_deal_contacts(deals["deal_id"].astype(str).tolist())
            all_window_contact_ids = set(
                deal_contact_map["contact_id"].astype(str)
            ) if not deal_contact_map.empty else set()
            known_ids = set(marketing["hs_id"].astype(str)) if not marketing.empty else set()
            missing_ids = list(all_window_contact_ids - known_ids)
            if missing_ids:
                extra = load_contacts_by_ids(missing_ids)
                if not extra.empty:
                    marketing = pd.concat([marketing, extra], ignore_index=True)
            # Refresh contact_deals + meetings so they cover the expanded
            # marketing set — otherwise pipeline_funnel(marketing_only=True) and
            # the BDS/SME rollups will still see the original narrow set.
            if not marketing.empty:
                contact_deals = load_contact_deals(marketing["hs_id"].tolist())
                try:
                    meetings = load_meetings_for_contacts(
                        marketing["hs_id"].tolist(),
                        data_floor_days_back=floor_days,
                    )
                except Exception as me:
                    st.warning(f"Expanded meeting reload failed: {me}")
    except Exception as e:
        st.warning(f"Window contact attribution lookup failed: {e}")

    # Keep a separate "full" meetings frame (180-day floor) for the SDR Lead
    # Detail "latest 15-min on record" lookup. ALL ROLLUPS (BDS/SME) use
    # the windowed meetings below so their counts align with the dashboard
    # window — Appointments/Shows/Strategy stop counting meetings outside
    # the active view.
    meetings_full = meetings.copy()
    if not meetings.empty:
        _mstart = pd.to_datetime(meetings["start_time"], utc=True, errors="coerce")
        _ws = pd.Timestamp(year=start.year, month=start.month, day=start.day, tz="UTC")
        _we = pd.Timestamp(year=end.year, month=end.month, day=end.day, tz="UTC") + pd.Timedelta(days=1)
        meetings = meetings[(_mstart >= _ws) & (_mstart < _we)].reset_index(drop=True)

    # YTD closed deals (used by Money cards + Closed Deals YTD section)
    try:
        deals_ytd, contact_deals_ytd, contacts_ytd = load_closed_deals_ytd(
            closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
        )
    except Exception as e:
        st.warning(f"YTD closed deals unavailable: {e}")
        deals_ytd = pd.DataFrame()
        contact_deals_ytd = pd.DataFrame(columns=["contact_id", "deal_id"])
        contacts_ytd = pd.DataFrame()

    stages = _stage_groups()

    fn_mkt = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=True)
    fn_all = pipeline_funnel(marketing, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)

    # ----- Row 1: Pipeline KPIs (existing) -----
    def _v(df, stage, col="count"):
        s = df.loc[df["stage"] == stage, col]
        return s.iloc[0] if not s.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "15-min Calls (Marketing)",
        _fmt_int(_v(fn_mkt, "15-min Booked")),
        help="Deals at 15-min Booked/Held whose contact has "
             "typeform_asset_download populated.",
    )
    c2.metric(
        "15-min Calls (All)",
        _fmt_int(_v(fn_all, "15-min Booked")),
        help="All deals at 15-min Booked/Held, regardless of source.",
    )
    c3.metric(
        "Strategy Calls Held (Mkt)",
        _fmt_int(_v(fn_mkt, "Strategy Held")),
        help="Strategy meetings held for marketing-attributed contacts.",
    )
    c4.metric(
        "Strategy Calls Held (All)",
        _fmt_int(_v(fn_all, "Strategy Held")),
        help="All Strategy meetings held in window, regardless of source.",
    )

    # Pipeline KPI verification — every deal in window with stage flags
    if not deals.empty and not contact_deals.empty:
        try:
            cd_join = contact_deals.merge(
                deals[["deal_id", "dealstage", "amount", "createdate", "closedate"]],
                on="deal_id", how="left",
            )
            cd_join["contact_id"] = cd_join["contact_id"].astype(str)
            c_lite_cols = ["hs_id", "name", "email",
                            "typeform_asset_download", "sdr_owner", "bds",
                            "lifecycle_stage", "contract_tier"]
            existing_cols = [c for c in c_lite_cols if c in marketing.columns]
            c_lite = marketing[existing_cols].copy()
            c_lite["hs_id"] = c_lite["hs_id"].astype(str)
            # Drop existing customers + internal-team contacts before joining
            # so the Pipeline detail shows ONLY active leads being worked.
            if {"lifecycle_stage", "contract_tier", "email"}.issubset(c_lite.columns):
                _excl = c_lite.apply(
                    lambda r: (
                        cfg.is_internal_team_contact(r.get("email"))
                        or cfg.is_existing_customer(r.get("lifecycle_stage"),
                                                      r.get("contract_tier"))
                    ),
                    axis=1,
                )
                c_lite = c_lite[~_excl].reset_index(drop=True)
            pdf = cd_join.merge(c_lite, left_on="contact_id", right_on="hs_id", how="inner")
            # Keep only deals whose CURRENT stage is an early funnel bucket
            # (15-min Booked/Held or Strategy Booked/Held). Closed-Won and
            # other stages are dropped.
            in_funnel = (
                pdf["dealstage"].isin(stages["15min_booked"])
                | pdf["dealstage"].isin(stages["strategy_booked"])
            )
            pdf = pdf[in_funnel].copy()

            # Single readable current-stage label (most-advanced wins) in place
            # of the raw HubSpot stage ID.
            def _stage_name(s):
                if s in cfg.STAGES_STRATEGY_HELD:
                    return "Strategy Held"
                if s in cfg.STAGES_STRATEGY_BOOKED:
                    return "Strategy Booked"
                if s in cfg.STAGES_15MIN_HELD:
                    return "15-min Held"
                if s in cfg.STAGES_15MIN_BOOKED:
                    return "15-min Booked"
                return "(open)"
            _rank = {"Strategy Held": 4, "Strategy Booked": 3,
                     "15-min Held": 2, "15-min Booked": 1, "(open)": 0}
            pdf["Stage"] = pdf["dealstage"].map(_stage_name)

            # Deal age from createdate. Every loaded deal was modified inside
            # the window (that is the loader filter), so "last modified" cannot
            # flag a zombie. createdate can: a deal parked in an early stage for
            # months is stalled, not active pipeline.
            _created = pd.to_datetime(pdf["createdate"], utc=True, errors="coerce")
            _age = _created.dt.date.map(
                lambda d: (end - d).days if pd.notna(d) else None
            )
            pdf["Age (days)"] = pd.to_numeric(_age, errors="coerce")
            # Drop only the indisputable zombies (deals parked in an early stage
            # for over a year). BPA's open early-stage deals already skew old, so
            # a tighter cutoff would empty the view; the Age column lets the user
            # judge the merely-stale ones (5-10 months) themselves.
            STALE_DEAL_DAYS = 365
            pdf = pdf[pdf["Age (days)"].fillna(0) <= STALE_DEAL_DAYS].copy()

            pdf["Marketing?"] = pdf["typeform_asset_download"].fillna("") \
                                    .astype(str).str.strip() != ""
            pdf["Open"]    = pdf["contact_id"].apply(cfg.hubspot_contact_url)
            pdf["Asset"]   = pdf["typeform_asset_download"].fillna("")
            pdf["Group"]   = pdf["Asset"].map(cfg.ASSET_TO_GROUP).fillna("")
            pdf["SDR"]     = pdf["sdr_owner"].map(cfg.resolve_owner) if "sdr_owner" in pdf.columns else "(unassigned)"
            pdf["BDS"]     = pdf["bds"].map(cfg.resolve_owner) if "bds" in pdf.columns else "(unassigned)"
            pdf["Created"] = cfg.format_ct_series(
                pdf["createdate"], fmt=cfg.DEFAULT_DATE_FORMAT
            )
            pdf["_rank"]   = pdf["Stage"].map(_rank)
            out = pdf[["Open", "name", "email", "SDR", "BDS", "Asset", "Group",
                       "Marketing?", "Stage", "Created", "Age (days)", "_rank"]] \
                 .rename(columns={"name": "Contact", "email": "Email"})
            # Most-advanced stage first, then marketing leads, then freshest.
            out = out.sort_values(
                ["_rank", "Marketing?", "Age (days)"],
                ascending=[False, False, True],
            ).reset_index(drop=True)
            out = out.drop(columns=["_rank"])
            out["Age (days)"] = out["Age (days)"].map(
                lambda x: f"{int(x)}" if pd.notna(x) else "—"
            )
            _win = (f"{start.strftime('%b %d').replace(' 0', ' ')} – "
                    f"{end.strftime('%b %d, %Y').replace(' 0', ' ')}")
            with st.expander(
                f"Pipeline detail — {len(out)} active funnel rows",
                expanded=False,
            ):
                st.caption(
                    f"Window: {_win}. One row per OPEN deal whose current stage "
                    "is 15-min Booked / Held or Strategy Booked / Held, for a "
                    "lead in this window. Internal-team members, existing "
                    "customers, and Closed-Won deals are excluded. Deals parked "
                    "in an early stage for over a year (dead / zombie deals) are "
                    "dropped too. Stage = the deal's current HubSpot stage; "
                    "Age = days since the deal was created."
                )
                st.dataframe(
                    cfg.style_unassigned(
                        out, columns=["SDR", "BDS", "Asset", "Group"],
                        green_when=lambda r: str(r.get("Stage")) == "Strategy Held",
                    ),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Open": st.column_config.LinkColumn("Open", display_text="HubSpot ↗"),
                        "Marketing?": st.column_config.CheckboxColumn("Mkt?"),
                    },
                )
        except Exception as e:
            st.warning(f"Pipeline detail unavailable: {e}")

    # ----- Row 2: Money + Time-to-Close (window-bounded, all sources) -----
    money = windowed_sales_money(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        start=start, end=end,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        stages_closed_won_no_closedate=cfg.STAGES_CLOSED_WON_NO_CLOSEDATE,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        group_cash_per_deal=cfg.GROUP_CASH_COLLECTED_PER_DEAL,
        today=date.today(),
        full_monthly=cfg.FULL_MONTHLY, full_term_months=cfg.FULL_TERM_MONTHS,
        ninety_day_amount=cfg.NINETY_DAY_AMOUNT, diy_monthly=cfg.DIY_MONTHLY,
        pt_multiplier=cfg.PT_MULTIPLIER,
    )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(
        "Total Sales (window)",
        _fmt_int(money["window_closed_count"]),
        help="Closed-won deals (all sources) within the current date range.",
    )
    m2.metric(
        "Total Revenue (window)",
        _fmt_money(money["window_revenue"]),
        help="Sum of effective deal $ for closed deals in the date range "
             "(HubSpot amount with group-default fallback).",
    )
    m3.metric(
        "Cash Collection",
        _fmt_money(money["window_cash_collection"]),
        help="Sum of per-deal cash collected (Chiro $47,928 / PT $23,928 per "
             "closed deal). Diverges from Revenue once payment-plan tracking "
             "is wired.",
    )
    m4.metric(
        "Avg Deal Size",
        _fmt_money(money["window_avg_deal_size"]),
        help="Total Revenue / Total Sales for the date range.",
    )
    m5.metric(
        "Avg Time-to-Close (days)",
        _fmt_minutes(money["window_cycle_median_days"]),
        help="Median days from typeform opt-in (createdate fallback) to "
             "deal close, across deals closed in this window.",
    )

    # Money KPI verification — windowed closed deals (filter ytd by closedate)
    if not deals_ytd.empty:
        try:
            no_close_set = set(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE)
            close_dt = pd.to_datetime(deals_ytd.get("closedate"), utc=True, errors="coerce").dt.date
            create_dt = pd.to_datetime(deals_ytd.get("createdate"), utc=True, errors="coerce").dt.date
            if "stage_entry_date" in deals_ytd.columns:
                stage_entry_dt = pd.to_datetime(
                    deals_ytd["stage_entry_date"], utc=True, errors="coerce"
                ).dt.date
            else:
                stage_entry_dt = pd.Series(
                    [None] * len(deals_ytd), index=deals_ytd.index, dtype=object
                )
            mask_close = close_dt.between(start, end)
            no_close_mask = deals_ytd["dealstage"].isin(no_close_set) & close_dt.isna()
            mask_stage_entry = no_close_mask & stage_entry_dt.between(start, end)
            mask_create = (no_close_mask & stage_entry_dt.isna()
                           & create_dt.between(start, end))
            window_deals_only = deals_ytd[mask_close | mask_stage_entry | mask_create].copy()
            window_table = build_closed_deals_table(
                window_deals_only, contact_deals_ytd, contacts_ytd,
                asset_to_group=cfg.ASSET_TO_GROUP,
                group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
                source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
                stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
                today=date.today(),
                full_monthly=cfg.FULL_MONTHLY, full_term_months=cfg.FULL_TERM_MONTHS,
                ninety_day_amount=cfg.NINETY_DAY_AMOUNT, diy_monthly=cfg.DIY_MONTHLY,
                pt_multiplier=cfg.PT_MULTIPLIER,
            )
            if not window_table.empty:
                wt = window_table.copy()
                wt["hubspot_link"] = wt["hs_id"].apply(cfg.hubspot_contact_url)
                wt["sdr_owner"] = wt["sdr_owner"].map(cfg.resolve_owner)
                wt["bds"] = wt["bds"].map(cfg.resolve_owner)
                wt["sme"] = wt["sme"].map(cfg.resolve_owner)
                wt["closedate"] = cfg.format_ct_series(
                    wt["closedate"], fmt=cfg.DEFAULT_DATE_FORMAT
                )
                wt["deal_amount"] = wt["deal_amount"].map(
                    lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—"
                )
                wt["sales_cycle_days"] = wt["sales_cycle_days"].map(
                    lambda x: f"{int(x)}" if pd.notna(x) else "—"
                )
                wt = wt[[
                    "hubspot_link", "closedate", "contact_name", "email", "typeform",
                    "group", "tier", "source", "deal_amount", "sales_cycle_days",
                    "sdr_owner", "bds", "sme",
                ]].rename(columns={
                    "hubspot_link": "Open",
                    "closedate": "Closed",
                    "contact_name": "Contact",
                    "email": "Email",
                    "typeform": "Typeform",
                    "group": "Group",
                    "tier": "Plan",
                    "source": "Source",
                    "deal_amount": "Deal $",
                    "sales_cycle_days": "Cycle (days)",
                    "sdr_owner": "SDR",
                    "bds": "BDS",
                    "sme": "SME",
                })
                mkt_n = int(window_table["is_marketing"].sum())
                with st.expander(
                    f"Money detail — {len(wt)} closes in window "
                    f"({mkt_n} marketing · {len(wt) - mkt_n} non-marketing)",
                    expanded=False,
                ):
                    st.dataframe(
                        cfg.style_unassigned(wt,
                                              columns=["SDR", "BDS", "SME", "Group",
                                                       "Plan", "Source", "Typeform"]),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Open": st.column_config.LinkColumn(
                                "Open", display_text="HubSpot ↗"),
                        },
                    )
        except Exception as e:
            st.warning(f"Money detail unavailable: {e}")

    # ----- Row 3: Speed to Lead (existing) -----
    st.divider()
    st.subheader("Speed to Lead")
    st.caption(
        "Only counts leads whose typeform submission falls inside the current "
        "window — measures how fast we contact **fresh** leads, not how long "
        "ago some old leads first heard from us."
    )
    speed_df = compute_speed_to_lead(
        marketing, aircall_calls, lead_window_start=start
    )
    speeds = speed_df["speed_to_lead_minutes"].dropna()

    if speeds.empty:
        median_speed = None
        pct_under_5 = None
        pct_under_60s = None
    else:
        median_speed = float(speeds.median())
        pct_under_5 = float((speeds <= 5).mean())
        pct_under_60s = float((speeds <= 1).mean())

    s1, s2, s3 = st.columns(3)
    s1.metric(
        "Median Speed to Lead",
        f"{median_speed:.1f} min" if median_speed is not None else "—",
        help="Median minutes from typeform submission to first outbound AirCall.")
    s2.metric(
        "% Under 5 min",
        _fmt_pct(pct_under_5),
        help="Share of leads whose first outbound call landed within 5 minutes "
             "of opt-in. Hormozi's 80% target.")
    s3.metric(
        "% Under 60 sec",
        _fmt_pct(pct_under_60s),
        help="Share within 60 seconds. Hormozi's stretch goal (50%).")

    st.divider()

    # ----- Precompute per-contact maps shared by SDR/BDS/SME detail tables -----
    from collections import defaultdict as _dd
    from dashboard.data.reconcile import normalize_phone as _norm

    # Phone -> [contact_ids]
    _phone_to_contacts: dict = {}
    for _, _c in marketing.iterrows():
        _pn = _norm(_c.get("phone")) or _norm(_c.get("mobilephone"))
        if _pn:
            _phone_to_contacts.setdefault(_pn, []).append(str(_c["hs_id"]))

    # Per-contact AirCall stats (outbound only)
    _per_contact_calls: dict = _dd(lambda: {"dials": 0, "pick_ups": 0,
                                              "contacts_made": 0, "talk_sec": 0})
    if not aircall_calls.empty:
        _ob = aircall_calls[aircall_calls["direction"] == "outbound"]
        if cfg.AIRCALL_EXCLUDED_USERS:
            _ob = _ob[~_ob["user_id"].astype(str).isin(cfg.AIRCALL_EXCLUDED_USERS)]
        for _, _call in _ob.iterrows():
            _pn = _call.get("phone_normalized") or ""
            for _cid in _phone_to_contacts.get(_pn, []):
                _s = _per_contact_calls[_cid]
                _s["dials"] += 1
                if pd.notna(_call.get("answered_at_utc")):
                    _s["pick_ups"] += 1
                    _dur = _call.get("duration") or 0
                    if _dur >= cfg.AIRCALL_CONNECT_DURATION_SEC:
                        _s["contacts_made"] += 1
                        _s["talk_sec"] += _dur

    # Speed-to-lead per contact (in minutes); reused from earlier compute_speed_to_lead
    _speed_map = dict(zip(
        speed_df["hs_id"].astype(str), speed_df["speed_to_lead_minutes"]
    )) if not speed_df.empty else {}

    # Build a one-shot in-window meetings frame for BDS / SME Meeting Detail
    # tables — only meetings whose start_time falls inside [start, end].
    _start_ts = pd.Timestamp(start)
    _end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    if not meetings.empty:
        _mst = pd.to_datetime(meetings["start_time"], utc=True, errors="coerce")
        _mst_local = _mst.dt.tz_convert(None) if getattr(_mst.dt, "tz", None) is not None else _mst
        _in_window_mask = (_mst_local >= _start_ts) & (_mst_local < _end_ts)
        _meetings_in_window = meetings[_in_window_mask].copy()
    else:
        _meetings_in_window = meetings

    # 15-min meeting most-recent per contact ACROSS THE 180-DAY DATA FLOOR
    # (not the dashboard window) — used by SDR Lead Detail's "15-min Status"
    # column so historical bookings still surface as context for each lead.
    _f15_outcome: dict = {}
    _f15_when: dict = {}
    if not meetings_full.empty:
        _types = meetings_full["activity_type"].fillna("").astype(str).str.lower()
        _fm = meetings_full[_types.str.contains("15 min", na=False)].copy()
        if not _fm.empty:
            _fm = _fm.sort_values("start_time", ascending=False, na_position="last") \
                .drop_duplicates(subset="contact_id", keep="first")
            _fm["contact_id"] = _fm["contact_id"].astype(str)
            _f15_outcome = dict(zip(_fm["contact_id"], _fm["outcome"].fillna("")))
            _f15_when = dict(zip(_fm["contact_id"], _fm["start_time"]))

    # In-window 15-min meetings (used by BDS Meeting Detail)
    _f15w_outcome: dict = {}
    _f15w_when: dict = {}
    if not _meetings_in_window.empty:
        _typesw = _meetings_in_window["activity_type"].fillna("").astype(str).str.lower()
        _fmw = _meetings_in_window[_typesw.str.contains("15 min", na=False)].copy()
        if not _fmw.empty:
            _fmw = _fmw.sort_values("start_time", ascending=False, na_position="last") \
                .drop_duplicates(subset="contact_id", keep="first")
            _fmw["contact_id"] = _fmw["contact_id"].astype(str)
            _f15w_outcome = dict(zip(_fmw["contact_id"], _fmw["outcome"].fillna("")))
            _f15w_when = dict(zip(_fmw["contact_id"], _fmw["start_time"]))

    # Strategy meetings — most-recent + total count per contact, ACROSS THE
    # 180-DAY DATA FLOOR (for SDR Lead Detail context). In-window strategy
    # state lives in _strw_outcome / _strw_when below.
    _str_outcome: dict = {}
    _str_when: dict = {}
    _str_count: dict = _dd(int)
    if not meetings_full.empty:
        _types = meetings_full["activity_type"].fillna("").astype(str).str.lower()
        _sm = meetings_full[_types.str.contains("strategy", na=False)].copy()
        if not _sm.empty:
            _sm = _sm.sort_values("start_time", ascending=False, na_position="last")
            _sm["contact_id"] = _sm["contact_id"].astype(str)
            for _cid, _grp in _sm.groupby("contact_id"):
                _str_count[_cid] = int(len(_grp))
                _row = _grp.iloc[0]
                _str_outcome[_cid] = (_row.get("outcome") or "").upper()
                _str_when[_cid] = _row.get("start_time")

    # In-window strategy meetings (used by SME Meeting Detail)
    _strw_outcome: dict = {}
    _strw_when: dict = {}
    if not _meetings_in_window.empty:
        _typesw2 = _meetings_in_window["activity_type"].fillna("").astype(str).str.lower()
        _smw = _meetings_in_window[_typesw2.str.contains("strategy", na=False)].copy()
        if not _smw.empty:
            _smw = _smw.sort_values("start_time", ascending=False, na_position="last") \
                .drop_duplicates(subset="contact_id", keep="first")
            _smw["contact_id"] = _smw["contact_id"].astype(str)
            _strw_outcome = dict(zip(_smw["contact_id"], _smw["outcome"].fillna("").str.upper()))
            _strw_when = dict(zip(_smw["contact_id"], _smw["start_time"]))

    # Team-and-customer exclusion set for all detail tables.
    # Customer signal: lifecycle_stage == "customer" OR contract_tier set
    # (backup signal — catches customers whose lifecycle wasn't promoted).
    _excl_cids: set = set()
    if not marketing.empty:
        for _, _c in marketing.iterrows():
            _email = (_c.get("email") or "").lower()
            if cfg.is_internal_team_contact(_email):
                _excl_cids.add(str(_c.get("hs_id")))
                continue
            if cfg.is_existing_customer(_c.get("lifecycle_stage"),
                                         _c.get("contract_tier")):
                _excl_cids.add(str(_c.get("hs_id")))

    # Deal stage flags per contact
    _won_cids: set = set()
    _won_revenue: dict = {}
    _dq15_cids: set = set()
    _dqstr_cids: set = set()
    if not deals.empty and not contact_deals.empty:
        _won_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_CLOSED_WON), "deal_id"])
        _won_cids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(_won_deal_ids),
                              "contact_id"].astype(str)
        )
        _won_deals_df = deals[deals["dealstage"].isin(cfg.STAGES_CLOSED_WON)]
        _deal_amt = dict(zip(_won_deals_df["deal_id"],
                             _won_deals_df["amount"].fillna(0)))
        for _, _cd in contact_deals.iterrows():
            if _cd["deal_id"] in _deal_amt:
                _cid = str(_cd["contact_id"])
                _won_revenue[_cid] = _won_revenue.get(_cid, 0.0) + float(_deal_amt[_cd["deal_id"]] or 0)
        _dq15_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_15MIN_DQ), "deal_id"])
        _dq15_cids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(_dq15_deal_ids),
                              "contact_id"].astype(str)
        )
        _dqstr_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_STRATEGY_DQ), "deal_id"])
        _dqstr_cids = set(
            contact_deals.loc[contact_deals["deal_id"].isin(_dqstr_deal_ids),
                              "contact_id"].astype(str)
        )

    # Window-label helper used in section captions
    _win_label = f"**Window: {start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}**" \
        if hasattr(start, "strftime") else f"**Window: {start} – {end}**"
    # Defensive fallback for Windows where %-d isn't supported
    try:
        _win_label = f"**Window: {start.strftime('%b %d').lstrip('0').replace(' 0', ' ')} – {end.strftime('%b %d, %Y').lstrip('0').replace(' 0', ' ')}**"
    except Exception:
        _win_label = f"**Window: {start} – {end}**"

    # ----- Section: SDR Performance (Wave 1 + Wave 2) -----
    st.subheader("SDR Performance")
    st.caption(
        f"{_win_label}. Dials, pick-ups, contacts-made + talk time from "
        "**AirCall** (calls placed in window). Appts Booked = unique contacts "
        "in window with a 15-min meeting assigned to this SDR. "
        f"**Pick Up** = call answered. **Contact Made** = answered + "
        f"≥{cfg.AIRCALL_CONNECT_DURATION_SEC}s (real conversation, filters "
        "voicemail). **Booking %** = Appts Booked / Contacts Made."
    )
    sdr = sales_sdr_rollup(
        contacts=marketing,
        calls=aircall_calls,
        meetings=meetings,
        aircall_user_names=cfg.AIRCALL_USER_NAMES,
        excluded_users=cfg.AIRCALL_EXCLUDED_USERS,
        aircall_to_sdr_owner=cfg.AIRCALL_TO_SDR_OWNER,
        connect_duration_sec=cfg.AIRCALL_CONNECT_DURATION_SEC,
        conv_window_hours=cfg.AIRCALL_CONV_TO_DISCO_WINDOW_HOURS,
        lead_window_start=start,
    )
    if sdr.empty:
        st.info("No SDR activity in this window.")
    else:
        display = sdr.copy()
        display["talk_time_min"] = display["talk_time_min"].map(_fmt_minutes)
        display["booking_rate"] = display["booking_rate"].map(_fmt_pct)
        display["median_speed_to_lead_min"] = display["median_speed_to_lead_min"].map(
            lambda x: f"{x:.1f} min" if x is not None and not pd.isna(x) else "—"
        )
        display = display[[
            "user_name", "dials", "pick_ups", "contacts_made", "talk_time_min",
            "appointments_booked", "booking_rate",
            "median_speed_to_lead_min",
        ]].rename(columns={
            "user_name": "SDR",
            "dials": "Dials",
            "pick_ups": "Pick Ups",
            "contacts_made": "Contacts Made",
            "talk_time_min": "Talk Time (min)",
            "appointments_booked": "Appts Booked",
            "booking_rate": "Booking %",
            "median_speed_to_lead_min": "Median Speed",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

    # SDR Lead Detail — every marketing lead with per-contact dial activity + speed
    sdr_rows = []
    for _, _c in marketing.iterrows():
        _cid = str(_c["hs_id"])
        # Skip internal-team / existing-customer contacts (they are not leads
        # the sales team is currently working).
        if _cid in _excl_cids:
            continue
        _stats = _per_contact_calls.get(_cid, {"dials": 0, "pick_ups": 0,
                                                "contacts_made": 0, "talk_sec": 0})
        _spd = _speed_map.get(_cid)
        _f15o = (_f15_outcome.get(_cid) or "").upper()
        _appt = _f15o if _f15o else "Not Booked"
        _self = str(_c.get("sdr_owner") or "") == "1266266951"
        # Skip leads with NO activity (no dials, no booking, no SDR assigned)
        if (_stats["dials"] == 0
            and not _f15o
            and not (_c.get("sdr_owner") or "")):
            continue
        sdr_rows.append({
            "Open": cfg.hubspot_contact_url(_cid),
            "Contact": _c.get("name") or "",
            "SDR": cfg.resolve_owner(_c.get("sdr_owner")),
            "Self Booked": _self,
            "Asset": _c.get("typeform_asset_download") or "",
            "Dials": _stats["dials"],
            "Pick Ups": _stats["pick_ups"],
            "Contacts Made": _stats["contacts_made"],
            "Talk (min)": round(_stats["talk_sec"] / 60.0, 1) if _stats["talk_sec"] else 0,
            "Speed to Lead (min)": (round(_spd, 1) if _spd is not None and not pd.isna(_spd) else None),
            "15-min Status": _appt,
            "15-min When (CT)": "",
        })
    if sdr_rows:
        _sdr_det = pd.DataFrame(sdr_rows)
        # Format CT timestamps via the contact_id -> when map applied to the rows in order
        _when_series = [_f15_when.get(str(_c["hs_id"])) for _, _c in marketing.iterrows()
                        if (str(_c["hs_id"]) in {r.get("Open","").split("/")[-1] for r in sdr_rows})]
        # Simpler approach: rebuild When directly from rows
        _whens = []
        for _, _c in marketing.iterrows():
            _cid = str(_c["hs_id"])
            if _cid in _excl_cids:
                continue
            _stats = _per_contact_calls.get(_cid, {"dials": 0})
            _f15o = _f15_outcome.get(_cid) or ""
            if _stats["dials"] == 0 and not _f15o and not (_c.get("sdr_owner") or ""):
                continue
            _whens.append(_f15_when.get(_cid))
        _sdr_det["15-min When (CT)"] = cfg.format_ct_series(pd.Series(_whens))
        # Sort: Dials desc then Speed asc
        _sdr_det = _sdr_det.sort_values(
            ["Dials", "Speed to Lead (min)"], ascending=[False, True], na_position="last"
        ).reset_index(drop=True)
        with st.expander(f"SDR Lead Detail — {len(_sdr_det)} leads with activity", expanded=False):
            st.dataframe(
                cfg.style_unassigned(
                    _sdr_det,
                    columns=["SDR", "Asset", "15-min Status"],
                    # Green = has a 15-min appointment on record (not just "Not Booked")
                    green_when=lambda r: str(r.get("15-min Status", "")).strip()
                                          not in ("", "Not Booked"),
                ),
                use_container_width=True, hide_index=True,
                column_config={
                    "Open": st.column_config.LinkColumn("Open", display_text="HubSpot ↗"),
                    "Self Booked": st.column_config.CheckboxColumn("Self Booked"),
                },
            )

    st.divider()

    # ----- Section: BDS Performance (Wave 1) -----
    st.subheader("BDS Performance")
    st.caption(
        f"{_win_label}. 15-min Discovery meetings whose **start_time falls in "
        "this window**, grouped by the BDS assigned. BDS holds the Discovery, "
        "qualifies the prospect, and books the Strategy when qualified. "
        "**Show %** = Shows / Appointments · **Booking %** = SME Booked / "
        "Shows · **DQ %** = Disqualified / Shows."
    )
    bds = sales_bds_rollup(
        contacts=marketing,
        meetings=meetings,
        contact_deals=contact_deals,
        deals=deals,
        stages_15min_dq=cfg.STAGES_15MIN_DQ,
    )
    if bds.empty:
        st.info("No BDS activity in this window.")
    else:
        display = bds.copy()
        display["bds_id"] = display["bds_id"].map(cfg.resolve_owner)
        display["show_rate"] = display["show_rate"].map(_fmt_pct)
        display["booking_rate"] = display["booking_rate"].map(_fmt_pct)
        display["dq_rate"] = display["dq_rate"].map(_fmt_pct)
        display = display.rename(columns={
            "bds_id": "BDS",
            "appointments": "Appointments",
            "shows": "Shows",
            "sme_booked": "SME Booked",
            "disqualified": "Disqualified",
            "show_rate": "Show %",
            "booking_rate": "Booking %",
            "dq_rate": "DQ %",
        })
        st.dataframe(
            cfg.style_unassigned(display, columns=["BDS"]),
            use_container_width=True, hide_index=True,
        )

    # BDS Meeting Detail — only contacts with an IN-WINDOW 15-min meeting.
    # Excludes internal-team rows + existing customers (current clients
    # shouldn't appear in the active sales workload).
    bds_rows = []
    bds_whens = []
    for _, _c in marketing.iterrows():
        _cid = str(_c["hs_id"])
        if _cid in _excl_cids:
            continue
        _outcome = _f15w_outcome.get(_cid)
        if not _outcome:
            continue  # only contacts with a 15-min meeting THIS WINDOW
        _has_strat = bool(_strw_outcome.get(_cid))
        _is_dq = _cid in _dq15_cids
        bds_rows.append({
            "Open": cfg.hubspot_contact_url(_cid),
            "Contact": _c.get("name") or "",
            "BDS": cfg.resolve_owner(_c.get("bds")),
            "Asset": _c.get("typeform_asset_download") or "",
            "15-min Outcome": _outcome.upper() if _outcome else "",
            "15-min When (CT)": "",
            "SME Booked After?": _has_strat,
            "DQ'd at 15-min?": _is_dq,
        })
        bds_whens.append(_f15w_when.get(_cid))
    if bds_rows:
        _bds_det = pd.DataFrame(bds_rows)
        _bds_det["15-min When (CT)"] = cfg.format_ct_series(pd.Series(bds_whens))
        _bds_det = _bds_det.sort_values("15-min When (CT)", ascending=False).reset_index(drop=True)
        with st.expander(f"BDS Meeting Detail — {len(_bds_det)} 15-min meetings", expanded=False):
            st.dataframe(
                cfg.style_unassigned(
                    _bds_det, columns=["BDS", "Asset"],
                    # Green = held the 15-min (outcome starts with COMPLETE)
                    green_when=lambda r: str(r.get("15-min Outcome", "")).upper().startswith("COMPLETE"),
                ),
                use_container_width=True, hide_index=True,
                column_config={
                    "Open": st.column_config.LinkColumn("Open", display_text="HubSpot ↗"),
                    "SME Booked After?": st.column_config.CheckboxColumn("SME Booked After?"),
                    "DQ'd at 15-min?": st.column_config.CheckboxColumn("DQ'd at 15-min?"),
                },
            )

    st.divider()

    # ----- Section: SME Performance (Wave 1 + Wave 2) -----
    st.subheader("SME Performance")
    st.caption(
        f"{_win_label}. Strategy meetings whose **start_time falls in this "
        "window**, grouped by the SME assigned. Deals closed = won deals "
        "whose closedate (or stage-entry date for DIY/90-Day) is in window. "
        "**First Close** = closed on the first Strategy call · **FU Close** "
        "= closed after a follow-up call. **Close %** = total closed / "
        "showed · **DQ %** = disqualified / showed."
    )
    # Filter deals to those actually CLOSED in window so the rollup doesn't
    # count old closes that merely got hs_lastmodifieddate touched (which is
    # what load_deals_in_window filters on). closedate — or stage_entry_date
    # for DIY/90-Day stages with no closedate — must be in [start, end].
    if not deals.empty:
        _no_close = set(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE)
        _cdt = pd.to_datetime(deals.get("closedate"), utc=True, errors="coerce").dt.date
        _sed = (pd.to_datetime(deals["stage_entry_date"], utc=True, errors="coerce").dt.date
                 if "stage_entry_date" in deals.columns else pd.Series([None] * len(deals), index=deals.index, dtype=object))
        _cre = pd.to_datetime(deals.get("createdate"), utc=True, errors="coerce").dt.date
        _m_close = _cdt.between(start, end)
        _no_close_mask = deals["dealstage"].isin(_no_close) & _cdt.isna()
        _m_stage = _no_close_mask & _sed.between(start, end)
        _m_create = _no_close_mask & _sed.isna() & _cre.between(start, end)
        deals_for_sme = deals[_m_close | _m_stage | _m_create]
    else:
        deals_for_sme = deals
    sme = sales_sme_rollup(
        contacts=marketing,
        meetings=meetings,
        contact_deals=contact_deals,
        deals=deals_for_sme,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        stages_strategy_dq=cfg.STAGES_STRATEGY_DQ,
        today=date.today(),
        full_monthly=cfg.FULL_MONTHLY, full_term_months=cfg.FULL_TERM_MONTHS,
        ninety_day_amount=cfg.NINETY_DAY_AMOUNT, diy_monthly=cfg.DIY_MONTHLY,
        pt_multiplier=cfg.PT_MULTIPLIER,
    )
    if sme.empty:
        st.info("No SME activity in this window.")
    else:
        display = sme.copy()
        display["sme_id"] = display["sme_id"].map(cfg.resolve_owner)
        display["show_rate"] = display["show_rate"].map(_fmt_pct)
        display["close_rate"] = display["close_rate"].map(_fmt_pct)
        display["first_close_rate"] = display["first_close_rate"].map(_fmt_pct)
        display["fu_close_rate"] = display["fu_close_rate"].map(_fmt_pct)
        display["dq_rate"] = display["dq_rate"].map(_fmt_pct)
        display["revenue"] = display["revenue"].map(_fmt_money)
        display = display[[
            "sme_id", "appointments", "showed", "deals_closed",
            "first_closes", "fu_closes", "disqualified",
            "show_rate", "close_rate", "first_close_rate", "fu_close_rate",
            "dq_rate", "revenue",
        ]].rename(columns={
            "sme_id": "SME",
            "appointments": "Appointments",
            "showed": "Showed",
            "deals_closed": "Closed",
            "first_closes": "First Close",
            "fu_closes": "FU Close",
            "disqualified": "DQ",
            "show_rate": "Show %",
            "close_rate": "Close %",
            "first_close_rate": "First %",
            "fu_close_rate": "FU %",
            "dq_rate": "DQ %",
            "revenue": "Revenue",
        })
        st.dataframe(
            cfg.style_unassigned(display, columns=["SME"]),
            use_container_width=True, hide_index=True,
        )

    # SME Meeting Detail — only contacts with an IN-WINDOW Strategy meeting.
    # Same team/customer exclusion as BDS Meeting Detail.
    sme_rows = []
    sme_whens = []
    for _, _c in marketing.iterrows():
        _cid = str(_c["hs_id"])
        if _cid in _excl_cids:
            continue
        _outcome = _strw_outcome.get(_cid)
        if not _outcome:
            continue  # only contacts with a Strategy meeting THIS WINDOW
        _won = _cid in _won_cids
        _dq = _cid in _dqstr_cids
        _cnt = _str_count.get(_cid, 0)
        if _won:
            _deal_status = "Closed-Won"
            _close_type = "FU Close" if _cnt >= 2 else "First Close"
        elif _dq:
            _deal_status = "DQ"
            _close_type = ""
        else:
            _deal_status = "Open / No deal"
            _close_type = ""
        _rev = _won_revenue.get(_cid, 0.0)
        sme_rows.append({
            "Open": cfg.hubspot_contact_url(_cid),
            "Contact": _c.get("name") or "",
            "SME": cfg.resolve_owner(_c.get("sme")),
            "Asset": _c.get("typeform_asset_download") or "",
            "Strategy Outcome": _outcome,
            "Strategy When (CT)": "",
            "Strategy Mtgs": _cnt,
            "Deal Status": _deal_status,
            "Close Type": _close_type,
            "Revenue": _fmt_money(_rev) if _won and _rev else ("—" if not _won else "$0"),
        })
        sme_whens.append(_strw_when.get(_cid))
    if sme_rows:
        _sme_det = pd.DataFrame(sme_rows)
        _sme_det["Strategy When (CT)"] = cfg.format_ct_series(pd.Series(sme_whens))
        _sme_det = _sme_det.sort_values("Strategy When (CT)", ascending=False).reset_index(drop=True)
        with st.expander(f"SME Meeting Detail — {len(_sme_det)} Strategy meetings", expanded=False):
            st.dataframe(
                cfg.style_unassigned(
                    _sme_det, columns=["SME", "Asset"],
                    # Green = closed-won (the goal)
                    green_when=lambda r: str(r.get("Deal Status", "")) == "Closed-Won",
                ),
                use_container_width=True, hide_index=True,
                column_config={
                    "Open": st.column_config.LinkColumn("Open", display_text="HubSpot ↗"),
                },
            )

    st.divider()

    # ----- Section: Marketing Lead Detail (existing) -----
    st.subheader("Marketing Lead Detail")
    st.caption(
        f"{_win_label}. One row per marketing lead with a known asset "
        "(submitted in this window). Blank-asset rows (past opt-ins and "
        "non-marketing conversions) are excluded so every name traces back "
        "to a campaign. Sorted by submission date."
    )
    if marketing.empty:
        st.info("No marketing leads in this window.")
        return

    # Only leads with a real marketing asset. A blank asset means the contact
    # re-entered via a past opt-in or a non-marketing path, which is noise in a
    # "where did this lead come from" view.
    _asset = marketing["typeform_asset_download"].fillna("").astype(str).str.strip()
    mkt_detail = marketing[_asset != ""].copy()
    if mkt_detail.empty:
        st.info("No asset-attributed marketing leads in this window.")
        return
    if deals.empty or contact_deals.empty:
        st.info("No deal data available — drill-down hidden.")
        return

    deals_by_contact = contact_deals.merge(
        deals[["deal_id", "dealstage", "amount", "createdate"]],
        on="deal_id", how="left",
    )
    latest_deal = (
        deals_by_contact.sort_values("createdate", ascending=False)
        .drop_duplicates("contact_id")
        .rename(columns={"contact_id": "hs_id"})
    )
    detail = mkt_detail.merge(
        latest_deal[["hs_id", "dealstage", "amount"]],
        on="hs_id", how="left",
    )

    detail["_sort_ts"] = pd.to_datetime(
        detail["typeform_submission_date"], utc=True, errors="coerce"
    )
    detail = detail.sort_values("_sort_ts", ascending=False, na_position="last")
    detail = detail.drop(columns=["_sort_ts"])

    detail["sdr_owner"] = detail["sdr_owner"].map(cfg.resolve_owner)
    detail["bds"] = detail["bds"].map(cfg.resolve_owner)
    detail["hubspot_link"] = detail["hs_id"].apply(cfg.hubspot_contact_url)
    detail["typeform_submission_date"] = cfg.format_ct_series(
        detail["typeform_submission_date"]
    )
    detail["fifteen_min_call_date"] = cfg.format_ct_series(
        detail["fifteen_min_call_date"]
    )
    detail = detail[[
        "hubspot_link",
        "name", "email", "typeform_asset_download", "typeform_submission_date",
        "fifteen_min_call_date", "lifecycle_stage",
        "sdr_owner", "bds", "dealstage", "amount",
    ]].rename(columns={
        "hubspot_link": "Open",
        "typeform_asset_download": "Asset",
        "typeform_submission_date": "Submitted (CT)",
        "fifteen_min_call_date": "15-min Call Date (CT)",
        "lifecycle_stage": "Lifecycle",
        "sdr_owner": "SDR Owner",
        "bds": "BDS",
        "dealstage": "Current Stage",
        "amount": "Deal $",
    })
    st.dataframe(
        cfg.style_unassigned(detail,
                              columns=["SDR Owner", "BDS", "Asset", "Current Stage"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Open": st.column_config.LinkColumn(
                "Open",
                help="Open contact in HubSpot",
                display_text="HubSpot ↗",
            ),
        },
    )

    # ----- Section: Closed Deals YTD (existing) -----
    st.divider()
    st.subheader("Closed Deals — Year to Date")
    st.caption("Every closed-won deal since Jan 1, with original asset attribution + sales cycle days.")
    deals_table = build_closed_deals_table(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        today=date.today(),
    )
    if deals_table.empty:
        st.info("No closed-won deals YTD.")
    else:
        show_marketing_only = st.checkbox(
            "Show marketing-attributed deals only",
            value=False,
            key="sales_closed_deals_marketing_filter",
        )
        if show_marketing_only and not deals_table.empty:
            deals_table = deals_table[deals_table["is_marketing"] == True]

        display_ytd = deals_table.copy()
        display_ytd["hubspot_link"] = display_ytd["hs_id"].apply(cfg.hubspot_contact_url)
        display_ytd["sdr_owner"] = display_ytd["sdr_owner"].map(cfg.resolve_owner)
        display_ytd["bds"] = display_ytd["bds"].map(cfg.resolve_owner)
        display_ytd["sme"] = display_ytd["sme"].map(cfg.resolve_owner)
        display_ytd["closedate"] = cfg.format_ct_series(
            display_ytd["closedate"], fmt=cfg.DEFAULT_DATE_FORMAT
        )
        display_ytd["deal_amount"] = display_ytd["deal_amount"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—")
        display_ytd["sales_cycle_days"] = display_ytd["sales_cycle_days"].map(
            lambda x: f"{int(x)}" if pd.notna(x) else "—")
        display_ytd = display_ytd[[
            "hubspot_link", "closedate", "contact_name", "email", "typeform",
            "group", "tier", "source", "deal_amount", "sales_cycle_days",
            "sdr_owner", "bds", "sme",
        ]].rename(columns={
            "hubspot_link": "Open",
            "closedate": "Closed",
            "contact_name": "Contact",
            "email": "Email",
            "typeform": "Typeform",
            "group": "Group",
            "tier": "Plan",
            "source": "Source",
            "deal_amount": "Deal $",
            "sales_cycle_days": "Cycle (days)",
            "sdr_owner": "SDR",
            "bds": "BDS",
            "sme": "SME",
        })
        total_in_view = int(len(display_ytd))
        marketing_count = int(deals_table["is_marketing"].sum()) if "is_marketing" in deals_table.columns else None
        if show_marketing_only:
            st.caption(f"Showing {total_in_view} marketing-attributed deal(s).")
        else:
            if marketing_count is not None:
                st.caption(
                    f"Showing {total_in_view} closed deal(s) total · "
                    f"{marketing_count} marketing-attributed · "
                    f"{total_in_view - marketing_count} non-marketing."
                )
            else:
                st.caption(f"Showing {total_in_view} closed deal(s) total.")
        st.dataframe(
            cfg.style_unassigned(display_ytd,
                                  columns=["SDR", "BDS", "SME", "Group",
                                           "Plan", "Source", "Typeform"]),
            use_container_width=True, hide_index=True,
            column_config={
                "Open": st.column_config.LinkColumn(
                    "Open", help="Open contact in HubSpot",
                    display_text="HubSpot ↗"),
            },
        )
