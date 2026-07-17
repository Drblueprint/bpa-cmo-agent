"""Tests for compute_close_commissions — per-closed-deal sales commissions."""
import pandas as pd

from dashboard.data.reconcile import compute_close_commissions

SDR = {"warm": 200.0, "cold": 400.0}
BDS = 300.0
SME = {"Chiro": 2000.0, "PT Recovery": 1000.0, "EMX": 1000.0,
       "MUDA": 1000.0, "_default": 1000.0}
FLAT = 25.0


def _calc(table):
    return compute_close_commissions(
        table, sdr_close=SDR, bds_close=BDS, sme_close=SME, flat_close=FLAT,
    )


def test_empty_table():
    out = _calc(pd.DataFrame())
    assert out["total"] == 0.0
    assert out["n_deals"] == 0


def test_warm_chiro_with_sdr():
    # Warm (has typeform) Chiro close, SDR assigned:
    # SDR 200 + BDS 300 + SME 2000 + Gerri 25 = 2525
    table = pd.DataFrame([
        {"typeform": "Top 10 typeform", "group": "Chiro", "sdr_owner": "89638769"},
    ])
    out = _calc(table)
    assert out["sdr_total"] == 200.0
    assert out["bds_total"] == 300.0
    assert out["sme_total"] == 2000.0
    assert out["flat_total"] == 25.0
    assert out["total"] == 2525.0
    assert out["n_deals"] == 1


def test_cold_pt_no_sdr():
    # Cold (no typeform) PT close, NO SDR assigned:
    # SDR 0 (no SDR) + BDS 300 + SME 1000 (PT) + Gerri 25 = 1325
    table = pd.DataFrame([
        {"typeform": "", "group": "PT Recovery", "sdr_owner": ""},
    ])
    out = _calc(table)
    assert out["sdr_total"] == 0.0
    assert out["sme_total"] == 1000.0
    assert out["total"] == 1325.0


def test_cold_with_sdr_charges_400():
    # Cold but an SDR IS assigned -> cold rate 400 applies
    table = pd.DataFrame([
        {"typeform": "", "group": "EMX", "sdr_owner": "79870794"},
    ])
    out = _calc(table)
    assert out["sdr_total"] == 400.0
    assert out["sme_total"] == 1000.0  # EMX = Event Chiro
    assert out["total"] == 400.0 + 300.0 + 1000.0 + 25.0


def test_unknown_group_uses_default():
    table = pd.DataFrame([
        {"typeform": "x", "group": "(unmapped)", "sdr_owner": "1"},
    ])
    out = _calc(table)
    assert out["sme_total"] == 1000.0  # _default


def test_muda_overrides_chiro_rate():
    # MUDA send_contract bills SME at $1000 even though group is Chiro ($2000).
    table = pd.DataFrame([
        {"typeform": "x", "group": "Chiro", "sdr_owner": "1",
         "send_contract": "MUDA - CHIRO (Multi Unit Discount Agreement)"},
    ])
    out = _calc(table)
    assert out["sme_total"] == 1000.0  # MUDA, not Chiro $2000
    # warm 200 + bds 300 + sme 1000 + gerri 25
    assert out["total"] == 1525.0


def test_non_muda_chiro_keeps_2000():
    table = pd.DataFrame([
        {"typeform": "x", "group": "Chiro", "sdr_owner": "1",
         "send_contract": "24 Month CHIRO - Solo"},
    ])
    out = _calc(table)
    assert out["sme_total"] == 2000.0


def test_multi_deal_totals():
    table = pd.DataFrame([
        {"typeform": "Top 10 typeform", "group": "Chiro", "sdr_owner": "1"},  # 2525
        {"typeform": "", "group": "PT Recovery", "sdr_owner": ""},            # 1325
    ])
    out = _calc(table)
    assert out["n_deals"] == 2
    assert out["total"] == 2525.0 + 1325.0


from dashboard.config import COMMISSION_RATES as CR


def test_commission_rates_shape():
    assert CR["sdr"]["disco_complete"] == {"warm": 20.0, "cold": 100.0}
    assert CR["sdr"]["strategy_complete"] == {"warm": 100.0, "cold": 100.0}
    assert CR["sdr"]["full_close"] == {"warm": 200.0, "cold": 400.0}
    assert CR["sdr"]["ninety_day"] == {"warm": 50.0, "cold": 100.0}
    assert CR["sdr"]["conversion_bonus"] == {"warm": 150.0, "cold": 300.0}
    assert CR["bds"] == {"full_close": 300.0, "ninety_day": 50.0, "conversion_bonus": 250.0}
    assert CR["sme"] == {"full_close": 2000.0, "ninety_day": 500.0, "conversion_bonus": 1500.0}
    assert CR["gerri_per_close"] == 25.0
    assert CR["stages"]["full"] == ("24094605", "closedwon")
    assert CR["stages"]["ninety_day"] == "1123458844"
    assert CR["stages"]["diy"] == "1163151789"


import pandas as pd
from dashboard.data.reconcile import build_closed_deals_table


def test_closed_deals_table_exposes_stage_and_entry_dates():
    deals = pd.DataFrame([{
        "deal_id": "d1", "dealstage": "24094605", "amount": 5000.0,
        "closedate": "2026-06-15T00:00:00Z", "stage_entry_date": None,
        "createdate": "2026-01-01T00:00:00Z",
        "entered_primary1": "2026-06-15T00:00:00Z", "entered_90day": "2026-05-01T00:00:00Z",
    }])
    contacts = pd.DataFrame([{
        "hs_id": "c1", "name": "X", "email": "x@x.com",
        "typeform_asset_download": "Top 10 typeform", "sdr_owner": "S", "bds": "B", "sme": "M",
        "send_contract_options": "", "created": "2026-01-01T00:00:00Z",
    }])
    cd = pd.DataFrame([{"contact_id": "c1", "deal_id": "d1"}])
    t = build_closed_deals_table(
        deals, cd, contacts, asset_to_group={"Top 10 typeform": "Chiro"},
        group_default_amount={}, source_overrides=None, stage_source_fallback=None,
    )
    row = t.iloc[0]
    assert row["dealstage"] == "24094605"
    assert row["entered_primary1"] == "2026-06-15T00:00:00Z"
    assert row["entered_90day"] == "2026-05-01T00:00:00Z"


from datetime import date
from dashboard.data.reconcile import sdr_completions_by_owner


def test_sdr_completions_by_owner_warm_cold_and_type():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "S1", "typeform_asset_download": "Top 10 typeform"},  # warm
        {"hs_id": "2", "sdr_owner": "S1", "typeform_asset_download": ""},                  # cold
    ])
    meetings = pd.DataFrame([
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "COMPLETED",
         "start_time": "2026-06-03T15:00:00Z"},                          # warm disco held
        {"contact_id": "2", "activity_type": "Strategy Call", "outcome": "COMPLETE - QUALIFIED",
         "start_time": "2026-06-04T15:00:00Z"},                          # cold strat held
        {"contact_id": "1", "activity_type": "15 min call", "outcome": "SCHEDULED",
         "start_time": "2026-06-05T15:00:00Z"},                          # not held -> ignored
    ])
    out = sdr_completions_by_owner(meetings, contacts, date(2026, 6, 1), date(2026, 6, 30))
    assert out["S1"] == {"disco_warm": 1, "disco_cold": 0, "strat_warm": 0, "strat_cold": 1}


from dashboard.data.reconcile import compute_monthly_commissions
from dashboard.config import COMMISSION_RATES as CR

_JUN = (date(2026, 6, 1), date(2026, 6, 30))
_MAY = (date(2026, 5, 1), date(2026, 5, 31))


def _deal(did, stage, *, sdr="S1", bds="B1", sme="M1", warm=True,
          entered_primary1=None, entered_90day=None, closedate=None):
    return {
        "hs_id": did, "sdr_owner": sdr, "bds": bds, "sme": sme,
        "typeform": "Top 10 typeform" if warm else "",
        "dealstage": stage, "entered_primary1": entered_primary1,
        "entered_90day": entered_90day, "closedate": closedate, "deal_amount": 0.0,
    }


def test_commissions_direct_full_close_warm():
    deals = pd.DataFrame([_deal("d1", "24094605", warm=True,
                                entered_primary1="2026-06-10T00:00:00Z")])
    res = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)
    sdr = res["sdr"].set_index("rep_id")
    assert sdr.loc["S1", "full"] == 200.0 and sdr.loc["S1", "ninety"] == 0.0 and sdr.loc["S1", "conversion"] == 0.0
    assert res["bds"].set_index("rep_id").loc["B1", "full"] == 300.0
    assert res["sme"].set_index("rep_id").loc["M1", "full"] == 2000.0
    assert res["gerri"]["count"] == 1 and res["gerri"]["total"] == 25.0


def test_commissions_90day_then_conversion_split_across_months():
    # Entered 90-day in May, converted to Primary-1 in June. Cold lead.
    deal = _deal("d2", "24094605", warm=False,
                 entered_90day="2026-05-20T00:00:00Z",
                 entered_primary1="2026-06-12T00:00:00Z")
    deals = pd.DataFrame([deal])
    may = compute_monthly_commissions(deals, {}, *_MAY, rates=CR)["sdr"].set_index("rep_id")
    jun = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["sdr"].set_index("rep_id")
    assert may.loc["S1", "ninety"] == 100.0 and may.loc["S1", "conversion"] == 0.0 and may.loc["S1", "full"] == 0.0
    assert jun.loc["S1", "conversion"] == 300.0 and jun.loc["S1", "full"] == 0.0 and jun.loc["S1", "ninety"] == 0.0
    # BDS/SME conversion in June
    assert compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["bds"].set_index("rep_id").loc["B1", "conversion"] == 250.0
    assert compute_monthly_commissions(deals, {}, *_JUN, rates=CR)["sme"].set_index("rep_id").loc["M1", "conversion"] == 1500.0


def test_commissions_diy_pays_only_gerri():
    deals = pd.DataFrame([_deal("d3", "1163151789", entered_primary1=None,
                                closedate="2026-06-05T00:00:00Z")])
    res = compute_monthly_commissions(deals, {}, *_JUN, rates=CR)
    assert res["sdr"].empty or "S1" not in res["sdr"].set_index("rep_id").index
    assert res["gerri"]["count"] == 1 and res["gerri"]["total"] == 25.0


def test_commissions_sdr_call_completions():
    comps = {"S1": {"disco_warm": 2, "disco_cold": 1, "strat_warm": 1, "strat_cold": 0}}
    res = compute_monthly_commissions(pd.DataFrame(columns=["hs_id"]), comps, *_JUN, rates=CR)
    sdr = res["sdr"].set_index("rep_id")
    # disco: 2*20 + 1*100 = 140 ; strategy: 1*100 = 100
    assert sdr.loc["S1", "disco"] == 140.0 and sdr.loc["S1", "strategy"] == 100.0
    assert sdr.loc["S1", "total"] == 240.0
