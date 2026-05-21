"""Tests for Wave 1 SALES tab rollups: SDR / BDS / SME + windowed money."""
from datetime import date as _d

import pandas as pd

from dashboard.data.reconcile import (
    sales_sdr_rollup,
    sales_bds_rollup,
    sales_sme_rollup,
    windowed_sales_money,
)


def test_sales_sdr_rollup_basic():
    """SDR table combines AirCall dials/connects with HubSpot 15-min bookings."""
    contacts = pd.DataFrame([
        {"hs_id": "c1", "sdr_owner": "89638769", "bds": "44815718", "sme": "77643349",
         "phone": "555-0101", "mobilephone": None,
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-19T10:00:00Z"},
        {"hs_id": "c2", "sdr_owner": "89638769", "bds": "44815718", "sme": "77643349",
         "phone": "555-0102", "mobilephone": None,
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-19T10:00:00Z"},
        {"hs_id": "c3", "sdr_owner": "79870794", "bds": "44815718", "sme": "77643349",
         "phone": "555-0103", "mobilephone": None,
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-19T10:00:00Z"},
    ])
    calls = pd.DataFrame([
        {"call_id": "k1", "started_at_utc": 1747663200,
         "answered_at_utc": 1747663210, "duration": 60, "direction": "outbound",
         "status": "answered", "user_id": "1551010", "user_name": "Peyton",
         "raw_digits": "5550101", "phone_normalized": "5550101"},
        {"call_id": "k2", "started_at_utc": 1747666800,
         "answered_at_utc": None, "duration": 0, "direction": "outbound",
         "status": "missed", "user_id": "1551010", "user_name": "Peyton",
         "raw_digits": "5550102", "phone_normalized": "5550102"},
        {"call_id": "k3", "started_at_utc": 1747670400,
         "answered_at_utc": 1747670410, "duration": 30, "direction": "outbound",
         "status": "answered", "user_id": "1605109", "user_name": "Garrett",
         "raw_digits": "5550103", "phone_normalized": "5550103"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "c1",
         "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-05-20T15:00:00Z"},
        {"meeting_id": "m2", "contact_id": "c2",
         "activity_type": "15 min call", "outcome": "COMPLETE",
         "start_time": "2026-05-20T16:00:00Z"},
    ])

    out = sales_sdr_rollup(
        contacts=contacts,
        calls=calls,
        meetings=meetings,
        aircall_user_names={"1551010": "Peyton Fulghum", "1605109": "Garrett Hustedt"},
        excluded_users=set(),
        aircall_to_sdr_owner={"1551010": "89638769", "1605109": "79870794"},
        connect_duration_sec=10,
        conv_window_hours=24,
    )
    by_user = out.set_index("user_name")
    assert by_user.loc["Peyton Fulghum", "dials"] == 2
    assert by_user.loc["Peyton Fulghum", "pick_ups"] == 1
    assert by_user.loc["Peyton Fulghum", "appointments_booked"] == 2
    assert by_user.loc["Peyton Fulghum", "booking_rate"] == 2.0
    assert by_user.loc["Garrett Hustedt", "dials"] == 1
    assert by_user.loc["Garrett Hustedt", "pick_ups"] == 1
    assert by_user.loc["Garrett Hustedt", "appointments_booked"] == 0


def test_sales_bds_rollup_with_dq():
    """BDS table tracks appointments, shows, SME booked, and DQ."""
    contacts = pd.DataFrame([
        {"hs_id": "c1", "bds": "44815718"},
        {"hs_id": "c2", "bds": "44815718"},
        {"hs_id": "c3", "bds": "44815718"},
        {"hs_id": "c4", "bds": "61097347"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "c1",
         "activity_type": "15 min call", "outcome": "COMPLETE",
         "start_time": "2026-05-20T15:00:00Z"},
        {"meeting_id": "m2", "contact_id": "c2",
         "activity_type": "15 min call", "outcome": "COMPLETE",
         "start_time": "2026-05-20T16:00:00Z"},
        {"meeting_id": "m3", "contact_id": "c3",
         "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-05-22T15:00:00Z"},
        {"meeting_id": "m4", "contact_id": "c1",
         "activity_type": "Strategy Call", "outcome": "SCHEDULED",
         "start_time": "2026-05-23T15:00:00Z"},
        {"meeting_id": "m5", "contact_id": "c4",
         "activity_type": "15 min call", "outcome": "COMPLETE",
         "start_time": "2026-05-21T15:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "c2", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d2", "dealstage": "33595199", "amount": 0},
    ])

    out = sales_bds_rollup(
        contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        stages_15min_dq={"33595199", "1031449111"},
    )
    by_bds = out.set_index("bds_id")
    assert by_bds.loc["44815718", "appointments"] == 3
    assert by_bds.loc["44815718", "shows"] == 2
    assert by_bds.loc["44815718", "sme_booked"] == 1
    assert by_bds.loc["44815718", "disqualified"] == 1
    assert by_bds.loc["44815718", "show_rate"] == 2 / 3
    assert by_bds.loc["44815718", "booking_rate"] == 0.5
    assert by_bds.loc["44815718", "dq_rate"] == 0.5
    assert by_bds.loc["61097347", "appointments"] == 1
    assert by_bds.loc["61097347", "shows"] == 1


def test_sales_sme_rollup_with_dq():
    """SME table tracks Strategy appointments, showed, closed, DQ, revenue."""
    contacts = pd.DataFrame([
        {"hs_id": "c1", "sme": "77643349",
         "typeform_asset_download": "Top 10 typeform"},
        {"hs_id": "c2", "sme": "77643349",
         "typeform_asset_download": "Top 10 typeform"},
        {"hs_id": "c3", "sme": "24801837",
         "typeform_asset_download": "Recovery Program (PT) typeform"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "c1",
         "activity_type": "Strategy Call", "outcome": "COMPLETE",
         "start_time": "2026-05-20T15:00:00Z"},
        {"meeting_id": "m2", "contact_id": "c2",
         "activity_type": "Strategy Call", "outcome": "COMPLETE",
         "start_time": "2026-05-21T15:00:00Z"},
        {"meeting_id": "m3", "contact_id": "c3",
         "activity_type": "Strategy Call", "outcome": "SCHEDULED",
         "start_time": "2026-05-22T15:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "c1", "deal_id": "d1"},
        {"contact_id": "c2", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 50000},
        {"deal_id": "d2", "dealstage": "1205515693", "amount": 0},
    ])

    out = sales_sme_rollup(
        contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        asset_to_group={
            "Top 10 typeform": "Chiro",
            "Recovery Program (PT) typeform": "PT Recovery",
        },
        group_default_amount={"Chiro": 47928.0, "PT Recovery": 23928.0},
        stages_closed_won={"closedwon"},
        stages_strategy_dq={"1205515693", "1031449110"},
    )
    by_sme = out.set_index("sme_id")
    assert by_sme.loc["77643349", "appointments"] == 2
    assert by_sme.loc["77643349", "showed"] == 2
    assert by_sme.loc["77643349", "deals_closed"] == 1
    assert by_sme.loc["77643349", "disqualified"] == 1
    assert by_sme.loc["77643349", "close_rate"] == 0.5
    assert by_sme.loc["77643349", "dq_rate"] == 0.5
    assert by_sme.loc["77643349", "revenue"] == 50000.0
    assert by_sme.loc["24801837", "appointments"] == 1
    assert by_sme.loc["24801837", "showed"] == 0


def test_windowed_sales_money_filters_by_closedate():
    """Window-bounded money keeps only deals closed in the window."""
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 50000,
         "closedate": "2026-05-10T00:00:00Z", "createdate": "2026-01-05T00:00:00Z"},
        {"deal_id": "d2", "dealstage": "closedwon", "amount": 30000,
         "closedate": "2026-03-10T00:00:00Z", "createdate": "2026-01-01T00:00:00Z"},
        {"deal_id": "d3", "dealstage": "1163151789", "amount": 0,
         "closedate": None, "createdate": "2026-05-12T00:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "c1", "deal_id": "d1"},
        {"contact_id": "c2", "deal_id": "d2"},
        {"contact_id": "c3", "deal_id": "d3"},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "c1", "name": "A", "email": "a@x.com",
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-04-10T00:00:00Z",
         "created": "2026-04-10T00:00:00Z",
         "contract_tier": None, "sdr_owner": "", "bds": "", "sme": ""},
        {"hs_id": "c2", "name": "B", "email": "b@x.com",
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-02-10T00:00:00Z",
         "created": "2026-02-10T00:00:00Z",
         "contract_tier": None, "sdr_owner": "", "bds": "", "sme": ""},
        {"hs_id": "c3", "name": "C", "email": "c@x.com",
         "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": None,
         "created": "2026-05-01T00:00:00Z",
         "contract_tier": "FULL - C", "sdr_owner": "", "bds": "", "sme": ""},
    ])

    result = windowed_sales_money(
        deals, contact_deals, contacts,
        start=_d(2026, 5, 1), end=_d(2026, 5, 31),
        asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        stages_closed_won={"closedwon", "1163151789"},
        stages_closed_won_no_closedate={"1163151789"},
    )
    # d1 (50000) + d3 (47928 default for Chiro via tier suffix)
    assert result["window_closed_count"] == 2
    assert result["window_revenue"] == 50000.0 + 47928.0
