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
