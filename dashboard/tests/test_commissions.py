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


def test_multi_deal_totals():
    table = pd.DataFrame([
        {"typeform": "Top 10 typeform", "group": "Chiro", "sdr_owner": "1"},  # 2525
        {"typeform": "", "group": "PT Recovery", "sdr_owner": ""},            # 1325
    ])
    out = _calc(table)
    assert out["n_deals"] == 2
    assert out["total"] == 2525.0 + 1325.0
