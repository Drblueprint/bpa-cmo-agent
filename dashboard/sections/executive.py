"""EXECUTIVE tab rendering — 3-row funnel view + per-rep tables."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dashboard import config as cfg
from dashboard.data.fb_loader import load_fb_insights
from dashboard.data.hubspot_loader import (
    load_contact_deals,
    load_deals_in_window,
    load_marketing_contacts,
    load_meetings_for_contacts,
    load_meetings_in_window,
    load_contacts_by_ids,
    load_closed_deals_ytd,
    load_list_memberships,
)
from dashboard.data.reconcile import (
    executive_kpis,
    executive_sdr_rollup,
    executive_sme_rollup,
    build_closed_deals_table,
    compute_ytd_money,
    compute_close_commissions,
    group_marketing_metrics,
    group_funnel_costs,
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


def _fmt_days(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(x)} days"


def render_executive(start: date, end: date) -> None:
    floor_days = st.session_state.get("data_floor_days_back", 180)
    # Group filter removed per Dr. Gumm — Executive is always "All sources".
    group_filter = "All"

    # --- Load data (try/except per source) ---
    try:
        fb = load_fb_insights(start, end)
    except Exception as e:
        st.warning(f"FB Ads unavailable: {e}")
        fb = pd.DataFrame(columns=["campaign_name", "group", "spend",
                                   "impressions", "clicks", "fb_leads"])
    try:
        contacts = load_marketing_contacts(start, end)
    except Exception as e:
        st.warning(f"HubSpot contacts unavailable: {e}")
        contacts = pd.DataFrame()
    try:
        contact_deals = load_contact_deals(contacts["hs_id"].tolist()) \
            if not contacts.empty else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception as e:
        st.warning(f"HubSpot contact-deal associations unavailable: {e}")
        contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    try:
        deals = load_deals_in_window(start, end, data_floor_days_back=floor_days)
    except Exception as e:
        st.warning(f"HubSpot deals unavailable: {e}")
        deals = pd.DataFrame()
    try:
        meetings = load_meetings_for_contacts(contacts["hs_id"].tolist(),
                                              data_floor_days_back=floor_days) \
            if not contacts.empty else pd.DataFrame(columns=[
                "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
            ])
    except Exception as e:
        st.warning(f"HubSpot meetings unavailable: {e}")
        meetings = pd.DataFrame(columns=[
            "meeting_id", "contact_id", "activity_type", "outcome", "start_time"
        ])

    # Closed-deal attribution: pull any contact tied to a closed-won deal in
    # the window who isn't already in our fresh-leads pull. Sales cycles can
    # be 3-6 months; this preserves asset attribution for long-cycle closes.
    try:
        from dashboard.data.hubspot_loader import load_contacts_by_ids
        if not deals.empty and not contact_deals.empty:
            won_deal_ids = set(deals.loc[deals["dealstage"].isin(cfg.STAGES_CLOSED_WON), "deal_id"])
            won_contact_ids = set(
                contact_deals.loc[contact_deals["deal_id"].isin(won_deal_ids), "contact_id"].astype(str)
            )
            known_ids = set(contacts["hs_id"].astype(str)) if not contacts.empty else set()
            missing_ids = list(won_contact_ids - known_ids)
            if missing_ids:
                extra = load_contacts_by_ids(missing_ids)
                if not extra.empty:
                    contacts = pd.concat([contacts, extra], ignore_index=True)
    except Exception as e:
        st.warning(f"Closed-deal attribution lookup failed: {e}")

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

    # === YTD closed-deal data (separate pull -- always Jan 1 -> today) ===
    try:
        deals_ytd, contact_deals_ytd, contacts_ytd = load_closed_deals_ytd(
            closed_won_stages=tuple(cfg.STAGES_CLOSED_WON),
        )
    except Exception as e:
        st.warning(f"YTD closed deals unavailable: {e}")
        deals_ytd = pd.DataFrame()
        contact_deals_ytd = pd.DataFrame(columns=["contact_id", "deal_id"])
        contacts_ytd = pd.DataFrame()

    ytd_money = compute_ytd_money(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
    )

    # YTD ad spend for Marketing CAC calculation
    from datetime import date as _date
    try:
        ytd_ad_spend_df = load_fb_insights(
            _date(_date.today().year, 1, 1), _date.today(),
            time_increment_days=None,  # one row per campaign, full window
        )
        ytd_total_ad_spend = float(ytd_ad_spend_df["spend"].sum()) \
            if not ytd_ad_spend_df.empty else 0.0
    except Exception as e:
        st.warning(f"YTD ad spend unavailable: {e}")
        ytd_total_ad_spend = 0.0

    mkt_customers = ytd_money["mkt_new_customers"]
    marketing_cac = (ytd_total_ad_spend / mkt_customers) if mkt_customers else None

    # YTD sales commissions (closed-deal only) for Blended CAC.
    try:
        ytd_deals_table = build_closed_deals_table(
            deals_ytd, contact_deals_ytd, contacts_ytd,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
            stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
        )
        commissions = compute_close_commissions(
            ytd_deals_table,
            sdr_close=cfg.SDR_CLOSE_COMMISSION,
            bds_close=cfg.BDS_CLOSE_COMMISSION,
            sme_close=cfg.SME_CLOSE_COMMISSION,
            flat_close=cfg.FLAT_CLOSE_COMMISSION,
        )
    except Exception as e:
        st.warning(f"Commission calc failed: {e}")
        commissions = {"total": 0.0, "sdr_total": 0.0, "bds_total": 0.0,
                       "sme_total": 0.0, "flat_total": 0.0, "n_deals": 0}

    total_customers = ytd_money["total_new_customers"]
    avg_commission = (commissions["total"] / total_customers) if total_customers else None
    blended_cac = ((ytd_total_ad_spend + commissions["total"]) / total_customers) \
        if total_customers else None

    kpis = executive_kpis(
        fb=fb, contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        group_filter=group_filter,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        stages_closed_won=cfg.STAGES_CLOSED_WON,
        sdr_payroll_monthly=cfg.SDR_PAYROLL_MONTHLY,
        sme_payroll_monthly=cfg.SME_PAYROLL_MONTHLY,
    )

    # === ROW 1 — top KPIs (mirrors MARKETING tab) ===
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ad Spend", _fmt_money(kpis["total_ad_spend"]))
    c2.metric("Marketing Leads", _fmt_int(kpis["new_leads"]),
              help="HubSpot contacts whose typeform was submitted in the window. "
                   "Falls back to FB lead count for groups that don't use a "
                   "typeform (e.g., TheraRay).")
    c3.metric("CPL", _fmt_money(kpis["cpl"]), help="Spend / Marketing Leads")
    c4.metric("15-min Calls Booked", _fmt_int(kpis["discovery_booked"]),
              help="15-min discovery meetings booked in the window.")

    # Per-group breakdown of the 4 KPIs above (Chiro, EMX, PT Recovery, TheraRay, ...)
    try:
        group_metrics = group_marketing_metrics(
            fb, contacts, contact_deals, deals,
            asset_to_group=cfg.ASSET_TO_GROUP,
            stages_15min_booked=cfg.STAGES_15MIN_BOOKED | cfg.STAGES_15MIN_HELD,
            hyros=None,
            stages_strategy=cfg.STAGES_STRATEGY_BOOKED | cfg.STAGES_STRATEGY_HELD,
            stages_closed_won=cfg.STAGES_CLOSED_WON,
            meetings=meetings,
        )
        if not group_metrics.empty:
            bd = group_metrics.copy()
            bd["cpl_calc"] = bd.apply(
                lambda r: (r["spend"] / r["marketing_leads"])
                if r["marketing_leads"] else None, axis=1,
            )
            bd["Spend"] = bd["spend"].map(_fmt_money)
            bd["Marketing Leads"] = bd["marketing_leads"].map(_fmt_int)
            bd["CPL"] = bd["cpl_calc"].map(_fmt_money)
            bd["15-min Calls"] = bd["calls_booked"].map(_fmt_int)
            bd = bd[["group", "Spend", "Marketing Leads", "CPL", "15-min Calls"]] \
                .rename(columns={"group": "Group"})
            with st.expander("Breakdown by group", expanded=True):
                st.dataframe(bd, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Group breakdown unavailable: {e}")

    st.divider()

    # === ROW 2 — CONVERSIONS ===
    st.subheader("Conversions")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Schedule Rate", _fmt_pct(kpis["schedule_rate"]),
              delta=f"{kpis['discovery_booked']} / {kpis['new_leads']}",
              delta_color="off",
              help="Discovery (15-min) calls booked ÷ New Leads. Phase A definition; "
                   "will upgrade to leads-worked denominator in Phase B with AirCall data.")
    c2.metric("Discovery Show %", _fmt_pct(kpis["discovery_show_rate"]),
              delta=f"{kpis['discovery_held']} / {kpis['discovery_booked']}",
              delta_color="off",
              help="15-min meetings that COMPLETED ÷ total 15-min meetings.")
    c3.metric("Disco → SME Set %", _fmt_pct(kpis["sme_set_rate"]),
              delta=f"{kpis['sme_booked']} / {kpis['discovery_held']}",
              delta_color="off",
              help="Strategy meetings booked ÷ Discovery meetings completed.")
    c4.metric("SME Show %", _fmt_pct(kpis["sme_show_rate"]),
              delta=f"{kpis['sme_held']} / {kpis['sme_booked']}",
              delta_color="off",
              help="Strategy meetings COMPLETED ÷ Strategy meetings booked.")
    c5.metric("Close Rate", _fmt_pct(kpis["close_rate"]),
              delta=f"{kpis['closed_won_from_funnel']} / {kpis['sme_held']}",
              delta_color="off",
              help="Closed-won contacts who also held a Strategy ÷ Strategy "
                   "meetings completed. Funnel-intersected so the rate stays "
                   "≤ 100%. Total YTD closes (incl. ones without a Strategy "
                   "meeting on record) show in the Money section below.")

    # Per-group breakdown of the 5 conversion rates (cells show rate · numerator/denominator)
    try:
        groups_seen = list(group_metrics["group"]) if 'group_metrics' in locals() and not group_metrics.empty else []
        # Stable order, drop empty/None
        preferred = ["Chiro", "EMX", "PT Recovery", "TheraRay", "NLAP"]
        groups_to_show = [g for g in preferred if g in groups_seen] + \
                          [g for g in groups_seen if g not in preferred and g]

        def _cell(rate, num, den):
            if rate is None or den in (0, None):
                return f"— ({num}/{den or 0})"
            return f"{rate*100:.0f}% ({num}/{den})"

        conv_rows = []
        for g in groups_to_show:
            kg = executive_kpis(
                fb=fb, contacts=contacts, meetings=meetings,
                contact_deals=contact_deals, deals=deals,
                group_filter=g,
                asset_to_group=cfg.ASSET_TO_GROUP,
                group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
                stages_closed_won=cfg.STAGES_CLOSED_WON,
                sdr_payroll_monthly=cfg.SDR_PAYROLL_MONTHLY,
                sme_payroll_monthly=cfg.SME_PAYROLL_MONTHLY,
            )
            # Suppress groups with no leads + no funnel activity in this
            # window — keeps the table clean and avoids misleading
            # all-zero rows (e.g., TheraRay uses a different funnel
            # without 15-min Discovery / Strategy meetings).
            if (kg["new_leads"] == 0
                and kg["discovery_booked"] == 0
                and kg["sme_booked"] == 0
                and kg["closed_won"] == 0):
                continue
            conv_rows.append({
                "Group": g,
                "Leads": kg["new_leads"],
                "Schedule %": _cell(kg["schedule_rate"], kg["discovery_booked"], kg["new_leads"]),
                "Discovery Show %": _cell(kg["discovery_show_rate"], kg["discovery_held"], kg["discovery_booked"]),
                "Disco → SME Set %": _cell(kg["sme_set_rate"], kg["sme_booked"], kg["discovery_held"]),
                "SME Show %": _cell(kg["sme_show_rate"], kg["sme_held"], kg["sme_booked"]),
                "Close %": _cell(kg["close_rate"], kg["closed_won_from_funnel"], kg["sme_held"]),
            })
        if conv_rows:
            with st.expander("Conversions by group", expanded=True):
                st.dataframe(pd.DataFrame(conv_rows), use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Conversion breakdown unavailable: {e}")

    st.divider()

    # === MONEY — YEAR TO DATE ===
    st.subheader("Money — Year to Date (Total)")
    st.caption("All closed-won deals since Jan 1 — includes sales outreach and referrals.")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("New Revenue", _fmt_money(ytd_money["total_new_revenue"]))
    t2.metric("Avg Deal Size", _fmt_money(ytd_money["total_avg_deal_size"]))
    t3.metric("New Customers", _fmt_int(ytd_money["total_new_customers"]))
    t4.metric("Sales Cycle (median)",
              _fmt_days(ytd_money["total_sales_cycle_median"]),
              help="Median days from typeform submission to close. Excludes "
                   "non-marketing leads (no submission date).")

    st.subheader("Money — Year to Date (From Marketing)")
    st.caption("Subset: closed-won deals attributed to marketing efforts only.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Marketing Revenue", _fmt_money(ytd_money["mkt_new_revenue"]))
    m2.metric("Marketing Avg Deal", _fmt_money(ytd_money["mkt_avg_deal_size"]))
    m3.metric("Marketing Customers", _fmt_int(ytd_money["mkt_new_customers"]))
    m4.metric("Marketing Sales Cycle",
              _fmt_days(ytd_money["mkt_sales_cycle_median"]))
    m5.metric("Marketing CAC",
              _fmt_money(marketing_cac),
              help=f"YTD ad spend ({_fmt_money(ytd_total_ad_spend)}) ÷ "
                   f"marketing customers ({_fmt_int(mkt_customers)}). "
                   f"Ad-only — sales team commissions/payouts not included here.")

    # === CUSTOMER ACQUISITION COST ===
    st.subheader("Customer Acquisition Cost — Year to Date")
    st.caption(
        "Blended CAC layers sales-team close commissions on top of ad spend. "
        "Commissions are closed-deal only (SDR warm $200 / cold $400, BDS $300, "
        "SME Chiro $2,000 · PT/EMX/MUDA $1,000, Gerri $25)."
    )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Marketing CAC (ad-only)", _fmt_money(marketing_cac),
              help=f"YTD ad spend ÷ marketing customers ({_fmt_int(mkt_customers)}).")
    k2.metric("Sales Commissions (YTD)", _fmt_money(commissions["total"]),
              help=f"Total close commissions on {_fmt_int(commissions['n_deals'])} "
                   f"closed deals. SDR {_fmt_money(commissions['sdr_total'])} · "
                   f"BDS {_fmt_money(commissions['bds_total'])} · "
                   f"SME {_fmt_money(commissions['sme_total'])} · "
                   f"Gerri {_fmt_money(commissions['flat_total'])}.")
    k3.metric("Avg Commission / Close", _fmt_money(avg_commission),
              help=f"Commissions ÷ all closed customers ({_fmt_int(total_customers)}).")
    k4.metric("Blended CAC", _fmt_money(blended_cac),
              help=f"(YTD ad spend {_fmt_money(ytd_total_ad_spend)} + commissions "
                   f"{_fmt_money(commissions['total'])}) ÷ all customers "
                   f"({_fmt_int(total_customers)}). Excludes fixed payroll.")

    # --- Cost per Stage by Source ---
    def _render_funnel_costs(window_start, window_end, label: str):
        try:
            # load_marketing_contacts now filters by recent_conversion_date
            # (the real form-submit event timestamp — survived the Apr 7
            # bulk-stamp). No extra filter needed here.
            typeform_contacts = load_marketing_contacts(window_start, window_end)
            tr_contacts = pd.DataFrame()
            try:
                memberships = load_list_memberships(cfg.THERARAY_HUBSPOT_LIST_ID)
                if not memberships.empty:
                    mt = pd.to_datetime(memberships["membership_timestamp"],
                                          utc=True, errors="coerce")
                    ws = pd.Timestamp(year=window_start.year,
                                       month=window_start.month,
                                       day=window_start.day, tz="UTC")
                    we = pd.Timestamp(year=window_end.year,
                                       month=window_end.month,
                                       day=window_end.day, tz="UTC") + pd.Timedelta(days=1)
                    in_win = memberships[(mt >= ws) & (mt < we)]
                    ids_in = in_win["contact_id"].tolist()
                    if ids_in:
                        tr_contacts = load_contacts_by_ids(ids_in)
                        if not tr_contacts.empty:
                            tr_contacts = tr_contacts[
                                ~tr_contacts["email"].fillna("").str.lower()
                                .isin(cfg.MARKETING_EXCLUDED_EMAILS)
                            ].copy()
                        if not tr_contacts.empty:
                            tr_contacts["typeform_asset_download"] = "TheraRay FB Lead"
                            cfg.ASSET_TO_GROUP["TheraRay FB Lead"] = "TheraRay"
            except Exception:
                pass
            if not tr_contacts.empty:
                if typeform_contacts.empty:
                    all_contacts = tr_contacts
                else:
                    # TheraRay rows FIRST so dedup keeps the tagged
                    # version (otherwise an existing-contact row with no
                    # typeform asset wins and TheraRay routing breaks).
                    all_contacts = pd.concat(
                        [tr_contacts, typeform_contacts], ignore_index=True
                    ).drop_duplicates(subset="hs_id", keep="first").reset_index(drop=True)
                # Belt + suspenders: force the TheraRay tag onto any
                # contact whose hs_id is in the list-membership window.
                _tr_ids = set(tr_contacts["hs_id"].astype(str))
                _mask = all_contacts["hs_id"].astype(str).isin(_tr_ids)
                all_contacts.loc[_mask, "typeform_asset_download"] = "TheraRay FB Lead"
            else:
                all_contacts = typeform_contacts

            fb_win = load_fb_insights(window_start, window_end,
                                       time_increment_days=None)
            meetings_win = load_meetings_in_window(window_start, window_end)

            # Filter YTD-loaded deals to those closed inside this window
            # (closedate, or stage-entry date for DIY/90-Day).
            if not deals_ytd.empty:
                no_close_set = set(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE)
                cdt = pd.to_datetime(deals_ytd.get("closedate"), utc=True,
                                      errors="coerce").dt.date
                if "stage_entry_date" in deals_ytd.columns:
                    sed = pd.to_datetime(deals_ytd["stage_entry_date"],
                                          utc=True, errors="coerce").dt.date
                else:
                    sed = pd.Series([None] * len(deals_ytd),
                                     index=deals_ytd.index, dtype=object)
                cre = pd.to_datetime(deals_ytd.get("createdate"), utc=True,
                                      errors="coerce").dt.date
                m_close = cdt.between(window_start, window_end)
                no_close_mask = deals_ytd["dealstage"].isin(no_close_set) & cdt.isna()
                m_stage = no_close_mask & sed.between(window_start, window_end)
                m_create = (no_close_mask & sed.isna()
                            & cre.between(window_start, window_end))
                deals_win = deals_ytd[m_close | m_stage | m_create]
            else:
                deals_win = deals_ytd

            # Build the marketing-attributed closed-deals table for this window
            # so closed_won counts match the Marketing Customers KPI.
            cdt = build_closed_deals_table(
                deals_win, contact_deals_ytd, contacts_ytd,
                asset_to_group=cfg.ASSET_TO_GROUP,
                group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
                source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
                stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
            )
            funnel = group_funnel_costs(
                fb_ytd=fb_win,
                contacts_ytd=all_contacts,
                meetings_ytd=meetings_win,
                deals_ytd=deals_win,
                contact_deals_ytd=contact_deals_ytd,
                asset_to_group=cfg.ASSET_TO_GROUP,
                stages_closed_won=cfg.STAGES_CLOSED_WON,
                closed_deals_table=cdt,
            )
            if funnel.empty:
                return
            disp = funnel.copy()
            disp["ad_spend"] = disp["ad_spend"].map(_fmt_money)
            disp["leads"] = disp["leads"].map(_fmt_int)
            disp["cpl"] = disp["cpl"].map(_fmt_money)
            disp["fifteen_booked"] = disp["fifteen_booked"].map(_fmt_int)
            disp["cost_per_fifteen_booked"] = disp["cost_per_fifteen_booked"].map(_fmt_money)
            disp["strategy_booked"] = disp["strategy_booked"].map(_fmt_int)
            disp["cost_per_strategy_booked"] = disp["cost_per_strategy_booked"].map(_fmt_money)
            disp["closed_won"] = disp["closed_won"].map(_fmt_int)
            disp["cost_per_close"] = disp["cost_per_close"].map(_fmt_money)
            disp = disp.rename(columns={
                "group": "Source",
                "ad_spend": "Ad Spend",
                "leads": "Leads",
                "cpl": "CPL",
                "fifteen_booked": "15-min Booked",
                "cost_per_fifteen_booked": "Cost / 15-min",
                "strategy_booked": "Strategy Booked",
                "cost_per_strategy_booked": "Cost / Strategy",
                "closed_won": "Closed-Won",
                "cost_per_close": "Cost / Close",
            })
            st.markdown(f"**Cost per Stage by Source — {label}**")
            st.caption(
                f"{window_start.strftime('%b %d, %Y')} → "
                f"{window_end.strftime('%b %d, %Y')}. **Leads** = contacts "
                "whose HubSpot **recent_conversion_date** (real form / meeting-"
                "link submission event) falls in this window. Counts are "
                "unique contacts reaching each stage; Cost / X = Ad Spend ÷ X."
            )
            st.dataframe(disp, use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Cost-per-stage ({label}) unavailable: {e}")

    _today = _date.today()
    _year_start = _date(_today.year, 1, 1)
    _render_funnel_costs(_year_start, _today, "Year to Date")

    st.divider()

    # === BY-REP TABLES ===
    contacts_for_reps = contacts.copy()
    if group_filter != "All" and not contacts_for_reps.empty:
        contacts_for_reps["group"] = contacts_for_reps["typeform_asset_download"] \
            .map(cfg.ASSET_TO_GROUP)
        contacts_for_reps = contacts_for_reps[contacts_for_reps["group"] == group_filter]

    # SDR table — full width
    st.subheader("SDR Performance")
    st.caption("SDR books the 15-min discovery call. Tracks: leads worked → "
               "discovery booked → discovery held.")
    sdr = executive_sdr_rollup(contacts_for_reps, meetings)
    if sdr.empty:
        st.info("No SDR data for this window.")
    else:
        sdr_display = sdr.copy()
        sdr_display["sdr_id"] = sdr_display["sdr_id"].map(cfg.resolve_owner)
        sdr_display["schedule_rate"] = sdr_display["schedule_rate"].map(_fmt_pct)
        sdr_display["show_rate"] = sdr_display["show_rate"].map(_fmt_pct)
        sdr_display = sdr_display.rename(columns={
            "sdr_id": "SDR Owner",
            "leads_worked": "Leads Worked",
            "discovery_booked": "Discovery Booked",
            "schedule_rate": "Schedule %",
            "discovery_held": "Discovery Held",
            "show_rate": "Show %",
        })
        st.dataframe(sdr_display, use_container_width=True, hide_index=True)

    # === Lead Detail — every marketing lead in window with status ===
    if not contacts_for_reps.empty:
        leads = contacts_for_reps.copy()
        # Self booking flag — sdr_owner mapped to Self Booking ID
        leads["self_booking"] = (
            leads["sdr_owner"].fillna("").astype(str) == "1266266951"
        )
        # Most recent 15-min meeting per contact (any outcome)
        if not meetings.empty:
            types_m = meetings["activity_type"].fillna("").astype(str).str.lower()
            fifteen = meetings[types_m.str.contains("15 min", na=False)].copy()
            if not fifteen.empty:
                fifteen = fifteen.sort_values(
                    "start_time", ascending=False, na_position="last"
                ).drop_duplicates(subset="contact_id", keep="first")
                fifteen["contact_id"] = fifteen["contact_id"].astype(str)
                m_outcome = dict(zip(fifteen["contact_id"], fifteen["outcome"].fillna("")))
                m_when = dict(zip(fifteen["contact_id"], fifteen["start_time"]))
            else:
                m_outcome, m_when = {}, {}
        else:
            m_outcome, m_when = {}, {}

        def _status(hs_id) -> str:
            o = (m_outcome.get(str(hs_id)) or "").upper()
            if not o: return "Not Booked"
            return o

        leads["meeting_status"] = leads["hs_id"].apply(_status)
        leads["meeting_when_raw"] = leads["hs_id"].astype(str).map(m_when)
        leads["meeting_when"] = cfg.format_ct_series(leads["meeting_when_raw"])
        leads["group"] = leads["typeform_asset_download"].map(cfg.ASSET_TO_GROUP).fillna("")
        leads["sdr_name"] = leads["sdr_owner"].map(cfg.resolve_owner)
        leads["bds_name"] = leads["bds"].map(cfg.resolve_owner)
        leads["hubspot_link"] = leads["hs_id"].apply(cfg.hubspot_contact_url)
        # Sort: newest typeform submission first
        leads["_sort"] = pd.to_datetime(
            leads["typeform_submission_date"], utc=True, errors="coerce",
        )
        leads = leads.sort_values("_sort", ascending=False, na_position="last")
        detail = leads[[
            "hubspot_link", "name", "email",
            "typeform_asset_download", "group",
            "sdr_name", "self_booking", "meeting_status", "meeting_when",
            "bds_name", "lifecycle_stage",
        ]].rename(columns={
            "hubspot_link": "Open",
            "name": "Contact",
            "email": "Email",
            "typeform_asset_download": "Asset",
            "group": "Group",
            "sdr_name": "SDR",
            "self_booking": "Self Booked",
            "meeting_status": "15-min Status",
            "meeting_when": "15-min Meeting (CT)",
            "bds_name": "BDS",
            "lifecycle_stage": "Lifecycle",
        })
        # Caption with quick totals
        total_leads = int(len(detail))
        self_booked_n = int(leads["self_booking"].sum())
        booked_n = int((leads["meeting_status"] != "Not Booked").sum())
        st.markdown(
            f"**Lead Detail** — {total_leads} marketing leads · "
            f"{booked_n} have a 15-min meeting on record · "
            f"{self_booked_n} self-booked"
        )
        st.dataframe(
            cfg.style_unassigned(
                detail,
                columns=["SDR", "BDS", "Asset", "Group", "15-min Status"],
                green_when=lambda r: str(r.get("15-min Status", "")).strip()
                                      not in ("", "Not Booked"),
            ),
            use_container_width=True, hide_index=True,
            column_config={
                "Open": st.column_config.LinkColumn(
                    "Open", help="Open contact in HubSpot",
                    display_text="HubSpot ↗",
                ),
                "Self Booked": st.column_config.CheckboxColumn("Self Booked"),
            },
        )

    st.divider()

    # BDS + SME side by side
    col_bds, col_sme = st.columns(2)

    with col_bds:
        st.subheader("BDS Performance")
        st.caption("BDS holds the 15-min and books the Strategy call. Tracks: "
                   "discovery held → strategy set → strategy held.")
        from dashboard.data.reconcile import executive_bds_rollup
        bds = executive_bds_rollup(contacts_for_reps, meetings)
        if bds.empty:
            st.info("No BDS data for this window.")
        else:
            bds_display = bds.copy()
            bds_display["bds_id"] = bds_display["bds_id"].map(cfg.resolve_owner)
            bds_display["set_rate"] = bds_display["set_rate"].map(_fmt_pct)
            bds_display["show_rate"] = bds_display["show_rate"].map(_fmt_pct)
            bds_display = bds_display.rename(columns={
                "bds_id": "BDS",
                "discovery_held": "Discovery Held",
                "strategy_booked": "Strategy Booked",
                "set_rate": "Set %",
                "strategy_held": "Strategy Held",
                "show_rate": "Show %",
            })
            st.dataframe(
                cfg.style_unassigned(bds_display, columns=["BDS"]),
                use_container_width=True, hide_index=True,
            )

    with col_sme:
        st.subheader("SME Performance")
        st.caption("SME holds the Strategy call and closes the deal. Tracks: "
                   "strategy held → deals closed → revenue.")
        # Filter deals to those actually CLOSED in window so the rollup
        # doesn't count old closes that got hs_lastmodifieddate touched.
        # closedate (or stage_entry_date for DIY/90-Day) in [start, end].
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
        sme = executive_sme_rollup(
            contacts_for_reps, meetings, contact_deals, deals_for_sme,
            asset_to_group=cfg.ASSET_TO_GROUP,
            group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
            stages_closed_won=cfg.STAGES_CLOSED_WON,
        )
        if sme.empty:
            st.info("No SME data for this window.")
        else:
            sme_display = sme.copy()
            sme_display["sme_id"] = sme_display["sme_id"].map(cfg.resolve_owner)
            sme_display["close_rate"] = sme_display["close_rate"].map(_fmt_pct)
            sme_display["revenue"] = sme_display["revenue"].map(_fmt_money)
            sme_display["revenue_per_call"] = sme_display["revenue_per_call"].map(_fmt_money)
            sme_display = sme_display.rename(columns={
                "sme_id": "SME",
                "sme_calls_held": "Strategy Held",
                "deals_closed": "Deals Closed",
                "close_rate": "Close %",
                "revenue": "Revenue",
                "revenue_per_call": "Revenue / Call",
            })
            st.dataframe(
                cfg.style_unassigned(sme_display, columns=["SME"]),
                use_container_width=True, hide_index=True,
            )

    # =============================================================
    # Per-call detail tables — every 15-min and Strategy call with
    # the assigned BDS / SME visible. Lets Dr. Gumm see who's on
    # which calls and which leads are in play.
    # =============================================================
    if not meetings.empty and not contacts_for_reps.empty:
        # Exclude existing customers + internal team — they're not active
        # leads being worked. Existing-customer signal = lifecycle == "customer"
        # OR contract_tier populated (catches customers whose lifecycle wasn't
        # promoted). Same rule the Sales tab uses.
        cfr = contacts_for_reps.copy()
        cfr = cfr[
            ~cfr.apply(
                lambda r: (
                    cfg.is_internal_team_contact(r.get("email"))
                    or cfg.is_existing_customer(r.get("lifecycle_stage"),
                                                  r.get("contract_tier"))
                ),
                axis=1,
            )
        ]
        contact_lookup = cfr[[
            "hs_id", "name", "email", "bds", "sme", "typeform_asset_download",
        ]].rename(columns={"hs_id": "contact_id"})
        contact_lookup["contact_id"] = contact_lookup["contact_id"].astype(str)

        meetings_x = meetings.copy()
        meetings_x["contact_id"] = meetings_x["contact_id"].astype(str)
        meetings_x = meetings_x.merge(contact_lookup, on="contact_id", how="inner")

        # Filter meetings to the current dashboard window (start_time in window).
        # Without this, historical meetings within the 180-day data floor leak
        # into the Call Detail tables (e.g., a Dec 2025 strategy call appearing
        # on a 2026 YTD view).
        _mstart = pd.to_datetime(meetings_x["start_time"], utc=True, errors="coerce")
        _ws = pd.Timestamp(year=start.year, month=start.month, day=start.day, tz="UTC")
        _we = pd.Timestamp(year=end.year, month=end.month, day=end.day, tz="UTC") + pd.Timedelta(days=1)
        meetings_x = meetings_x[(_mstart >= _ws) & (_mstart < _we)]

        # Format start_time to Central Time
        meetings_x["scheduled_ct"] = cfg.format_ct_series(meetings_x["start_time"])

        types = meetings_x["activity_type"].fillna("").astype(str).str.lower()
        fifteen_detail = meetings_x[types.str.contains("15 min", na=False)].copy()
        strategy_detail = meetings_x[types.str.contains("strategy", na=False)].copy()

        # One row per contact — keep only the most recent meeting per contact
        if not fifteen_detail.empty:
            fifteen_detail = fifteen_detail.sort_values(
                "start_time", ascending=False, na_position="last"
            ).drop_duplicates(subset="contact_id", keep="first").reset_index(drop=True)
        if not strategy_detail.empty:
            strategy_detail = strategy_detail.sort_values(
                "start_time", ascending=False, na_position="last"
            ).drop_duplicates(subset="contact_id", keep="first").reset_index(drop=True)

        st.divider()
        st.subheader("BDS Call Detail")
        st.caption("Every 15-min discovery call, with the BDS assigned to hold it.")
        if fifteen_detail.empty:
            st.info("No 15-min calls in this window.")
        else:
            fifteen_detail["bds"] = fifteen_detail["bds"].map(cfg.resolve_owner)
            fifteen_detail["hubspot_link"] = fifteen_detail["contact_id"].apply(cfg.hubspot_contact_url)
            fifteen_view = fifteen_detail[[
                "hubspot_link",
                "bds", "name", "email", "typeform_asset_download",
                "outcome", "scheduled_ct",
            ]].rename(columns={
                "hubspot_link": "Open",
                "bds": "BDS",
                "name": "Contact",
                "email": "Email",
                "typeform_asset_download": "Asset",
                "outcome": "Outcome",
                "scheduled_ct": "Scheduled (CT)",
            }).sort_values(["BDS", "Scheduled (CT)"], ascending=[True, False])
            st.dataframe(
                cfg.style_unassigned(fifteen_view, columns=["BDS", "Asset", "Outcome"]),
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

        st.divider()
        st.subheader("SME Call Detail")
        st.caption("Every Strategy call, with the SME assigned to hold it.")
        if strategy_detail.empty:
            st.info("No Strategy calls in this window.")
        else:
            strategy_detail["sme"] = strategy_detail["sme"].map(cfg.resolve_owner)
            strategy_detail["hubspot_link"] = strategy_detail["contact_id"].apply(cfg.hubspot_contact_url)
            strategy_view = strategy_detail[[
                "hubspot_link",
                "sme", "name", "email", "typeform_asset_download",
                "outcome", "scheduled_ct",
            ]].rename(columns={
                "hubspot_link": "Open",
                "sme": "SME",
                "name": "Contact",
                "email": "Email",
                "typeform_asset_download": "Asset",
                "outcome": "Outcome",
                "scheduled_ct": "Scheduled (CT)",
            }).sort_values(["SME", "Scheduled (CT)"], ascending=[True, False])
            st.dataframe(
                cfg.style_unassigned(strategy_view, columns=["SME", "Asset", "Outcome"]),
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

    # === CLOSED DEALS (YTD) -- full detail ===
    st.divider()
    st.subheader("Closed Deals — Year to Date")
    st.caption("Every closed-won deal since Jan 1, with original asset attribution + sales cycle days.")
    deals_table = build_closed_deals_table(
        deals_ytd, contact_deals_ytd, contacts_ytd,
        asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
        source_overrides=cfg.CONTACT_SOURCE_OVERRIDES,
        stage_source_fallback=cfg.STAGE_SOURCE_FALLBACK,
    )
    if deals_table.empty:
        st.info("No closed-won deals YTD.")
    else:
        # Filter toggle
        show_marketing_only = st.checkbox(
            "Show marketing-attributed deals only",
            value=False,
            key="closed_deals_marketing_filter",
        )
        if show_marketing_only and not deals_table.empty:
            deals_table = deals_table[deals_table["is_marketing"] == True]

        display = deals_table.copy()
        display["hubspot_link"] = display["hs_id"].apply(cfg.hubspot_contact_url)
        display["sdr_owner"] = display["sdr_owner"].map(cfg.resolve_owner)
        display["bds"] = display["bds"].map(cfg.resolve_owner)
        display["sme"] = display["sme"].map(cfg.resolve_owner)
        # Format close date to CT
        close_dt = pd.to_datetime(display["closedate"], utc=True, errors="coerce")
        close_ct = close_dt.dt.tz_convert("America/Chicago")
        display["closedate"] = close_ct.apply(
            lambda x: x.strftime("%m/%d/%Y") if pd.notna(x) else "")
        display["deal_amount"] = display["deal_amount"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "—")
        display["sales_cycle_days"] = display["sales_cycle_days"].map(
            lambda x: f"{int(x)}" if pd.notna(x) else "—")
        display = display[[
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
        total_in_view = int(len(display))
        # Compute the marketing subset count for context
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
            cfg.style_unassigned(display,
                                  columns=["SDR", "BDS", "SME", "Group",
                                           "Plan", "Source", "Typeform"]),
            use_container_width=True, hide_index=True,
            column_config={
                "Open": st.column_config.LinkColumn(
                    "Open", help="Open contact in HubSpot",
                    display_text="HubSpot ↗"),
            },
        )
