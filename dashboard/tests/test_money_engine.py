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
