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
    # Contact 1: has call date -> booked; Contact 2: nothing; Contact 3: MQL -> booked
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": "2026-05-10T10:00:00Z", "lifecycle_stage": "subscriber"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "3", "typeform_asset_download": "PT Recovery Guide",
         "fifteen_min_call_date": None, "lifecycle_stage": "marketingqualifiedlead"},
    ])
    # Deal data is no longer the source of truth for calls_booked
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }
    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=asset_to_group,
        stages_15min_booked=set(),  # unused - calls_booked driven by contact properties
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


from dashboard.data.reconcile import reconciliation_panel


def test_reconciliation_panel_basic():
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "fb_leads": 20},
        {"campaign_name": "DS | __PT__ ...", "group": "PT Recovery",
         "spend": 500.0, "fb_leads": 10},
    ])
    # HubSpot: 3 Chiro leads (from Chiro Audit PDF), 1 PT lead
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "3", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "4", "typeform_asset_download": "PT Recovery Guide"},
    ])
    # Hyros: 2 leads from a Chiro campaign source, 0 PT
    hyros = pd.DataFrame([
        {"lead_id": "h1", "first_source": "FB - __Chiro__ campaign"},
        {"lead_id": "h2", "first_source": "FB - __Chiro__ campaign"},
    ])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }

    result = reconciliation_panel(fb, contacts, hyros,
                                   asset_to_group=asset_to_group)

    # Verify expected columns
    assert set(result.columns) == {"group", "fb_leads", "hyros_leads",
                                    "hubspot_leads", "match_rate"}

    # Chiro: FB=20, Hyros=2, HubSpot=3 → match_rate = min(2,3)/3 ≈ 0.667
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["fb_leads"] == 20
    assert chiro["hyros_leads"] == 2
    assert chiro["hubspot_leads"] == 3
    assert abs(chiro["match_rate"] - (2/3)) < 1e-9

    # PT Recovery: FB=10, Hyros=0, HubSpot=1 → match_rate = 0/1 = 0.0
    pt = result[result["group"] == "PT Recovery"].iloc[0]
    assert pt["fb_leads"] == 10
    assert pt["hyros_leads"] == 0
    assert pt["hubspot_leads"] == 1
    assert pt["match_rate"] == 0.0


def test_group_marketing_metrics_empty_contact_deals():
    """Empty contact_deals and no call-date properties must not crash."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "impressions": 0, "clicks": 0, "fb_leads": 0},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group={"Chiro Audit PDF": "Chiro"},
        stages_15min_booked={"15min_booked"},
    )

    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["leads"] == 1
    assert chiro["calls_booked"] == 0
    assert chiro["cpl"] == 1000.0
    assert chiro["cost_per_qualified_call"] is None


def test_reconciliation_panel_empty_hyros():
    """Hyros may return zero rows; the panel should still render the other sources."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "fb_leads": 5},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
    ])
    hyros = pd.DataFrame()  # empty

    result = reconciliation_panel(fb, contacts, hyros,
                                   asset_to_group={"Chiro Audit PDF": "Chiro"})
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["hyros_leads"] == 0
    assert chiro["hubspot_leads"] == 1


def test_owner_rollup_empty_contact_deals():
    """No matching deals → empty result with columns intact, no sort crash."""
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "Gage", "bds": "Scott Warren"},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])
    stages = {
        "15min_booked":    {"15min_booked"},
        "strategy_booked": {"strategy_booked"},
        "closedwon":       {"closedwon"},
    }
    result = owner_rollup(contacts, contact_deals, deals,
                          owner_field="sdr_owner", stage_groups=stages)
    # Must have the column even if zero rows
    assert "closed_won_revenue" in result.columns


def test_group_marketing_metrics_uses_contact_properties_for_calls_booked():
    """A contact with fifteen_min_call_date OR lifecycle=MQL counts as booked,
    regardless of deal stage."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 100.0, "impressions": 1000, "clicks": 10, "fb_leads": 5},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": "2026-05-10T12:00:00Z", "lifecycle_stage": "lead"},
        {"hs_id": "2", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "marketingqualifiedlead"},
        {"hs_id": "3", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "subscriber"},
    ])
    # Deal data is irrelevant for calls_booked now
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group={"Chiro PDF": "Chiro"},
        stages_15min_booked=set(),  # ignored
    )
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["leads"] == 3
    assert chiro["calls_booked"] == 2  # contact 1 (date) + contact 2 (MQL)
