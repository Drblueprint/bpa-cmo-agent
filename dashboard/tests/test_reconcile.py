"""Tests for marketing per-group aggregation."""
import pandas as pd

from dashboard.data.reconcile import group_marketing_metrics


def test_group_marketing_metrics_basic():
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "impressions": 50000, "clicks": 500, "fb_leads": 20},
        {"campaign_name": "DS | __PT__ ...", "group": "PT Recovery",
         "spend": 500.0, "impressions": 25000, "clicks": 250, "fb_leads": 10},
        {"campaign_name": "DS | __EMX__ ...", "group": "EMX",
         "spend": 200.0, "impressions": 8000, "clicks": 80, "fb_leads": 5},
    ])
    # 3 marketing contacts: 2 from Chiro asset, 1 PT
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "3", "typeform_asset_download": "PT Recovery Guide"},
    ])
    # 2 deals from marketing leads in 15-min booked stage
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "3", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "15min_booked", "amount": 0},
    ])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }
    stages_15min = {"15min_booked", "15min_held"}

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=asset_to_group,
        stages_15min_booked=stages_15min,
    )

    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["spend"] == 1000.0
    assert chiro["leads"] == 2
    assert chiro["calls_booked"] == 1
    assert chiro["cpl"] == 500.0
    assert chiro["cost_per_qualified_call"] == 1000.0


from dashboard.data.reconcile import pipeline_funnel


def test_pipeline_funnel_marketing_vs_all():
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "x"},
        {"hs_id": "2", "typeform_asset_download": "y"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",   "amount": 5000},
        {"deal_id": "d3", "dealstage": "closedwon",   "amount": 1000},  # not marketing
    ])
    stages = {
        "15min_booked":     {"15min_booked", "15min_held"},
        "strategy_booked":  set(),
        "closedwon":        {"closedwon"},
    }

    fn = pipeline_funnel(contacts, contact_deals, deals,
                         stage_groups=stages, marketing_only=True)
    assert fn["count"].loc[fn["stage"] == "15-min Booked"].iloc[0] == 1
    assert fn["count"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 1
    assert fn["revenue"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 5000.0

    fn_all = pipeline_funnel(contacts, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)
    assert fn_all["count"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 2
    assert fn_all["revenue"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 6000.0


from dashboard.data.reconcile import owner_rollup


def test_owner_rollup_by_sdr():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "Gage", "bds": "Scott Warren"},
        {"hs_id": "2", "sdr_owner": "Gage", "bds": "Garrett"},
        {"hs_id": "3", "sdr_owner": "Other", "bds": "Scott Warren"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
        {"contact_id": "3", "deal_id": "d3"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",    "amount": 5000},
        {"deal_id": "d3", "dealstage": "strategy_held", "amount": 0},
    ])
    stages = {
        "15min_booked":    {"15min_booked", "15min_held"},
        "strategy_booked": {"strategy_booked", "strategy_held"},
        "closedwon":       {"closedwon"},
    }

    by_sdr = owner_rollup(contacts, contact_deals, deals,
                          owner_field="sdr_owner", stage_groups=stages)

    gage = by_sdr[by_sdr["owner"] == "Gage"].iloc[0]
    assert gage["calls_15min"] == 1
    assert gage["closed_won"] == 1
    assert gage["closed_won_revenue"] == 5000.0
