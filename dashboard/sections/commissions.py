"""COMMISSIONS tab - per-rep monthly commissions for Garrett/Callum."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import dashboard.config as cfg
from dashboard.data.hubspot_loader import (
    load_marketing_contacts, load_contact_deals, load_closed_deals_in_window,
    load_meetings_in_window, load_contacts_by_ids, load_deal_contacts,
)
from dashboard.data.reconcile import (
    build_closed_deals_table, sdr_completion_contacts, compute_monthly_commissions,
)

_MONEY = lambda v: f"${v:,.0f}"


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start.replace(year=start.year + 1, month=1, day=1)
           if start.month == 12 else start.replace(month=start.month + 1, day=1))
    return start, nxt - timedelta(days=1)


def render_commissions(start: date, end: date) -> None:
    st.subheader("Commissions")
    st.caption("Monthly commission payouts by rep. SDR is warm/cold; BDS/SME/Gerri "
               "are flat. A 90-day pays a base; converting to a full (Primary-1) "
               "pays the bonus in the conversion month. DIY closes pay Gerri only.")
    today = date.today()
    msel = st.date_input("Commission month (pick any day in it)", value=today.replace(day=1),
                         key="commissions_month")
    if isinstance(msel, (tuple, list)):
        msel = msel[0] if msel else today
    m_start, m_end = _month_bounds(msel)
    st.caption(f"**Showing:** {m_start.strftime('%B %Y')}")

    # Closed deals over a broad window (Jan 1 of the month's year -> its end) so
    # conversions of deals that entered 90-day earlier are visible.
    broad_start = date(m_start.year, 1, 1)
    try:
        deals = load_closed_deals_in_window(
            broad_start, m_end, tuple(cfg.NEW_CUSTOMER_STAGES),
            tuple(cfg.STAGES_CLOSED_WON_NO_CLOSEDATE))
    except Exception as e:
        st.warning(f"Deals unavailable: {e}")
        deals = pd.DataFrame()
    # Contacts for those deals (for sdr_owner/bds/sme + warm/cold).
    contacts = pd.DataFrame()
    try:
        if not deals.empty:
            dc = load_deal_contacts(deals["deal_id"].astype(str).tolist())
            cids = list({str(x) for x in dc["contact_id"]}) if not dc.empty else []
            if cids:
                contacts = load_contacts_by_ids(cids)
    except Exception as e:
        st.warning(f"Deal contacts unavailable: {e}")
    try:
        cd = load_contact_deals(contacts["hs_id"].tolist()) if not contacts.empty \
            else pd.DataFrame(columns=["contact_id", "deal_id"])
    except Exception:
        cd = pd.DataFrame(columns=["contact_id", "deal_id"])

    ct = build_closed_deals_table(
        deals, cd, contacts, asset_to_group=cfg.ASSET_TO_GROUP,
        group_default_amount=cfg.GROUP_DEFAULT_DEAL_AMOUNT,
    ) if not deals.empty else pd.DataFrame(
        columns=["sdr_owner", "bds", "sme", "typeform", "dealstage",
                 "entered_primary1", "entered_90day", "closedate", "deal_amount"])

    # Held 15-min/strategy in the month, by SDR (needs meetings + their contacts).
    try:
        meetings = load_meetings_in_window(m_start, m_end)
    except Exception:
        meetings = pd.DataFrame(columns=["contact_id", "activity_type", "outcome", "start_time"])
    mc = pd.DataFrame()
    try:
        if not meetings.empty:
            mcids = list({str(x) for x in meetings["contact_id"].dropna()})
            if mcids:
                mc = load_contacts_by_ids(mcids)
    except Exception:
        pass
    call_contacts = sdr_completion_contacts(meetings, mc, m_start, m_end) if not mc.empty \
        else pd.DataFrame(columns=["sdr_owner", "contact_id", "contact_name", "event", "temp"])

    res = compute_monthly_commissions(ct, call_contacts, m_start, m_end, rates=cfg.COMMISSION_RATES)

    def _show(title, df, label_cols):
        st.markdown(f"**{title}**")
        if df.empty:
            st.info(f"No {title} commissions in {m_start.strftime('%B %Y')}.")
            return
        d = df.copy()
        d["Rep"] = d["rep_id"].map(cfg.resolve_owner)
        d = d[d["Rep"] != "(unassigned)"]
        for c in [c for c in d.columns if c not in ("rep_id", "Rep")]:
            d[c] = d[c].map(_MONEY)
        d = d[["Rep"] + label_cols]
        st.dataframe(d, use_container_width=True, hide_index=True)

    _EVENT_LABELS = {"disco": "15-min Call", "strategy": "Strategy Call",
                     "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion"}

    def _detail_expander(role, role_label):
        with st.expander(f"{role_label} commission detail (contacts)"):
            d = res["detail"]
            d = d[d["role"] == role].copy()
            if not d.empty:
                d["Rep"] = d["rep_id"].map(cfg.resolve_owner)
                d = d[d["Rep"] != "(unassigned)"]
            if d.empty:
                st.caption(f"No {role_label} commission detail in {m_start.strftime('%B %Y')}.")
                return
            d = d.sort_values(["Rep", "amount"], ascending=[True, False])
            d["Contact"] = d["contact_name"]
            d["Event"] = d["event"].map(_EVENT_LABELS)
            d["Open"] = d["contact_id"].map(cfg.hubspot_contact_url)
            d["Amount"] = d["amount"].map(_MONEY)
            d = d[["Rep", "Contact", "Event", "Amount", "Open"]]
            st.dataframe(
                d, use_container_width=True, hide_index=True,
                column_config={"Open": st.column_config.LinkColumn(
                    "Open", display_text="HubSpot ↗")})

    _show("SDR", res["sdr"].rename(columns={
        "disco": "15-min", "strategy": "Strategy", "full": "Full Close",
        "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["15-min", "Strategy", "Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("sdr", "SDR")
    _show("BDS", res["bds"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("bds", "BDS")
    _show("SME", res["sme"].rename(columns={
        "full": "Full Close", "ninety": "90-Day", "conversion": "Conversion", "total": "Total"}),
        ["Full Close", "90-Day", "Conversion", "Total"])
    _detail_expander("sme", "SME")
    g = res["gerri"]
    st.markdown("**Gerri**")
    st.metric("Gerri (flat $25 / close)", _MONEY(g["total"]), delta=f"{g['count']} closes",
              delta_color="off")
