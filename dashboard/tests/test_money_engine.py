import pytest
from dashboard.data.reconcile import classify_tier


@pytest.mark.parametrize("raw,plan,group", [
    ("1:  PRIMARY", "FULL", "Chiro"),
    ("PT - Primary", "FULL", "PT"),
    ("90-DAY - C", "90DAY", "Chiro"),
    ("DIY - C", "DIY", "Chiro"),
    ("BASIC - NOT CERTIFIED", "BASIC", "Chiro"),
    ("PT - DIY", "DIY", "PT"),
    ("", "UNKNOWN", "Chiro"),
    (None, "UNKNOWN", "Chiro"),
])
def test_classify_tier(raw, plan, group):
    assert classify_tier(raw) == (plan, group)


from datetime import date
from dashboard.data.reconcile import deal_money

RATES = dict(full_monthly=1997.0, full_term_months=24,
             ninety_day_amount=5991.0, diy_monthly=997.0, pt_multiplier=0.5)
TODAY = date(2026, 6, 9)


def test_deal_money_full_chiro():
    m = deal_money("FULL", "Chiro", "2026-04-15T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 47928.0          # 1997 * 24
    assert m["monthly"] == 1997.0
    assert m["est_cash_collected"] == 1997.0 * 2   # Apr->Jun = 2 months
    assert m["counts_as_sale"] is True


def test_deal_money_full_pt_halves():
    m = deal_money("FULL", "PT", "2026-06-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 23964.0          # 47928 / 2
    assert m["monthly"] == 998.5
    assert m["est_cash_collected"] == 998.5 * 1    # same month -> 1


def test_deal_money_full_caps_at_term():
    m = deal_money("FULL", "Chiro", "2023-01-01T00:00:00Z", TODAY, **RATES)
    assert m["est_cash_collected"] == 1997.0 * 24  # capped at 24mo


def test_deal_money_ninety_day():
    m = deal_money("90DAY", "Chiro", "2026-05-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 5991.0
    assert m["est_cash_collected"] == 5991.0       # one-time, not monthly
    assert m["monthly"] == 0.0


def test_deal_money_diy_accrues_no_tcv():
    m = deal_money("DIY", "Chiro", "2026-03-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 0.0              # no contract total
    assert m["monthly"] == 997.0
    assert m["est_cash_collected"] == 997.0 * 3    # Mar->Jun = 3


def test_deal_money_basic_excluded():
    m = deal_money("BASIC", "Chiro", "2026-05-01T00:00:00Z", TODAY, **RATES)
    assert m["booked_revenue"] == 0.0
    assert m["est_cash_collected"] == 0.0
    assert m["counts_as_sale"] is False


import pandas as pd
from dashboard.data.reconcile import build_closed_deals_table

RATE_KW = dict(full_monthly=1997.0, full_term_months=24,
               ninety_day_amount=5991.0, diy_monthly=997.0, pt_multiplier=0.5)


def test_build_closed_deals_table_uses_tier_not_amount():
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 40000.0,
         "createdate": "2026-04-01T00:00:00Z", "closedate": "2026-04-15T00:00:00Z",
         "stage_entry_date": None},
        {"deal_id": "d2", "dealstage": "1163151789", "amount": 40000.0,
         "createdate": "2026-03-01T00:00:00Z", "closedate": None,
         "stage_entry_date": "2026-03-10T00:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "c1", "deal_id": "d1"},
        {"contact_id": "c2", "deal_id": "d2"},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "c1", "name": "Full Doc", "email": "f@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": "1:  PRIMARY",
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-04-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
        {"hs_id": "c2", "name": "DIY Doc", "email": "d@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": "DIY - C",
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-03-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
    ])
    t = build_closed_deals_table(
        deals, contact_deals, contacts,
        asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        today=date(2026, 6, 9), **RATE_KW,
    )
    full = t[t["hs_id"] == "c1"].iloc[0]
    diy = t[t["hs_id"] == "c2"].iloc[0]
    # deal.amount ($40k) ignored; FULL booked = 47928
    assert full["deal_amount"] == 47928.0
    assert full["est_cash_collected"] == 1997.0 * 2
    assert full["plan"] == "FULL"
    # DIY: no booked TCV, cash accrues (Mar->Jun = 3)
    assert diy["deal_amount"] == 0.0
    assert diy["est_cash_collected"] == 997.0 * 3
    assert diy["plan"] == "DIY"


from dashboard.data.reconcile import compute_ytd_money


def test_compute_ytd_money_tier_revenue():
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 40000.0,
         "createdate": "2026-04-01T00:00:00Z", "closedate": "2026-04-15T00:00:00Z",
         "stage_entry_date": None},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "c1", "deal_id": "d1"}])
    contacts = pd.DataFrame([
        {"hs_id": "c1", "name": "Full Doc", "email": "f@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": "1:  PRIMARY",
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-04-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
    ])
    result = compute_ytd_money(
        deals, contact_deals, contacts,
        asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        today=date(2026, 6, 9), **RATE_KW,
    )
    # deal.amount ($40k) ignored; FULL booked = 47928
    assert result["total_new_revenue"] == 47928.0
    assert result["total_est_cash_collected"] == 1997.0 * 2  # Apr->Jun = 2mo
    assert result["mkt_new_revenue"] == 47928.0
    assert result["mkt_est_cash_collected"] == 1997.0 * 2


def test_build_closed_deals_table_unknown_tier_zero_money():
    """A closed-won deal whose contact has an unmapped/None contract_tier
    derives no money: deal_amount and est_cash_collected are 0.0 and plan is
    UNKNOWN (deal.amount placeholder is never used)."""
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 40000.0,
         "createdate": "2026-04-01T00:00:00Z", "closedate": "2026-04-15T00:00:00Z",
         "stage_entry_date": None},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "c1", "deal_id": "d1"}])
    contacts = pd.DataFrame([
        {"hs_id": "c1", "name": "Mystery Doc", "email": "m@x.com",
         "typeform_asset_download": "Top 10 typeform", "contract_tier": None,
         "send_contract_options": "", "analytics_source_data_1": "",
         "typeform_submission_date": None, "created": "2026-04-01T00:00:00Z",
         "sdr_owner": "", "bds": "", "sme": ""},
    ])
    t = build_closed_deals_table(
        deals, contact_deals, contacts,
        asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        today=date(2026, 6, 9), **RATE_KW,
    )
    row = t[t["hs_id"] == "c1"].iloc[0]
    assert row["deal_amount"] == 0.0
    assert row["est_cash_collected"] == 0.0
    assert row["plan"] == "UNKNOWN"
