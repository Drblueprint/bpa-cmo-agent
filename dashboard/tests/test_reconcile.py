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
